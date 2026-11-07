"""Running a scan off the GUI thread.

`scanner.find_duplicates` is plain blocking Python that can take minutes on a
large tree, so the window runs it on a `ScanWorker` — a QThread — and hears
back through two signals: `progressed` with each `scanner.Progress` (already
throttled to about ten a second by the scanner), and `done` once with the
`ScanResult`, or `failed` with a traceback if the scanner itself broke.

Both are emitted on the worker thread and delivered on the GUI thread: the
worker object lives on the GUI thread, so Qt queues every connection made to
it from there. Nothing in the window is touched from the worker.
"""

from __future__ import annotations

import threading
import traceback

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from .patterns import PathFilter
from .scanner import find_duplicates


class ScanWorker(QThread):
    """One scan of `root`, started with `start()` and ended early by `stop()`."""

    progressed = pyqtSignal(object)  # scanner.Progress
    done = pyqtSignal(object)  # scanner.ScanResult
    failed = pyqtSignal(str)  # the traceback

    def __init__(
        self,
        root: str,
        path_filter: PathFilter,
        min_size: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.root = root
        self._filter = path_filter
        self._min_size = min_size
        self._cancel = threading.Event()

    def run(self) -> None:
        # Caught here rather than left to sys.excepthook: the hook shows a
        # dialog, and a dialog must not be built on a thread other than the
        # GUI's. The window shows this one instead.
        try:
            result = find_duplicates(
                self.root,
                self._filter,
                self._min_size,
                progress=self.progressed.emit,
                cancel=self._cancel,
            )
        except Exception:  # pragma: no cover - a bug in the scanner
            self.failed.emit(traceback.format_exc())
            return
        self.done.emit(result)

    def stop(self) -> None:
        """Ask the scan to end. It does within about a tenth of a second,
        and still emits `done` — with a result marked `cancelled`."""
        self._cancel.set()
