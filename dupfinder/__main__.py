"""Entry point: python -m dupfinder [FOLDER]"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

from PyQt6.QtWidgets import QApplication

from . import APP_NAME, UI_POINT_SIZE, messages
from .config import ensure_config
from .style import tune_palette
from .window import MainWindow


def resolve_folder(argument: str | None) -> tuple[str, str | None]:
    """The folder to scan, plus a warning to show about it (or None).

    With no argument, the current working directory — which is what a desktop
    launcher gives us, and a sensible place for the folder row to start.

    A path that turns out to be a *file* resolves to its parent directory,
    so a file manager action that passes the selection still lands somewhere
    sensible.
    """
    if argument is None:
        return os.getcwd(), None

    folder = os.path.abspath(os.path.expanduser(argument))
    if os.path.isdir(folder):
        return folder, None
    if os.path.isfile(folder):
        return os.path.dirname(folder), None
    return (
        os.getcwd(),
        f"No such folder:\n\n{folder}\n\nStarting in {os.getcwd()} instead.",
    )


# How much of a traceback the internal-error dialog shows.
TRACEBACK_LINES = 12


def _report_unhandled(kind, value, trace) -> None:
    """Show an exception that escaped a slot, instead of dying of it.

    PyQt6 aborts the whole process when a Python exception leaves a slot and
    no `sys.excepthook` has been installed — a bug in one button handler would
    take every result on screen down with it, with nothing but a core dump to show
    for it when DupFinder was started from a desktop icon. With a hook installed
    PyQt calls it instead and carries on, so the bug is reported and the
    window survives.
    """
    text = "".join(traceback.format_exception(kind, value, trace))
    if sys.__stderr__ is not None:
        sys.__stderr__.write(text)
    if QApplication.instance() is None:
        return
    # The tail of the traceback, where the failing line is: a desktop launch
    # has no terminal for the stderr copy above to reach. Through `messages`,
    # like every box, so it is framed and the test suite's `dialogs` fixture
    # can catch it — an exec()'d box blocks offscreen.
    tail = "\n".join(text.rstrip().splitlines()[-TRACEBACK_LINES:])
    messages.critical(
        None,
        f"{APP_NAME} — internal error",
        f"Something went wrong inside {APP_NAME}. The window should still "
        f"work.\n\n{tail}",
    )


def main() -> int:
    # nargs="?" rather than a required argument: argparse reports a missing
    # one on stderr and exits before a QApplication exists, which is invisible
    # when DupFinder is started from a desktop icon rather than a terminal.
    # Everything that can go wrong is reported in a dialog below instead.
    parser = argparse.ArgumentParser(prog="dupfinder", description=__doc__)
    parser.add_argument(
        "folder",
        nargs="?",
        default=None,
        metavar="FOLDER",
        help="folder to scan; defaults to the current directory",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    sys.excepthook = _report_unhandled
    app.setApplicationName(APP_NAME)
    # applicationDisplayName is deliberately NOT set. Every platform backend
    # runs its window titles through QPlatformWindow::formatWindowTitle(),
    # which appends the display name to whatever setWindowTitle() was given —
    # so with it set, a dialog titled "DupFinder — Settings" would reach the
    # title bar as "DupFinder — Settings — DupFinder". Each window spells out
    # its own full title instead.
    # Ties the window to dupfinder.desktop, so the desktop shows our icon and
    # name in the dock and alt-tab. Without it the Wayland app_id is derived
    # from argv[0] ("python3") and matches no desktop entry at all.
    app.setDesktopFileName("dupfinder")

    # Set on the application rather than per widget, so the folder row scales
    # along with the results. The tree then overrides the family (not the
    # size) with a fixed-width one — see style.mono_font.
    font = app.font()
    font.setPointSize(UI_POINT_SIZE)
    app.setFont(font)

    tune_palette(app)

    ensure_config()

    folder, warning = resolve_folder(args.folder)
    window = MainWindow(folder)
    window.show()
    window.activateWindow()
    window.raise_()

    # After show(), so the warning appears over the window it is talking about
    # rather than on its own against the desktop.
    if warning:
        messages.warning(window, f"{APP_NAME} — folder not found", warning)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
