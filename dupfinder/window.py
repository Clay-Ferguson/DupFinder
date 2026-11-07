"""The window: a folder row, the duplicate groups, and three buttons under them.

The layout is Sonar's with the preview pane taken away: the results run the
full width of the window, and the Open and folder buttons that sat under
Sonar's preview sit under the results instead, with a Delete (trash) button
alone at the far right of the same row.

The results are a two-level tree. Each top-level row is one group of
identical files and says how many copies there are and how much space they
waste; the files themselves are its children, one per row, with their size and
modification time beside them — the two things anyone deciding which copy to
keep wants to see.

A scan runs on a `ScanWorker` thread. While it does, the Find Dups button
becomes Stop and the rest of the header is disabled, since a scan can take
minutes and the only thing worth doing to one mid-way is ending it.
"""

from __future__ import annotations

import os
import time

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from windowchrome import apply_scrollbars, close_markdown_windows

from . import APP_NAME
from .config import Settings, load_settings
from .help import show_user_guide
from .launch import delete_file, open_file, open_folder
from .patterns import PathFilter, pattern_problems
from .scanner import PHASE_HASH, PHASE_SAMPLE, Progress, ScanResult
from .settings import MIN_SIZE_LABEL, show_settings
from .sizes import format_size, megabytes_problem, parse_megabytes
from .statusbar import ScanStatusBar
from .style import (
    ACTION_BUTTON_PADDING,
    CONTROL_BAR_PADDING,
    DANGER_BUTTON_BG,
    PRIMARY_BUTTON_BG,
    SECONDARY_BUTTON_BG,
    action_button,
    action_button_style,
    icon_button,
    menu_style,
    mono_font,
    results_tree_style,
    selection_button_bg,
)
from .worker import ScanWorker

# The absolute path a file row stands for. The row's *text* is only the part
# below the scanned folder, so it is not a usable path on its own — everything
# that opens a file must read this role instead. Group rows carry None.
PATH_ROLE = Qt.ItemDataRole.UserRole
# The size of each file in a group, on the group row: what its label is
# rebuilt from when a Delete leaves it with fewer copies. File rows carry None.
SIZE_ROLE = Qt.ItemDataRole.UserRole + 1

# The tree's columns.
COL_PATH, COL_SIZE, COL_MODIFIED = range(3)
HEADERS = ("File", "Size", "Modified")

# How a file's modification time is shown: to the minute, which is enough to
# tell "the copy I edited this morning" from "the backup from last spring".
TIME_FORMAT = "%Y-%m-%d %H:%M"

# The widest text the Size and Modified columns can hold, which fixes their
# widths, and the room added around it for the item padding and a gap.
WIDEST_SIZE = "1023.9 MB"
WIDEST_TIME = "2000-12-31 23:59"
COLUMN_PADDING = 32

# How many unreadable paths the end-of-scan warning lists before "and N more".
MAX_ERRORS_SHOWN = 20

FIND_LABEL = "Find Dups"
STOP_LABEL = "Stop"

OPEN_TIP = "Open the selected file with the Open command (Options ▸ Settings)"
FOLDER_TIP = "Show the folder holding the selected file in the file manager"
DELETE_TIP = "Delete the selected file permanently (asks first)"


def printable(text: str) -> str:
    """`text` with any undecodable filename bytes shown as U+FFFD.

    Paths from `os.scandir` carry lone surrogates for bytes that are not
    UTF-8 — lossless, which is what lets PATH_ROLE still open the file, but
    not something to put in front of a reader. Only labels go through this.
    """
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def plural(count: int, noun: str) -> str:
    """`1 file`, `2 files`, `1,234 files`."""
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def group_label(size: int, copies: int) -> str:
    """A group row's text: "3 copies · 4.2 MB each · 8.4 MB reclaimable"."""
    return (
        f"{copies} copies · {format_size(size)} each · "
        f"{format_size(size * (copies - 1))} reclaimable"
    )


