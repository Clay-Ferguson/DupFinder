"""The help window, and where its content lives.

There is no help *text* here. The user guide is a markdown file under
`docs/`, rendered by `windowchrome.show_markdown()` — so changing what the
help says means editing markdown, not Python, and the same file serves as the
repository's documentation and as the app's.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QWidget
from windowchrome import MarkdownDialog, apply_frame, apply_scrollbars, show_markdown

from . import APP_NAME
from .style import SCROLLBAR_HANDLE, action_button

# `docs/` sits beside the package, not inside it. That is safe rather than
# lucky: `pyproject.toml` sets `package = false` and `start.sh` runs the app
# out of the tree, so there is no wheel this could be missing from. The one
# thing that *does* have to keep up is `packaging/build-deb.sh`, which installs
# the whole `docs/` tree into /usr/lib/dupfinder beside the package for this
# reason, and checks before packing that every link in it resolves.
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _open(name: str, title: str, parent: QWidget | None) -> MarkdownDialog:
    """Show one of the documents, styled like the rest of the app."""
    dialog = show_markdown(
        DOCS_DIR / name,
        parent,
        title=f"{APP_NAME} — {title}",
        # Every button in this app comes from `action_button`, and this is the
        # one place that factory is handed *out* — the dialog lives in
        # windowchrome, and a plain QPushButton would wear the desktop theme.
        button_factory=lambda text: action_button(text, uniform=True),
    )
    # show_markdown() has already shown it, so this re-shows it framed; for
    # a guide that was already open it hands back the frame it has.
    apply_frame(dialog)
    # The wider scroll bars the rest of the app uses.
    apply_scrollbars(dialog.view, handle=SCROLLBAR_HANDLE)
    return dialog


def show_user_guide(parent: QWidget | None = None) -> None:
    """The whole user guide, the same one that ships in `docs/`."""
    _open("USER_GUIDE.md", "User Guide", parent)
