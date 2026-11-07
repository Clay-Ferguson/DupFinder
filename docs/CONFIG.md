# DupFinder configuration

DupFinder reads one file:

```
~/.config/dupfinder/dupfinder-config.yaml
```

It is created with defaults the first time DupFinder runs. It holds the two lists of glob patterns that decide which files a scan looks at, the smallest file worth comparing, and the command the Open button runs.

Edit it from **Options ▸ Settings** in the window's menu bar. The file can still be edited by hand; the dialog and the file are two views of the same settings. Saving from the dialog **rewrites the file**, so any comments or blank lines you added by hand are replaced by DupFinder's own. Keys DupFinder does not know about are kept.

The file is read when a scan starts and when Open is pressed, so changes apply without restarting.

## The file

```yaml
scan:
  # Files to compare. An EMPTY list means "every file" (the default).
  included: []

  # Whether "included" is applied. false compares every file but keeps the list.
  use_included: true

  # Whether "excluded" is applied. false skips nothing but keeps the list.
  use_excluded: true

  # Folders and files to skip.
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
    - "*/.venv/*"
    - "*/__pycache__/*"
    - "*/venv/*"
    - "*/.svn/*"
    - "*/.hg/*"
    - "*/build/*"
    - "*/dist/*"
    - "*/.next/*"
    - "*/.nuxt/*"

  # Ignore files smaller than this many megabytes.
  min_size_mb: "0"

open:
  # The command the Open button runs.
  command: "xdg-open"
```

## `scan.included`

A list of glob patterns matched against each file's **name**, at any depth. Empty means every file is compared. With any entry at all, only files matching one of the patterns are compared.

- Patterns cannot contain `/`; DupFinder refuses to scan with one, and says which.
- Matching is case-sensitive: `*.jpg` does not match `PHOTO.JPG`. List both if you need both.
- Folders are never tested against this list, so `*.jpg` still looks inside every folder.

Example: `["*.jpg", "*.JPG", "*.png", "*.mp4"]`

## `scan.use_included`

`true` or `false`. With `false` the `included` list is ignored — every file is compared — but it stays in the file, so turning it back on restores it.

## `scan.excluded`

A list of patterns, written the way `find -path` writes them:

| Pattern | Skips |
|---|---|
| `*/name/*` | every folder called `name`, at any depth. It is never entered. |
| `*/a/b/*` | every folder whose path ends in `a/b`. It is never entered. |
| `*/docs/*.tmp` | any file or folder whose full path matches. `*` crosses `/` here. |
| `*.log` | any file or folder whose name matches, at any depth. |

A pattern containing `/` must start with `*/`, because it is matched against the full, absolute path; DupFinder refuses one that does not, rather than silently skipping nothing. Matching is case-sensitive.

## `scan.use_excluded`

`true` or `false`. With `false` nothing is skipped, but the list is kept.

## `scan.min_size_mb`

The smallest file compared, in **megabytes** (1 MB is 1024 × 1024 bytes, the same unit the results list uses). Fractions are allowed: `"0.5"` is 512 KiB. Examples: `"0"`, `"0.5"`, `"10"`. Write just the number — no unit suffix. A bare number without quotes works too. `"0"` compares every file; empty files are always ignored, whatever this says.

Older versions had `scan.min_size`, a number of bytes. It is no longer read, so a config written by one of them starts at `"0"` until you set this.

## `open.command`

The program the Open button runs. It is split the way a shell would split it — quotes and backslashes work — but no shell is involved, so pipes, redirection and `~` do not. The selected file is appended as the last argument, or substituted wherever `%s` appears.

Examples: `"xdg-open"`, `"/usr/bin/code"`, `"eog"`, `"gnome-terminal -- vim %s"`

Empty or missing means `xdg-open`.

## When the file is broken

A missing file, a file that is not valid YAML, or a key holding the wrong kind of value never stops DupFinder: each bad key falls back to its default on its own. The Settings dialog says when the file could not be read, so that pressing Save — which replaces it — is a choice rather than a surprise.
