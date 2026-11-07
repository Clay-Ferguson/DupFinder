"""The settings dialog: what a scan looks at, and the Open button's command.

Sonar's dialog, trimmed to what DupFinder has: the two pattern lists (one
pattern per line in each of two text areas, each with a checkbox that sets it
aside without losing it), the smallest file worth comparing, and the Open
command.

The layout is a stack of labelled sections in a QVBoxLayout, sized to its
contents: the next setting is one more `_add_checked_patterns` or `_add_line`
call and the dialog grows to fit it, with no geometry to revisit.

Saving writes the file and nothing else. Both readers go back to the config
at the moment they need it — `start_scan` calls `load_settings` per scan,
`open_file` calls `open_command` per click — so a saved change applies next
time without a restart and without anything to notify.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from windowchrome import apply_checkboxes, apply_scrollbars

from . import APP_NAME
from .config import CONFIG_PATH, Settings, load_settings, save_settings
from .patterns import parse_pattern_lines, pattern_lines, pattern_problems
from .sizes import megabytes_problem
from .style import (
    PRIMARY_BUTTON_BG,
    SECONDARY_BUTTON_BG,
    action_button,
    action_button_size,
    mono_font,
)

# How many lines of patterns each text area shows before it has to scroll.
VISIBLE_LINES = 7

# Vertical gaps: between one labelled section and the next, and between a
# label and the field it belongs to. The second is smaller on purpose — it is
# what makes the pair read as one thing.
SECTION_SPACING = 14
LABEL_SPACING = 4

# Wide enough for a long exclusion path without wrapping it — these are read
# as whole patterns, and a pattern broken across two lines is hard to check.
MIN_WIDTH = 600

# The minimum-size field holds a handful of characters ("0.5"), so it is sized
# for about this many rather than stretched across the dialog, where it would
# read as holding something as long as a command line.
SHORT_FIELD_CHARS = 12

# The minimum-size field's caption, which names its unit: the field holds a
# bare number, and without one "1" could as well be bytes as gigabytes. Also
# the prefix of any message about the value, here and in the main window.
MIN_SIZE_LABEL = "Ignore files smaller than (MB):"


class PatternEdit(QPlainTextEdit):
    """A text area exactly `VISIBLE_LINES` tall, one pattern per line.

    The height is pinned rather than left to the layout: a field a few pixels
    taller than a whole number of lines shows the top of the next one — a
    sliver of clipped text along the bottom edge that reads as a rendering
    fault. Seven whole lines, always; the dialog's own surplus collects above
    the buttons instead.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(mono_font())
        # Patterns are single tokens: wrapping one across two lines would make
        # the "one per line" rule the whole field is built on unreadable.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(True)  # Tab moves on rather than inserting one
        apply_scrollbars(self)
        self.setFixedHeight(self._height_for_lines())

    def _height_for_lines(self) -> int:
        """The pixel height that shows `VISIBLE_LINES` lines and no more.

        A QPlainTextEdit lays each block out at exactly `lineSpacing()`, so the
        text itself is that times the line count, and the chrome around it is
        the frame plus the document's own margin — counted once, since it is
        only leading space and the document keeps running underneath the
        bottom one.
        """
        metrics = QFontMetrics(self.font())
        margin = int(self.document().documentMargin())
        return metrics.lineSpacing() * VISIBLE_LINES + margin + 2 * self.frameWidth()


