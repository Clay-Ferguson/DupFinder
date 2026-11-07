"""Shared fixtures: a private config, dialog capture, spawn capture, a tree.

Every tree is built in pytest's `tmp_path` rather than checked in: the cases
worth testing — hard links, symlinks, a FIFO, unreadable files — cannot
survive a git checkout, and the rest are only interesting for the bytes they
hold.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from dupfinder import config, launch  # noqa: E402
from dupfinder.window import MainWindow  # noqa: E402

# The open command a test config uses: harmless if it were ever really run.
TEST_OPEN_COMMAND = "/bin/true"


def write(path, data: bytes) -> str:
    """Write `data` to `path`, creating folders on the way. Returns the path."""
    path = str(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def block(seed: int, size: int) -> bytes:
    """`size` bytes that differ from every other seed's, and are not random —
    so a failing test fails the same way every run."""
    pattern = bytes((seed * 31 + i * 7) % 251 for i in range(251))
    return (pattern * (size // len(pattern) + 1))[:size]


@pytest.fixture
def conf(tmp_path_factory):
    """A config file of this test's own.

    `config.CONFIG_PATH` is read at call time rather than cached, so rebinding
    the module attribute keeps every test off the real ~/.config. Returns a
    function so a test can save different settings mid-run.
    """
    original = config.CONFIG_PATH
    # Outside `tmp_path`, which tests scan: the config would be one more file.
    config.CONFIG_PATH = str(tmp_path_factory.mktemp("config") / "dupfinder-config.yaml")

    def save(
        included=(),
        excluded=(),
        use_included=True,
        use_excluded=True,
        min_size_mb="0",
        open_command=TEST_OPEN_COMMAND,
    ):
        error = config.save_settings(
            config.Settings(
                included=tuple(included),
                excluded=tuple(excluded),
                use_included=use_included,
                use_excluded=use_excluded,
                min_size_mb=min_size_mb,
                open_command=open_command,
            )
        )
        assert error is None
        return config.CONFIG_PATH

    save()
    yield save
    config.CONFIG_PATH = original


class _Dialogs(list):
    """The (title, message) of every dialog shown, and the answer to give a
    question."""

    answer = QMessageBox.StandardButton.No


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    """Catch every QMessageBox instead of showing it, and report what was said.

    Autouse and not optional: under QT_QPA_PLATFORM=offscreen a QMessageBox
    still blocks waiting for a click that can never come, so one raised by a
    path under test would hang the whole run rather than fail it.

    A `question` is answered with `shown.answer`, No unless a test sets it to
    Yes — so a test that forgets to answer never deletes anything.
    """
    shown = _Dialogs()

    def capture(_parent, title, message, *args, **kwargs):
        shown.append((title, message))
        return QMessageBox.StandardButton.Ok

    def ask(_parent, title, message, *args, **kwargs):
        shown.append((title, message))
        return shown.answer

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(capture))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(capture))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(capture))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(ask))
    return shown


@pytest.fixture
def spawned(monkeypatch):
    """Record every argv `launch` would start, instead of starting it."""
    calls = []

    def spy(argv, **kwargs):
        calls.append(list(argv))
        return None

    monkeypatch.setattr(launch.subprocess, "Popen", spy)
    # xdg-open may not be installed where the tests run; resolve it anyway.
    real_which = launch.shutil.which
    monkeypatch.setattr(
        launch.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name == "xdg-open" else real_which(name),
    )
    return calls


@pytest.fixture
def dup_tree(tmp_path):
    """A small tree with a known answer.

        photos/a.jpg, backup/a-copy.jpg, deep/x/y/a.jpg   one 300 KB group
        docs/r.txt, docs/r (1).txt                         one 2 KB group
        other/unique.bin                                   same size as r.txt, different
        node_modules/r.txt                                 a copy, but skipped by default
        empty1, empty2                                     never a group
    """
    root = tmp_path / "tree"
    big = block(1, 300 * 1024)
    small = block(2, 2048)
    write(root / "photos" / "a.jpg", big)
    write(root / "backup" / "a-copy.jpg", big)
    write(root / "deep" / "x" / "y" / "a.jpg", big)
    write(root / "docs" / "r.txt", small)
    write(root / "docs" / "r (1).txt", small)
    write(root / "other" / "unique.bin", block(3, 2048))
    write(root / "node_modules" / "r.txt", small)
    write(root / "empty1", b"")
    write(root / "empty2", b"")
    return str(root)


@pytest.fixture
def scan(qtbot, conf):
    """Open a window on `folder`, run Find Dups, and wait for it to finish."""

    def run(folder):
        window = MainWindow(folder)
        qtbot.addWidget(window)
        window.start_scan()
        # Waits for the window's own handling of `done`, not just the signal:
        # `scanning` goes false only once the results are on screen.
        qtbot.waitUntil(lambda: not window.scanning, timeout=30000)
        return window

    return run


needs_permissions = pytest.mark.skipif(
    os.geteuid() == 0, reason="root reads an unreadable file anyway"
)

needs_fifo = pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs here")
