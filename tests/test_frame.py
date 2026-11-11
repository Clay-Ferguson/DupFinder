"""Every window DupFinder opens wears windowchrome's frame.

The frame itself is windowchrome's and is tested there; these only check that
each of the app's windows was handed to `apply_frame()`, which is the one
thing a new dialog could forget.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox, QWidget
from windowchrome import WindowFrame
from windowchrome.markdowndialog import _WINDOWS, close_markdown_windows

from dupfinder import messages
from dupfinder.help import show_user_guide
from dupfinder.settings import SettingsDialog
from dupfinder.window import MainWindow


def framed(window: QWidget) -> bool:
    return (
        window.findChild(WindowFrame) is not None
        and bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
    )


def test_the_main_window_is_framed(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    assert framed(window)


def test_the_main_window_gets_its_room_below_the_title_bar(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    title_bar = window.findChild(WindowFrame).title_bar
    assert window.height() == 700 + title_bar.height()


def test_the_settings_dialog_is_framed(qtbot, conf):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    assert framed(dialog)


def test_the_user_guide_is_framed(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    try:
        show_user_guide(window)
        show_user_guide(window)  # raising the open guide must not break it
        (guide,) = _WINDOWS.values()
        assert framed(guide)
        assert len(guide.findChildren(WindowFrame)) == 1
    finally:
        close_markdown_windows()


def test_a_message_box_is_framed_and_answers(monkeypatch):
    """`_show` is what the `dialogs` fixture leaves alone: run it with exec()
    stubbed, since a real one blocks offscreen."""
    boxes = []

    def run(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "exec", run)
    answer = messages._show(
        QMessageBox.Icon.Question,
        None,
        "DupFinder",
        "Delete?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    assert answer == QMessageBox.StandardButton.Yes
    (box,) = boxes
    assert framed(box)
    assert box.defaultButton() is box.button(QMessageBox.StandardButton.No)