class MainWindow(QMainWindow):
    def __init__(self, folder: str) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 700)

        # The running scan, or None. Its root is also what the rows' labels
        # are relative to, kept on `_root` so the labels stay right after the
        # worker is gone and the folder field has been edited.
        self._worker: ScanWorker | None = None
        # Set by Stop, so the progress still queued behind it cannot paint
        # over "Stopping…" before the worker has wound down.
        self._stopping = False
        self._root = ""
        self._build_menus()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- folder row --------------------------------------------------
        folder_label = QLabel("Folder:")
        # Enter anywhere in the folder field runs the scan rather than
        # activating whichever button holds focus — `action_button()` clears
        # autoDefault on every button it makes, which leaves that path clear.
        self.find_button = action_button(FIND_LABEL, PRIMARY_BUTTON_BG, uniform=True)
        self.find_button.clicked.connect(self._find_or_stop)

        # The padded button sets the height for every control in the row: a
        # stock QLineEdit is shorter, and mixing the two leaves the field
        # floating with a gap above and below it.
        row_height = self.find_button.sizeHint().height()

        self.folder_edit = QLineEdit(folder)
        self.folder_edit.setFixedHeight(row_height)
        self.folder_edit.returnPressed.connect(self.start_scan)
        # Square, at the shared row height: with only an ellipsis on it there
        # is no text width to size to. Fixed, so it takes no padding.
        self.browse_button = action_button("…", SECONDARY_BUTTON_BG, "0px")
        self.browse_button.setFixedSize(row_height, row_height)
        self.browse_button.setToolTip("Choose the folder to scan")
        self.browse_button.clicked.connect(self._browse)

        folder_row = QHBoxLayout()
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        folder_row.addWidget(self.find_button)
        layout.addLayout(folder_row)

        # --- results -----------------------------------------------------
        self.results = QTreeWidget()
        self.results.setColumnCount(len(HEADERS))
        self.results.setHeaderLabels(HEADERS)
        self.results.setFont(mono_font())
        self.results.setStyleSheet(results_tree_style())
        # Every row is one line of text, and saying so lets Qt lay out a tree
        # of tens of thousands of rows without measuring each one.
        self.results.setUniformRowHeights(True)
        # A path too long for the window loses its middle, not its end: the
        # file name and the top folder are what tell two copies apart.
        self.results.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # The path takes whatever width is left; size and time get a fixed
        # width measured off the widest thing each can hold. Not
        # ResizeToContents, which looks equivalent and is not: it re-measures
        # every row on every insert, and filling a tree of 24,000 groups that
        # way took minutes rather than a fraction of a second.
        header = self.results.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Stretch)
        metrics = self.results.fontMetrics()
        for column, widest in ((COL_SIZE, WIDEST_SIZE), (COL_MODIFIED, WIDEST_TIME)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(column, metrics.horizontalAdvance(widest) + COLUMN_PADDING)
        self.results.currentItemChanged.connect(self._on_selection_changed)
        apply_scrollbars(self.results)
        layout.addWidget(self.results, 1)

        # --- control bar -------------------------------------------------
        # Open wears the selection color: it acts on the row highlighted in
        # the tree, and sharing that color is what says so. The folder button
        # is the same gesture aimed one level up, as an icon, as in Sonar.
        self.open_button = action_button("Open", selection_button_bg(), CONTROL_BAR_PADDING)
        self.open_button.setToolTip(OPEN_TIP)
        self.open_button.clicked.connect(self._open_selected)
        self.folder_button = icon_button(
            QStyle.StandardPixmap.SP_DirIcon, SECONDARY_BUTTON_BG, CONTROL_BAR_PADDING
        )
        self.folder_button.setToolTip(FOLDER_TIP)
        self.folder_button.clicked.connect(self._open_selected_folder)
        # Red, the one destructive control in the app. It deletes only the
        # highlighted file, and only after a confirmation.
        self.delete_button = icon_button(
            QStyle.StandardPixmap.SP_TrashIcon, DANGER_BUTTON_BG, CONTROL_BAR_PADDING
        )
        self.delete_button.setToolTip(DELETE_TIP)
        self.delete_button.clicked.connect(self._delete_selected)
        self._set_file_buttons(False)

        control_bar = QHBoxLayout()
        control_bar.addWidget(self.open_button)
        control_bar.addWidget(self.folder_button)
        # Delete sits alone at the far right, away from Open and the folder
        # button, so a click meant for one of those cannot land on it.
        control_bar.addStretch(1)
        control_bar.addWidget(self.delete_button)
        layout.addLayout(control_bar)

        self._status = ScanStatusBar()
        self.setStatusBar(self._status)

        self.find_button.setFocus()

    # -- menus --------------------------------------------------------------

    def _build_menus(self) -> None:
        """File ▸ Exit, and Options ▸ Settings / User Guide — as in Sonar."""
        bar = self.menuBar()
        bar.setStyleSheet(menu_style())

        file_menu = bar.addMenu("&File")
        exit_action = QAction("E&xit", self)
        exit_action.setStatusTip(f"Close {APP_NAME}")
        # close(), not QApplication.quit(): closeEvent is what stops a scan
        # still running, and quit() skips it.
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        options = bar.addMenu("&Options")
        self.settings_action = QAction("&Settings", self)
        self.settings_action.setStatusTip("Which files to compare, and the Open command")
        # Nothing to refresh afterwards: the config is re-read at the start of
        # every scan, so a saved change applies from the next Find Dups.
        self.settings_action.triggered.connect(lambda: show_settings(self))
        options.addAction(self.settings_action)

        guide_action = QAction("&User Guide", self)
        guide_action.setStatusTip(f"Everything {APP_NAME} does")
        guide_action.triggered.connect(lambda: show_user_guide(self))
        options.addAction(guide_action)

    # -- reporting ----------------------------------------------------------

    def _report_problem(self, message: str) -> None:
        """Show something that actually went wrong, in a dialog."""
        QMessageBox.warning(self, APP_NAME, message)

    # -- actions -----------------------------------------------------------

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, f"{APP_NAME} — folder to scan", self._folder()
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _folder(self) -> str:
        """The folder row as an absolute path, with '~' expanded."""
        return os.path.abspath(os.path.expanduser(self.folder_edit.text().strip()))

    def _find_or_stop(self) -> None:
        if self.scanning:
            self.stop_scan()
        else:
            self.start_scan()

    @property
    def scanning(self) -> bool:
        return self._worker is not None

    def start_scan(self) -> None:
        """Check the settings and the folder, then start a scan on a thread.

        The config is read exactly once, here, and everything the scan needs
        from it is handed to the worker — a settings change saved mid-scan
        applies to the next one, not half-way through this one.
        """
        if self.scanning:
            return

        settings, _error = load_settings()
        problems = self._settings_problems(settings)
        if problems:
            self._report_problem(
                "The settings need fixing first:\n\n"
                + "\n\n".join(problems)
                + "\n\nChange them under Options ▸ Settings."
            )
            return

        folder = self._folder()
        if not os.path.isdir(folder):
            self._report_problem(f"Not a folder:\n\n{folder}")
            return

        self.results.clear()
        self._root = folder
        path_filter = PathFilter(settings.active_included, settings.active_excluded)
        # At least 1 byte: empty files are never compared, whatever the setting.
        min_size = max(parse_megabytes(settings.min_size_mb) or 0, 1)
        self._worker = ScanWorker(folder, path_filter, min_size, self)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._set_scanning(True)
        self._status.set_status(f"Scanning {folder}…", busy=True)
        self._worker.start()

    def stop_scan(self) -> None:
        """Ask the running scan to end; `_on_done` reports it when it has."""
        if self._worker is not None:
            self._worker.stop()
            self._stopping = True
            self.find_button.setEnabled(False)  # until the worker answers
            self._status.set_status("Stopping…", busy=True)

    @staticmethod
    def _settings_problems(settings: Settings) -> list[str]:
        """What in the config would make a scan wrong, one message each.

        The config file can be edited by hand, so the dialog's own check on
        Save is not enough. Only the lists a scan will apply are checked: a
        bad pattern in a list switched off cannot do any harm.
        """
        problems = pattern_problems(settings.active_included, settings.active_excluded)
        size_error = megabytes_problem(settings.min_size_mb)
        if size_error:
            problems.append(f"{MIN_SIZE_LABEL} {size_error}")
        return problems

    def _set_scanning(self, scanning: bool) -> None:
        """Swap the header between its idle and its scanning state."""
        self.find_button.setText(STOP_LABEL if scanning else FIND_LABEL)
        # Gray while it means Stop: the green is "start something", and a
        # button that ends a scan should not look like one that begins it.
        self.find_button.setStyleSheet(
            action_button_style(
                SECONDARY_BUTTON_BG if scanning else PRIMARY_BUTTON_BG,
                ACTION_BUTTON_PADDING,
            )
        )
        self.find_button.setEnabled(True)
        self.folder_edit.setEnabled(not scanning)
        self.browse_button.setEnabled(not scanning)
        self.settings_action.setEnabled(not scanning)

    # -- scan callbacks ----------------------------------------------------

    def _on_progress(self, progress: Progress) -> None:
        if self._worker is None or self._stopping:
            return
        if progress.phase == PHASE_SAMPLE:
            message = (
                f"Comparing {progress.total:,} same-size files… "
                f"{progress.done:,} checked"
            )
        elif progress.phase == PHASE_HASH:
            percent = progress.done * 100 // progress.total if progress.total else 100
            message = (
                f"Hashing… {percent}% ({format_size(progress.done)} of "
                f"{format_size(progress.total)})"
            )
        else:
            message = f"Scanning {self._root}… {progress.files:,} files"
        self._status.set_status(message, busy=True)

    def _on_done(self, result: ScanResult) -> None:
        self._finish_worker()
        if result.cancelled:
            self._status.set_status(
                f"Stopped — {plural(result.files_scanned, 'file')} scanned"
            )
            return

        self._show_groups(result)
        scanned = f"{plural(result.files_scanned, 'file')} scanned in {result.root}"
        if result.groups:
            message = (
                f"{plural(len(result.groups), 'group')} · "
                f"{plural(result.duplicate_files, 'file')} · "
                f"{format_size(result.reclaimable)} reclaimable — {scanned}"
            )
        else:
            message = f"No duplicates — {scanned}"
        if result.errors:
            message += f" · {len(result.errors):,} unreadable"
        self._status.set_status(message)

        if result.errors:
            shown = "\n".join(printable(e) for e in result.errors[:MAX_ERRORS_SHOWN])
            more = len(result.errors) - MAX_ERRORS_SHOWN
            if more > 0:
                shown += f"\n… and {more:,} more"
            self._report_problem(
                f"{len(result.errors):,} "
                f"{'file or folder' if len(result.errors) == 1 else 'files or folders'}"
                " could not be read, "
                f"and were left out:\n\n{shown}"
            )

    def _on_failed(self, trace: str) -> None:
        self._finish_worker()
        self._status.set_status("Scan failed")
        self._report_problem(f"The scan stopped with an internal error:\n\n{trace}")

    def _finish_worker(self) -> None:
        if self._worker is not None:
            self._worker.wait()
            self._worker.deleteLater()
            self._worker = None
        self._stopping = False
        self._set_scanning(False)

    # -- rows ---------------------------------------------------------------

    def _display_path(self, path: str) -> str:
        """`path` relative to the scanned folder, as the tree shows it."""
        try:
            relative = os.path.relpath(path, self._root)
        except ValueError:
            return path
        return path if relative.startswith(os.pardir) else relative

    def _show_groups(self, result: ScanResult) -> None:
        """Fill the tree: a row per group, already in largest-waste order.

        Every item is built first and handed over in one `addTopLevelItems`,
        then spanned and expanded: the tree lays itself out once instead of
        once per row, which is the difference between a fraction of a second
        and a long freeze for a home folder's worth of groups.
        """
        bold = QFont(self.results.font())
        bold.setBold(True)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        parents = []
        for group in result.groups:
            parent = QTreeWidgetItem([group_label(group.size, len(group.paths))])
            parent.setFont(COL_PATH, bold)
            parent.setData(COL_PATH, PATH_ROLE, None)
            parent.setData(COL_PATH, SIZE_ROLE, group.size)
            size = format_size(group.size)
            for path in group.paths:
                try:
                    mtime = time.localtime(os.stat(path).st_mtime)
                    modified = time.strftime(TIME_FORMAT, mtime)
                except OSError:
                    modified = "—"
                child = QTreeWidgetItem([printable(self._display_path(path)), size, modified])
                child.setData(COL_PATH, PATH_ROLE, path)
                child.setToolTip(COL_PATH, printable(path))
                child.setTextAlignment(COL_SIZE, right)
                parent.addChild(child)
            parents.append(parent)

        self.results.setUpdatesEnabled(False)
        try:
            self.results.addTopLevelItems(parents)
            # Only once they are in the tree: spanning is a property of the
            # view's row, and an item not yet in a view has none.
            for parent in parents:
                parent.setFirstColumnSpanned(True)
            self.results.expandAll()
        finally:
            self.results.setUpdatesEnabled(True)

    def _selected_path(self) -> str | None:
        item = self.results.currentItem()
        return item.data(COL_PATH, PATH_ROLE) if item is not None else None

    def _set_file_buttons(self, enabled: bool) -> None:
        self.open_button.setEnabled(enabled)
        self.folder_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _on_selection_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        """Open, folder and Delete act on a file row, and only on one."""
        self._set_file_buttons(
            current is not None and current.data(COL_PATH, PATH_ROLE) is not None
        )

    def _open_selected(self) -> None:
        path = self._selected_path()
        if path:
            error = open_file(path)
            if error:
                self._report_problem(error)

    def _open_selected_folder(self) -> None:
        path = self._selected_path()
        if path:
            error = open_folder(path)
            if error:
                self._report_problem(error)

    def _delete_selected(self) -> None:
        """Delete the highlighted file, once the user has said yes.

        Only that one file. Its row then leaves the tree, and a group left
        with a single file leaves with it — one file is not a duplicate. A
        group that still has copies gets its label recounted.
        """
        item = self.results.currentItem()
        path = item.data(COL_PATH, PATH_ROLE) if item is not None else None
        if item is None or not path:
            return
        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"Delete this file?\n\n{printable(path)}\n\n"
            "It is deleted permanently, not moved to the Trash.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        error = delete_file(path)
        if error:
            self._report_problem(printable(error))
            return
        self._remove_file_row(item)
        self._status.set_status(
            f"Deleted {printable(self._display_path(path))} · {self._remaining()}"
        )

    def _remove_file_row(self, item: QTreeWidgetItem) -> None:
        """Take a file row out of the tree, and its group if that leaves one."""
        # Nothing selected afterwards, rather than whichever row Qt picks: the
        # next Delete should be aimed at a file the user chose.
        self.results.clearSelection()
        self.results.setCurrentIndex(QModelIndex())
        parent = item.parent()
        if parent is None:
            return
        parent.removeChild(item)
        copies = parent.childCount()
        if copies < 2:
            self.results.takeTopLevelItem(self.results.indexOfTopLevelItem(parent))
        else:
            parent.setText(COL_PATH, group_label(parent.data(COL_PATH, SIZE_ROLE), copies))

    def _remaining(self) -> str:
        """What the tree still lists, for the status bar after a Delete."""
        count = self.results.topLevelItemCount()
        if not count:
            return "no duplicates left"
        files = reclaimable = 0
        for i in range(count):
            parent = self.results.topLevelItem(i)
            copies = parent.childCount()
            files += copies
            reclaimable += parent.data(COL_PATH, SIZE_ROLE) * (copies - 1)
        return (
            f"{plural(count, 'group')} · {plural(files, 'file')} · "
            f"{format_size(reclaimable)} reclaimable left"
        )

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:
        # Without this a scan still running when the window closes keeps a
        # thread hashing files with nothing left to report to — and Qt aborts
        # the process when a running QThread is destroyed.
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait()
        # And the spinner, which would otherwise go on repainting two labels
        # while the window is being torn down around them.
        self._status.stop()
        # And the help windows, which are modeless and so still on screen.
        close_markdown_windows()
        super().closeEvent(event)
