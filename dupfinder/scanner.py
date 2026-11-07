"""Finding the duplicates: the whole algorithm, with no Qt in it.

`find_duplicates(root, ...)` walks `root` and returns every set of two or
more files whose contents are byte-for-byte identical. Names, timestamps and
permissions are ignored; nothing is ever written, moved or deleted.

The work is staged so that each stage reads as little as it can, and each one
only sees what the stage before it could not rule out:

  1. Walk.   One pass over the tree with `os.scandir`, which hands back each
             entry's type without a stat, and a stat only for regular files.
             Excluded folders are never entered. Symlinks are never followed —
             a link is not a copy, and following them invites loops.
  2. Inodes. Hard links are one file under several names: they share an
             inode, take the space once, and are not duplicates. Only the
             first name seen is kept.
  3. Size.   Files can only be identical if they are the same size, so a file
             whose size no other file shares is ruled out without ever being
             opened. On a typical tree this is most of them.
  4. Sample. Each remaining file has its first and last 64 KiB hashed. The
             tail matters as much as the head: photos from one camera and
             videos from one encoder share long identical headers and differ
             later, and the tail rules them out here instead of costing a full
             read. A file of 128 KiB or less is read *whole* by this stage, so
             its sample digest is already its content digest and it is done.
  5. Hash.   Whatever still matches is read in full and hashed with SHA-256,
             in 1 MiB chunks with a cancel check between them, so Stop is
             answered promptly even part-way through a 50 GB disk image.

Stages 4 and 5 run on `HASH_THREADS` threads: file reads and hashlib both
release the GIL, so several files really are read at once.

SHA-256 rather than something faster-on-paper: with the SHA extensions every
current x86 CPU has, OpenSSL's SHA-256 runs at ~3 GB/s against BLAKE2b's ~1 GB/s
(measured, Python 3.14), and either is faster than the disk feeding it. A
match on a 256-bit hash is treated as identical content; there is no byte-by-
byte comparison afterwards, because there is nothing left for one to catch.

Progress is reported through a callback, always from the calling thread and at
most every `PROGRESS_INTERVAL` seconds (plus once at each stage change), so
the caller can hand it straight to a GUI without throttling it again.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from .patterns import PathFilter

# How much of each end of a file the sample stage reads.
SAMPLE_BYTES = 64 * 1024

# A file this size or smaller is read whole by the sample stage.
WHOLE_FILE_BYTES = 2 * SAMPLE_BYTES

# The read size for a full hash. Large enough that the per-call overhead
# vanishes, small enough that a cancel check comes round several hundred times
# a second.
CHUNK_BYTES = 1024 * 1024

# Threads for stages 4 and 5. Enough to keep an SSD's queue busy; few enough
# that a spinning disk is not driven into seeking between eight files at once,
# which is slower than reading them one after another.
HASH_THREADS = 4

# The longest gap between two progress reports, in seconds.
PROGRESS_INTERVAL = 0.1

# The stages a progress report can be from.
PHASE_WALK = "walk"
PHASE_SAMPLE = "sample"
PHASE_HASH = "hash"


@dataclass(frozen=True)
class Progress:
    """Where a scan has got to.

    `files` is how many files the walk has accepted so far. `done` and `total`
    count what the current stage has to get through: files for the sample
    stage, bytes for the hash stage, and nothing (0 and 0) during the walk,
    whose total is unknown until it ends.
    """

    phase: str
    files: int
    done: int = 0
    total: int = 0


@dataclass(frozen=True)
class DupGroup:
    """Two or more files with identical contents, all `size` bytes long.

    `paths` are absolute and sorted.
    """

    size: int
    paths: tuple[str, ...]

    @property
    def reclaimable(self) -> int:
        """The space freed by keeping one copy and removing the rest."""
        return self.size * (len(self.paths) - 1)


@dataclass
class ScanResult:
    """What a scan found. `groups` is empty when it was cancelled."""

    root: str
    groups: list[DupGroup] = field(default_factory=list)
    files_scanned: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def duplicate_files(self) -> int:
        """Every file in every group, the first copy of each included."""
        return sum(len(group.paths) for group in self.groups)

    @property
    def reclaimable(self) -> int:
        return sum(group.reclaimable for group in self.groups)


class Cancelled(Exception):
    """Raised inside the scan when the cancel event is set."""


# -- small helpers ---------------------------------------------------------------


class _Counter:
    """A number several hashing threads add to and the scan thread reads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.value = 0

    def add(self, amount: int) -> None:
        with self._lock:
            self.value += amount


