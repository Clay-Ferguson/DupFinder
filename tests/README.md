# Testing notes

Run with `./tests/run.sh` (see `AGENTS.md`). Arguments go straight to pytest.

## Layout

- `test_scanner.py` — the algorithm, no Qt: what is and is not a duplicate, which stage rules a file out (a spy on `scanner.full_digest` proves small files and tail differences never get a full read), hard links, symlinks, FIFOs, patterns, unreadable files, cancelling, progress.
- `test_patterns.py`, `test_sizes.py`, `test_config.py` — the pure helpers.
- `test_launch.py` — Open-command argv building, Open / folder handoffs, and the guard that the non-widget modules never import Qt.
- `test_window.py` — the window end to end: groups and status text after a real scan, Open / folder on file rows only, bad settings, Stop, closing mid-scan.
- `test_settings.py` — the dialog: loading, saving, refusing bad input.
- `test_help.py` — the Options menu and every link/anchor in `docs/`.
- `test_rules.py` — AGENTS.md rules read off the source: no hand-built buttons, no shells.

## Fixtures worth knowing (`conftest.py`)

- `conf` — **use it in every test that reads settings.** Points `config.CONFIG_PATH` at a temp file (read at call time, so rebinding the attribute is enough) and returns a `save(...)` function for changing settings mid-test. The Open command defaults to `/bin/true`.
- `dialogs` — **autouse, and load-bearing.** A `QMessageBox` still blocks for a click under `offscreen`, so one raised by code under test would hang the run. This intercepts them and returns what would have been shown, which is also how to assert a problem *was* reported.
- `spawned` — records every argv `launch` would start instead of starting it, and resolves `xdg-open` even where it is not installed.
- `dup_tree` — a small tree with a known answer (see its docstring).
- `scan(folder)` — opens a window, starts a scan and waits until the results are on screen.
- `block(seed, size)` / `write(path, data)` — deterministic content and file creation.
- `needs_permissions` — skips unreadable-file tests as root, which reads them anyway.

## Gotchas

- Wait for a scan with `qtbot.waitUntil(lambda: not window.scanning)`, not `waitSignal(worker.done)`: the signal can be emitted before a `waitSignal` connects to it.
- To test Stop without a slow tree, replace `dupfinder.worker.find_duplicates` (as `slow_scan` in `test_window.py` does), since the worker looks it up at run time.
- `win.grab().save(path)` renders the window to a PNG when you want to see a layout.
