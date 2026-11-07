# Notes to AI Agents

## What this is

DupFinder is a PyQt6 desktop app that finds files with identical contents under a folder (always recursively) and lists them in groups. 

It reports, and offers one action of its own: **Delete** (the trash-can button) permanently removes the single selected file after a Yes/No confirmation, then drops its row — and its group, if one file is left. There is no move or bulk-delete feature. Open and the folder button hand files to other programs.

`finddupes.py` / `finddupes.md` are a reference CLI script from another AI, kept untouched and excluded from ruff. Do not edit them or import from them.

## Running

```bash
./start.sh [FOLDER]
```

uv-run, `package = false`, no install step. `windowchrome` is a sibling checkout (`../windowchrome`, editable). The folder argument is optional and only prefills the Folder row; startup problems are `QMessageBox`es, since the app is launched from a desktop icon.

Installed from the `.deb` it runs `/usr/lib/dupfinder` under `python3 -I`. See `packaging/build-deb.sh`.

## Layout

- `__main__.py` — argparse, `QApplication`, excepthook, `ensure_config`, folder resolution.
- `config.py` — YAML config (`Settings` frozen dataclass; `load_settings`/`save_settings`), Sonar's `KEYS` table design. Read at the moment of use (once per scan, `open_command()` per Open click).
- `patterns.py` — `PathFilter` (what the walk skips), `pattern_problems()`, and the dialog's one-pattern-per-line text form. Same pattern syntax and rules as Sonar. Pure.
- `sizes.py` — `parse_megabytes` ("0.5" → 524288 bytes; the min-size setting is in MB), `megabytes_problem`, `format_size`. Pure.
- `scanner.py` — **the algorithm**: `find_duplicates(root, filter, min_size, progress, cancel) -> ScanResult`. Pure, no Qt; its module docstring explains the stages.
- `worker.py` — `ScanWorker(QThread)` wrapping `find_duplicates`; signals `progressed`, `done`, `failed`; `stop()` sets the cancel event.
- `launch.py` — `open_file()` (configured command, default `xdg-open`), `open_folder()`, `build_open_argv`, the child environment, and `delete_file()` (`os.remove`; a file already gone counts as deleted).
- `window.py` — `MainWindow`: menus, folder row, Find Dups/Stop, the results `QTreeWidget` (group rows + file rows), the control bar (Open, folder, Delete), status text.
- `settings.py` — Options ▸ Settings. Adding a setting = one `_add_*()` call + a field on `Settings` + a row in `config.KEYS` (an import-time assert catches a field with no row).
- `statusbar.py` — `ScanStatusBar` (spinner + green busy state), Sonar's.
- `help.py` — Options ▸ User Guide via `windowchrome.show_markdown()`.
- `style.py` — shared look, Sonar's minus what only the preview used.

## Rules

- **Every button is made by `style.action_button()`** (or `icon_button()`), never `QPushButton(...)` directly (`tests/test_rules.py` guards it).
- **No shells.** The Open command is split with `shlex` and run as an argv list. Never `shell=True` (guarded).
- **Only the widget modules import Qt** (`window`, `worker`, `statusbar`, `settings`, `help`, `style`). `config`, `patterns`, `sizes`, `scanner` and `launch` are plain Python; `test_the_non_widget_modules_never_import_qt` guards it, and the `.deb` smoke test imports exactly those without Qt.
- **Config loading must never raise.** Bad or missing config degrades to defaults. Saving rewrites the whole file via temp file + `os.replace`.
- **The config is read once per scan**, in `start_scan`, and what the scan needs is handed to the worker; nothing reads it mid-scan.
- **Nothing in the window is touched from the worker thread.** Results and progress arrive through queued signals. `closeEvent` must stop and `wait()` a running worker — destroying a running QThread aborts the process.
- **Sizes are binary but labelled KB/MB/GB** (1 MB = 1024 × 1024 bytes), the Windows/everyday convention, by the user's choice. Never write KiB/MiB/GiB in the UI, docs or comments.
- **The scanner never follows symlinks** and never opens anything but regular files (a FIFO would block forever). Keep `follow_symlinks=False` on every `is_dir`/`is_file`/`stat` in the walk.
- **Delete is one file, confirmed, every time.** It acts only on the current file row, asks first with No as the default, and clears the selection afterwards so deletions never chain. Never add a delete that skips the question or takes more than one file.
- **A cancelled scan returns no groups.** Partial results could list files as duplicates that a full comparison would have separated.
- **Do not style the title bar**, keep the window title just "DupFinder", and **do not restyle the rendered help documents** (both as in Sonar).
- **`docs/` is runtime content** shipped in the `.deb`; heading renames break the guide's Contents links. `tests/test_help.py` checks every link and anchor.
- Do not commit to git, or offer to. Only the human developer commits. Never add a dependency without asking.

## The algorithm, in brief

Walk (prune excluded folders, skip symlinks/non-regular/empty/too-small files) → collapse hard links by `(st_dev, st_ino)` → group by size, drop singletons → hash first+last 64 KB (a file ≤ 128 KB is read whole here and is finished) → full SHA-256 of what still matches. Stages 4–5 run on a 4-thread pool; progress is reported from the calling thread only, at most every 0.1 s. Groups are sorted by reclaimable bytes (`size × (copies − 1)`).

## Testing

```bash
./tests/run.sh                        # everything
./tests/run.sh tests/test_scanner.py  # one file
./lint.sh                             # ruff, pyright, bash -n
```

`run.sh` sets `QT_QPA_PLATFORM=offscreen` and pulls pytest/pytest-qt in with `uv run --with`. See `tests/README.md` for the fixtures (the autouse `dialogs` fixture that stops a `QMessageBox` hanging the run, and `conf`, which points the config at a temp file).