class _Reporter:
    """Calls the progress callback, but not more often than it is worth."""

    def __init__(self, callback: Callable[[Progress], None] | None) -> None:
        self._callback = callback
        self._last = 0.0

    def __call__(self, progress: Progress, force: bool = False) -> None:
        if self._callback is None:
            return
        now = time.monotonic()
        if force or now - self._last >= PROGRESS_INTERVAL:
            self._last = now
            self._callback(progress)


def _error(path: str, exc: OSError) -> str:
    """One line for the "could not be read" list."""
    return f"{path}: {exc.strerror or exc}"


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled


# -- stage 1: the walk --------------------------------------------------------------


def _walk(
    root: str,
    path_filter: PathFilter,
    min_size: int,
    errors: list[str],
    cancel: threading.Event,
) -> Iterable[tuple[str, int, tuple[int, int]]]:
    """Yield `(path, size, (device, inode))` for every file worth comparing.

    Depth-first with an explicit stack, so a deep tree cannot hit Python's
    recursion limit. Entries are sorted by name in each folder, which costs
    next to nothing and makes the walk — and so which name a hard-linked file
    is reported under — the same on every run.

    `is_dir`/`is_file` with `follow_symlinks=False` are what keep links out:
    both are False for a symlink, whatever it points at. They are also False
    for FIFOs, sockets and device nodes, which is the other half of the point —
    opening a FIFO to hash it would block the scan forever.
    """
    stack = [root]
    while stack:
        _check(cancel)
        folder = stack.pop()
        try:
            with os.scandir(folder) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            errors.append(_error(folder, exc))
            continue
        subfolders: list[str] = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not path_filter.skip_dir(entry.name, entry.path):
                        subfolders.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    if path_filter.skip_file(entry.name, entry.path):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    if stat.st_size > 0 and stat.st_size >= min_size:
                        yield entry.path, stat.st_size, (stat.st_dev, stat.st_ino)
            except OSError as exc:
                errors.append(_error(entry.path, exc))
        # Reversed, so that popping the stack visits them in name order.
        stack.extend(reversed(subfolders))


# -- stages 4 and 5: hashing ----------------------------------------------------------


def sample_digest(path: str, size: int) -> bytes:
    """SHA-256 of the first and last `SAMPLE_BYTES` of `path`, or all of it.

    A file of `WHOLE_FILE_BYTES` or less is read whole, so for those this is
    simply the digest of the content and `full_digest` is never needed.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        if size <= WHOLE_FILE_BYTES:
            digest.update(handle.read())
        else:
            digest.update(handle.read(SAMPLE_BYTES))
            handle.seek(-SAMPLE_BYTES, os.SEEK_END)
            digest.update(handle.read(SAMPLE_BYTES))
    return digest.digest()


def full_digest(path: str, cancel: threading.Event, progress: _Counter) -> bytes:
    """SHA-256 of all of `path`, adding each chunk's length to `progress`."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            _check(cancel)
            digest.update(chunk)
            progress.add(len(chunk))
    return digest.digest()


def _run_all(
    pool: ThreadPoolExecutor,
    jobs: dict[str, Callable[[], bytes]],
    cancel: threading.Event,
    report: Callable[[], None],
) -> dict[str, bytes | OSError]:
    """Run every job on `pool`; each path's digest, or the error it raised.

    Waits in `PROGRESS_INTERVAL` slices so `report` can run on this thread
    while the pool works. Raises `Cancelled` as soon as the event is set,
    after dropping every job that has not started yet.
    """
    futures: dict[Future[bytes], str] = {pool.submit(job): path for path, job in jobs.items()}
    pending: set[Future[bytes]] = set(futures)
    while pending:
        _done, pending = wait(pending, timeout=PROGRESS_INTERVAL, return_when=FIRST_EXCEPTION)
        if cancel.is_set():
            for future in pending:
                future.cancel()
            raise Cancelled
        report()
    results: dict[str, bytes | OSError] = {}
    for future, path in futures.items():
        try:
            results[path] = future.result()
        except OSError as exc:
            results[path] = exc
    return results


