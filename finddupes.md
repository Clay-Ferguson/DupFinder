I've written `finddupes.py`. It uses only Python's standard library, so there's nothing to install. It only reports duplicates; it never deletes or changes anything.

```bash
chmod +x finddupes.py
./finddupes.py ~/Projects -x node_modules -x .git -x '*.tmp' -x '*.log'
```

**How exclude patterns work:**
- Each `-x` adds one pattern, and you can repeat it as many times as you like.
- To keep a list of patterns, put one per line in a text file and use `-X excludes.txt`. Lines starting with `#` are treated as comments.
- A pattern with no `/` matches any file or folder name, like `*.tmp` or `node_modules`.
- A pattern with a `/` matches a path relative to the folder you're scanning, like `photos/raw/*`.
- Excluded folders are skipped completely; the script never goes inside them.
- Put quotes around the patterns, or your shell will expand them before the script sees them.

**Why it should be much faster than a bash one-liner:**
- It groups files by size first. A file whose size no other file shares is never read.
- For files that do share a size, it hashes only the first 64 KiB. Only files that still match after that get a full SHA-256 hash.
- Hashing runs on several threads at once. On a spinning hard drive, use `-j 1` or `-j 2`, because many threads reading at once slows those drives down.

**Other options and behavior:**
- `--min-size 1K` ignores files smaller than that size. By default only empty files are skipped.
- `-o dupes.txt` saves the results to a file instead of printing them.
- Results are sorted so the groups wasting the most space come first.
- Symlinks are skipped.
- Hard links to the same file aren't reported as duplicates, since they don't use extra space.

I tested it on a small folder of sample files. It found the real duplicates and left out excluded folders and file types, symlinks, hard links, and empty files. It also correctly kept apart two files whose first 64 KiB were identical but which differed later on.