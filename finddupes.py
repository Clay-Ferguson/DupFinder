#!/usr/bin/env python3
"""
finddupes.py - find duplicate files by content (SHA-256), recursively.

Only file contents are compared. Names, timestamps and permissions are ignored.
Nothing is ever deleted or modified; the script only reports.

How it stays fast:
  1. Walk the tree once, skipping excluded folders entirely (never entered).
  2. Group files by size. A file with a unique size can't have a duplicate,
     so it is never read at all.
  3. For same-size files, hash only the first 64 KiB. Files whose first
     block differs are dropped.
  4. Only the remaining candidates get a full SHA-256 hash.
  Hashing runs on several threads (hashlib releases the GIL while hashing).

Usage examples:
  finddupes.py ~/Pictures
  finddupes.py ~/Projects -x node_modules -x .git -x '*.tmp' -x '*.log'
  finddupes.py /data -X my_excludes.txt --min-size 1K -o dupes.txt

Exclude patterns (-x, repeatable; or -X FILE with one pattern per line):
  * A pattern with no '/' is matched against each file or folder NAME,
    e.g.  '*.tmp'   'node_modules'   '.git'   'backup*'
  * A pattern containing '/' is matched against the path RELATIVE to the
    folder being scanned, e.g.  'photos/raw/*'   '*/cache/*'
  Matching folders are skipped completely, including everything inside them.
  Patterns use shell-style wildcards (* ? [abc]) and are case-sensitive.
  Quote them so your shell doesn't expand them.
"""

import argparse
import hashlib
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatchcase

PARTIAL_BYTES = 64 * 1024
CHUNK = 1024 * 1024


def parse_size(text):
    """'1500', '4K', '10M', '2G' -> bytes (binary multipliers)."""
    text = text.strip().upper().removesuffix("B").removesuffix("I")
    mult = {"K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}
    if text and text[-1] in mult:
        return int(float(text[:-1]) * mult[text[-1]])
    return int(text)


def load_patterns(args):
    patterns = list(args.exclude or [])
    for path in args.exclude_from or []:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    name_pats = [p for p in patterns if "/" not in p]
    path_pats = [p.strip("/") for p in patterns if "/" in p]
    return name_pats, path_pats


def is_excluded(name, relpath, name_pats, path_pats):
    return any(fnmatchcase(name, p) for p in name_pats) or any(
        fnmatchcase(relpath, p) for p in path_pats
    )


def walk(roots, name_pats, path_pats, min_size, errors):
    """Yield (path, size, (dev, inode)) for every regular file not excluded.
    Symlinks are never followed or reported."""
    for root in roots:
        root = os.path.abspath(root)
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError as e:
                errors.append(f"{d}: {e.strerror}")
                continue
            for entry in entries:
                rel = os.path.relpath(entry.path, root)
                if is_excluded(entry.name, rel, name_pats, path_pats):
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        stack.append(entry.path)
                    elif entry.is_file():
                        st = entry.stat()
                        if st.st_size >= min_size:
                            yield entry.path, st.st_size, (st.st_dev, st.st_ino)
                except OSError as e:
                    errors.append(f"{entry.path}: {e.strerror}")


def hash_file(path, partial):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            if partial:
                h.update(f.read(PARTIAL_BYTES))
            else:
                while chunk := f.read(CHUNK):
                    h.update(chunk)
    except OSError as e:
        return path, None, e.strerror
    return path, h.hexdigest(), None


def refine(groups, partial, pool, errors):
    """Split each group of candidate paths by hash; keep sub-groups of 2+."""
    paths = [p for g in groups for p in g]
    digests = {}
    for path, digest, err in pool.map(lambda p: hash_file(p, partial), paths):
        if err:
            errors.append(f"{path}: {err}")
        else:
            digests[path] = digest
    out = []
    for g in groups:
        by_hash = defaultdict(list)
        for p in g:
            if p in digests:
                by_hash[digests[p]].append(p)
        out.extend(sub for sub in by_hash.values() if len(sub) > 1)
    return out, digests


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def main():
    ap = argparse.ArgumentParser(
        description="Find duplicate files by content (SHA-256). Reports only; never deletes.",
        epilog="See the top of this script for exclude-pattern rules and examples.",
    )
    ap.add_argument("folders", nargs="+", help="folder(s) to scan recursively")
    ap.add_argument("-x", "--exclude", action="append", metavar="PATTERN",
                    help="exclude files/folders matching PATTERN (repeatable)")
    ap.add_argument("-X", "--exclude-from", action="append", metavar="FILE",
                    help="read exclude patterns from FILE, one per line (# comments ok)")
    ap.add_argument("--min-size", default="1", metavar="SIZE",
                    help="ignore files smaller than SIZE, e.g. 1K, 10M (default: 1, skips empty files)")
    ap.add_argument("-j", "--jobs", type=int, default=min(8, os.cpu_count() or 4),
                    help="hashing threads (default: %(default)s; use 1-2 for a spinning hard drive)")
    ap.add_argument("-o", "--output", metavar="FILE", help="write results to FILE instead of the screen")
    args = ap.parse_args()

    for f in args.folders:
        if not os.path.isdir(f):
            ap.error(f"not a folder: {f}")

    name_pats, path_pats = load_patterns(args)
    min_size = parse_size(args.min_size)
    errors = []

    def status(msg):
        print(msg, file=sys.stderr, flush=True)

    # 1. Walk and group by size, collapsing hard links (same inode = same file).
    by_size = defaultdict(list)
    seen_inodes = set()
    count = 0
    for path, size, inode in walk(args.folders, name_pats, path_pats, min_size, errors):
        count += 1
        if inode in seen_inodes:
            continue
        seen_inodes.add(inode)
        by_size[size].append(path)
    groups = [g for g in by_size.values() if len(g) > 1]
    status(f"Scanned {count:,} files; {sum(map(len, groups)):,} share a size with another file.")

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        # 2. Partial hash of the first 64 KiB.
        groups, _ = refine(groups, partial=True, pool=pool, errors=errors)
        status(f"{sum(map(len, groups)):,} files left after checking the first 64 KiB.")
        # 3. Full hash.
        groups, digests = refine(groups, partial=False, pool=pool, errors=errors)

    sizes = {}
    for g in groups:
        sizes[g[0]] = os.path.getsize(g[0])
    groups.sort(key=lambda g: sizes[g[0]] * (len(g) - 1), reverse=True)

    out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    try:
        for g in groups:
            size = sizes[g[0]]
            print(f"# {len(g)} copies, {human(size)} each, sha256 {digests[g[0]]}", file=out)
            for p in sorted(g):
                print(p, file=out)
            print(file=out)
    finally:
        if out is not sys.stdout:
            out.close()

    wasted = sum(sizes[g[0]] * (len(g) - 1) for g in groups)
    status(f"Found {len(groups):,} group{'s' if len(groups) != 1 else ''} of duplicates; {human(wasted)} could be freed.")
    if errors:
        status(f"{len(errors)} files/folders could not be read:")
        for e in errors[:20]:
            status(f"  {e}")
        if len(errors) > 20:
            status(f"  ... and {len(errors) - 20} more")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)