def _regroup(
    groups: Iterable[list[str]],
    digests: dict[str, bytes | OSError],
    errors: list[str],
) -> list[list[str]]:
    """Split each group by digest, keeping only the sub-groups of two or more.

    A file whose read failed is dropped (and recorded); the rest of its group
    carries on without it.
    """
    out: list[list[str]] = []
    for group in groups:
        by_digest: dict[bytes, list[str]] = defaultdict(list)
        for path in group:
            digest = digests[path]
            if isinstance(digest, OSError):
                errors.append(_error(path, digest))
            else:
                by_digest[digest].append(path)
        out.extend(paths for paths in by_digest.values() if len(paths) > 1)
    return out


# -- the whole scan ---------------------------------------------------------------------


def find_duplicates(
    root: str,
    path_filter: PathFilter | None = None,
    min_size: int = 1,
    progress: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
) -> ScanResult:
    """Every group of identical files under `root`, largest waste first.

    Never raises for anything on disk: unreadable folders and files are listed
    in `ScanResult.errors` and the scan carries on without them. Setting
    `cancel` from another thread ends the scan within about a tenth of a
    second, returning a result marked `cancelled` with no groups.
    """
    root = os.path.abspath(root)
    path_filter = path_filter or PathFilter()
    cancel = cancel or threading.Event()
    report = _Reporter(progress)
    result = ScanResult(root)
    try:
        _scan(root, path_filter, min_size, cancel, report, result)
    except Cancelled:
        result.cancelled = True
        result.groups = []
    return result


def _scan(
    root: str,
    path_filter: PathFilter,
    min_size: int,
    cancel: threading.Event,
    report: _Reporter,
    result: ScanResult,
) -> None:
    errors = result.errors

    # Stages 1-3: walk, fold hard links together, group by size.
    report(Progress(PHASE_WALK, 0), force=True)
    by_size: dict[int, list[str]] = defaultdict(list)
    seen: set[tuple[int, int]] = set()
    for path, size, inode in _walk(root, path_filter, min_size, errors, cancel):
        result.files_scanned += 1
        report(Progress(PHASE_WALK, result.files_scanned))
        if inode in seen:
            continue
        seen.add(inode)
        by_size[size].append(path)
    sizes = {path: size for size, paths in by_size.items() for path in paths}
    groups = [paths for paths in by_size.values() if len(paths) > 1]
    del by_size, seen

    with ThreadPoolExecutor(max_workers=HASH_THREADS) as pool:
        # Stage 4: sample both ends (or all, for a small file).
        candidates = [path for group in groups for path in group]
        sampled = _Counter()

        def sample_job(path: str) -> Callable[[], bytes]:
            def job() -> bytes:
                try:
                    return sample_digest(path, sizes[path])
                finally:
                    sampled.add(1)

            return job

        def report_sample() -> None:
            report(Progress(PHASE_SAMPLE, result.files_scanned, sampled.value, len(candidates)))

        report(Progress(PHASE_SAMPLE, result.files_scanned, 0, len(candidates)), force=True)
        digests = _run_all(pool, {p: sample_job(p) for p in candidates}, cancel, report_sample)
        groups = _regroup(groups, digests, errors)

        # A small file was read whole, so its group is already final.
        finished = [group for group in groups if sizes[group[0]] <= WHOLE_FILE_BYTES]
        groups = [group for group in groups if sizes[group[0]] > WHOLE_FILE_BYTES]

        # Stage 5: hash what is left in full.
        candidates = [path for group in groups for path in group]
        total = sum(sizes[path] for path in candidates)
        hashed = _Counter()

        def report_hash() -> None:
            report(Progress(PHASE_HASH, result.files_scanned, hashed.value, total))

        report(Progress(PHASE_HASH, result.files_scanned, 0, total), force=True)
        jobs = {p: (lambda p=p: full_digest(p, cancel, hashed)) for p in candidates}
        digests = _run_all(pool, jobs, cancel, report_hash)
        finished += _regroup(groups, digests, errors)

    result.groups = sorted(
        (DupGroup(sizes[group[0]], tuple(sorted(group))) for group in finished),
        key=lambda group: (-group.reclaimable, group.paths[0]),
    )