class SettingsDialog(QDialog):
    """Edit the scan patterns, the minimum file size and the Open command."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumWidth(MIN_WIDTH)

        settings, error = load_settings()

        self._layout = QVBoxLayout(self)
        # The layout's own spacing is the tight one, since it is what falls
        # between a label and the field it names; the wider gap between
        # sections is added explicitly, in `_begin_section`.
        self._layout.setSpacing(LABEL_SPACING)

        if error:
            # Shown before anything else, because Save from here rewrites the
            # file: someone with a typo in their YAML is looking at fields that
            # do not reflect what is on disk, and needs to know that saving
            # replaces it rather than edits it. Escaped, because the label is
            # rich text and a YAML parser error is full of angle brackets.
            warning = QLabel(
                f"<b>{escape(CONFIG_PATH)} could not be read</b><br>"
                f"{escape(error)}<br>"
                "The fields below start empty; saving replaces the file."
            )
            warning.setWordWrap(True)
            self._layout.addWidget(warning)

        self.included_check, self.included_edit = self._add_checked_patterns(
            "Compare only these files (empty = every file):",
            settings.included,
            settings.use_included,
            tooltip=(
                "Uncheck to compare every file, as if this list were empty,\n"
                "without losing the patterns — check it again to bring them back.\n"
                "Patterns match a file's name, e.g. *.jpg"
            ),
        )
        self.excluded_check, self.excluded_edit = self._add_checked_patterns(
            "Skip these files and folders:",
            settings.excluded,
            settings.use_excluded,
            tooltip=(
                "Uncheck to skip nothing — node_modules, .git and the rest are\n"
                "scanned too, which can make a scan much slower and fill the\n"
                "list with copies nobody meant to clean up — without losing the\n"
                "patterns. Check it again to bring them back."
            ),
        )
        self.min_size_edit = self._add_line(
            MIN_SIZE_LABEL,
            settings.min_size_mb,
            tooltip=(
                "A number of megabytes (1 MB = 1024 × 1024 bytes); fractions\n"
                "are allowed — for example 0, 0.5, 10.\n"
                "0 compares every file. Empty files are always ignored."
            ),
            short=True,
        )
        self.open_edit = self._add_line(
            "Command the Open button runs (the file is added as the last argument):",
            settings.open_command,
            tooltip=(
                "Split the way a shell would split it, but run without a shell,"
                " so pipes and redirection do not work.\n"
                "Put %s anywhere in the command to place the file there instead"
                " of at the end — e.g. gnome-terminal -- vim %s"
            ),
        )

        # New settings go here — one more `_add_checked_patterns` / `_add_line`
        # (or any widget) added before the button row, which stays pinned to
        # the bottom.

        # Every field above is a fixed height, so a dialog dragged taller has
        # surplus to put somewhere: it goes here, between the last setting and
        # the buttons, rather than into a field that would show a clipped row.
        self._layout.addStretch(1)
        self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        self._layout.addLayout(self._button_row())

    # -- construction ------------------------------------------------------

    def _begin_section(self, label: str, tooltip: str = "") -> None:
        """Open a new labelled section: the gap above it, then its caption."""
        if self._layout.count():
            self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        caption = QLabel(label)
        # A long caption wraps rather than widening the dialog past MIN_WIDTH.
        caption.setWordWrap(True)
        # The label carries the field's tooltip too: it is the larger target.
        caption.setToolTip(tooltip)
        self._layout.addWidget(caption)

    def _add_checked_patterns(
        self, label: str, patterns: Sequence[str], checked: bool, tooltip: str = ""
    ) -> tuple[QCheckBox, PatternEdit]:
        """A pattern field whose caption is a checkbox that switches it off.

        Unchecked, the field is dimmed rather than cleared: its patterns are
        still saved, only not applied, so a list set aside for one scan is
        there again when the box is ticked. Dim rather than hidden so the
        dialog does not change height under the pointer.
        """
        if self._layout.count():
            self._layout.addSpacing(SECTION_SPACING - LABEL_SPACING)
        check = QCheckBox(label)
        check.setChecked(checked)
        check.setToolTip(tooltip)
        apply_checkboxes(check)
        self._layout.addWidget(check)

        edit = PatternEdit()
        edit.setPlainText(pattern_lines(patterns))
        edit.setEnabled(checked)
        check.toggled.connect(edit.setEnabled)
        self._layout.addWidget(edit)
        return check, edit

    def _add_line(
        self, label: str, value: str, tooltip: str = "", short: bool = False
    ) -> QLineEdit:
        """A labelled single-line field, appended to the stack.

        Height matched to the buttons — and so to the main window's folder
        row, which is measured the same way. `short` sizes it for a few
        characters and pushes it left, for a value like "10M".
        """
        self._begin_section(label, tooltip)
        edit = QLineEdit(value)
        edit.setFont(mono_font())
        edit.setToolTip(tooltip)
        edit.setFixedHeight(action_button_size().height())
        if short:
            width = edit.fontMetrics().horizontalAdvance("M" * SHORT_FIELD_CHARS)
            edit.setFixedWidth(width)
            row = QHBoxLayout()
            row.addWidget(edit)
            row.addStretch(1)
            self._layout.addLayout(row)
        else:
            self._layout.addWidget(edit)
        return edit

    def _button_row(self) -> QHBoxLayout:
        """Save and Cancel, right-aligned, sized like the Find Dups button."""
        save = action_button("Save", PRIMARY_BUTTON_BG, uniform=True)
        save.setDefault(True)  # Enter in the dialog saves
        save.clicked.connect(self._save)

        cancel = action_button("Cancel", SECONDARY_BUTTON_BG, uniform=True)
        cancel.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        return row

    # -- actions -----------------------------------------------------------

    def _save(self) -> None:
        """Write every field back, and close only if that worked."""
        included = parse_pattern_lines(self.included_edit.toPlainText())
        excluded = parse_pattern_lines(self.excluded_edit.toPlainText())
        min_size_mb = self.min_size_edit.text().strip() or "0"
        # Checked whether or not a list's box is ticked: its patterns are
        # saved either way, and would stop every scan the moment it was.
        problems = pattern_problems(included, excluded)
        size_error = megabytes_problem(min_size_mb)
        if size_error:
            problems.append(f"{MIN_SIZE_LABEL} {size_error}")
        if problems:
            QMessageBox.warning(self, f"{APP_NAME} — Settings", "\n\n".join(problems))
            return
        error = save_settings(
            Settings(
                included=tuple(included),
                excluded=tuple(excluded),
                use_included=self.included_check.isChecked(),
                use_excluded=self.excluded_check.isChecked(),
                min_size_mb=min_size_mb,
                open_command=self.open_edit.text().strip(),
            )
        )
        if error:
            # Left open rather than closed on failure: the edits are still in
            # the fields, so the user can fix the cause and press Save again.
            QMessageBox.warning(self, f"{APP_NAME} — Settings", error)
            return
        self.accept()


def show_settings(parent: QWidget | None = None) -> bool:
    """Open the settings dialog modally. True if it was saved."""
    return SettingsDialog(parent).exec() == QDialog.DialogCode.Accepted
