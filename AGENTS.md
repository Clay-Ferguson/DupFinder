# Notes to AI Agents

## What this is

DupFinder is a PyQt6 desktop app that finds files with identical contents under a folder (always recursively) and lists them in groups. 

It reports, and offers one action of its own: **Delete** (the trash-can button) permanently removes the selected files (any number, in any groups; the tree is ExtendedSelection) after one Yes/No confirmation, then drops each row — and its group, if one file is left. There is no move feature. Open and the folder button hand files to other programs.

`finddupes.py` / `finddupes.md` are a reference CLI script from another AI, kept untouched and excluded from ruff. Do not edit them or import from them.

## Running

```bash
./start.sh [FOLDER]
```

uv-run, `package = false`, no install step. `windowchrome` is a sibling checkout (`../windowchrome`, editable). The folder argument is optional and only prefills the Folder row; startup problems are message boxes (through `messages.py`, like every box), since the app is launched from a desktop icon.

Installed from the `.deb` it runs `/usr/lib/dupfinder` under `python3 -I`. See `packaging/build-deb.sh`.

## Layout

- `__main__.py` — argparse, `QApplication`, excepthook, `ensure_config`, folder resolution.
- `config.py` — YAML config (`Settings` frozen dataclass; `load_settings`/`save_settings`), Sonar's `KEYS` table design. Read at the moment of use (once per scan, `open_command()` per Open click).
- `patterns.py` — `PathFilter` (what the walk skips), `pattern_problems()`, and the dialog's one-pattern-per-line text form. Same pattern syntax and rules as Sonar. Pure.
- `sizes.py` — `parse_megabytes` ("0.5" → 524288 bytes; the min-size setting is in MB), `megabytes_problem`, `format_size`. Pure.
- `scanner.py` — **the algorithm**: `find_duplicates(root, filter, min_size, progress, cancel) -> ScanResult`. Pure, no Qt; its module docstring explains the stages.
- `worker.py` — `ScanWorker(QThread)` wrapping `find_duplicates`; signals `progressed`, `done`, `failed`; `stop()` sets the cancel event.
- `launch.py` — `open_file()` (configured command, default `xdg-open`), `open_folder()`, `build_open_argv`, the child environment, and `delete_file()` (`os.remove`; a file already gone counts as deleted).
- `window.py` — `MainWindow`: windowchrome's title bar and border (`apply_frame()`), then menus, folder row, Find Dups/Stop, the results `QTreeWidget` (group rows + file rows), the control bar (Open, folder, Delete), status text.
- `settings.py` — Options ▸ Settings. Adding a setting = one `_add_*()` call + a field on `Settings` + a row in `config.KEYS` (an import-time assert catches a field with no row).
- `statusbar.py` — `ScanStatusBar` (spinner + green busy state), Sonar's.
- `help.py` — Options ▸ User Guide via `windowchrome.show_markdown()`, framed after it is shown.
- `messages.py` — `critical()`, `warning()`, `information()`, `question()`: drop-in replacements for the static `QMessageBox` calls, same arguments and results, that frame the box before running it. Call them as `messages.warning(...)`, never imported by name, so the tests' `dialogs` fixture can replace them.
- `style.py` — shared look, Sonar's minus what only the preview used, plus `SCROLLBAR_HANDLE`.

## Rules

- **Every button is made by `style.action_button()`** (or `icon_button()`), never `QPushButton(...)` directly (`tests/test_rules.py` guards it).
- **No shells.** The Open command is split with `shlex` and run as an argv list. Never `shell=True` (guarded).
- **Only the widget modules import Qt** (`window`, `worker`, `statusbar`, `settings`, `help`, `messages`, `style`). `config`, `patterns`, `sizes`, `scanner` and `launch` are plain Python; `test_the_non_widget_modules_never_import_qt` guards it, and the `.deb` smoke test imports exactly those without Qt.
- **Config loading must never raise.** Bad or missing config degrades to defaults. Saving rewrites the whole file via temp file + `os.replace`.
- **The config is read once per scan**, in `start_scan`, and what the scan needs is handed to the worker; nothing reads it mid-scan.
- **Nothing in the window is touched from the worker thread.** Results and progress arrive through queued signals. `closeEvent` must stop and `wait()` a running worker — destroying a running QThread aborts the process.
- **Sizes are binary but labelled KB/MB/GB** (1 MB = 1024 × 1024 bytes), the Windows/everyday convention, by the user's choice. Never write KiB/MiB/GiB in the UI, docs or comments.
- **The scanner never follows symlinks** and never opens anything but regular files (a FIFO would block forever). Keep `follow_symlinks=False` on every `is_dir`/`is_file`/`stat` in the walk.
- **Delete is confirmed, every time, then done one file at a time.** It acts only on the selected file rows (group rows are ignored), asks once with No as the default, then calls `_delete_row` — the single-file delete — for each in turn, reporting a failure and going on. Keep it that simple: no batching or reordering of the deletes. It clears the selection afterwards so deletions never chain. Never add a delete that skips the question. Open and the folder button are enabled only with exactly one file row selected.
- **A cancelled scan returns no groups.** Partial results could list files as duplicates that a full comparison would have separated.
- **Every window DupFinder opens wears windowchrome's frame, and only through `apply_frame()`** (windowchrome README §13): the main window, the Settings dialog, the User Guide, and every message box. The static `QMessageBox.critical()`/`warning()`/`information()`/`question()` (and any `QInputDialog.get…()`) are never called directly — they go through `messages.py`, and a box built by hand calls `apply_frame(box)` before `exec()` (`test_message_boxes_go_through_messages` guards the static calls; `tests/test_frame.py` checks each window). A window that skips this shows the system's dark title bar beside the framed one. Use the default `FrameColors`. The frame owns a window's contents margins, so margins go on its *layout*, never on the window; and the title bar is inside the window, which is why `MainWindow` adds `frame.title_bar.height()` to the height it asks for. File pickers (`QFileDialog.getExistingDirectory`) stay the desktop's own chooser, which belongs to another process and can't be framed — never switch to `DontUseNativeDialog` for it. Don't style the title bar any other way, don't subclass `TitleBar`/`WindowFrame` or connect its buttons to window slots, and don't add anything application-wide for it.
- **Every `apply_scrollbars()` passes `handle=SCROLLBAR_HANDLE`** (`style.py`, the GTK theme's `#777777`), to match Start Menu and the GTK apps (windowchrome README §9).
- **The menus are windowchrome's** (README §14 there): `apply_menus(bar)` with no arguments, so the gray edges, padding and item width are the shared ones and the highlight follows the palette. There is no menu stylesheet in `style.py`; change the menu look in windowchrome. A `QMenu` built on its own (a context menu) is not the bar's child and needs its own `apply_menus()` call. `STATUS_BAR_BORDER` is windowchrome's `DIVIDER_BORDER`, not a copy of the gray.
- Keep the window title just "DupFinder", and **do not restyle the rendered help documents** (both as in Sonar).
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
