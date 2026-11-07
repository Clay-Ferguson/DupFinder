"""Handing files to other programs, and the package's layering."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from dupfinder.launch import build_open_argv, open_file, open_folder

from conftest import TEST_OPEN_COMMAND, write


@pytest.mark.parametrize(
    "command,argv",
    [
        ("xdg-open", ["xdg-open", "/p/a b.jpg"]),
        ("'/opt/my app/run' --flag", ["/opt/my app/run", "--flag", "/p/a b.jpg"]),
        ("gnome-terminal -- vim %s", ["gnome-terminal", "--", "vim", "/p/a b.jpg"]),
        ("tool --file=%s -q", ["tool", "--file=/p/a b.jpg", "-q"]),
    ],
)
def test_build_open_argv(command, argv):
    assert build_open_argv(command, "/p/a b.jpg") == argv


@pytest.mark.parametrize("command", ["", "   ", "vim 'unbalanced"])
def test_a_command_that_cannot_be_split_is_refused(command):
    with pytest.raises(ValueError):
        build_open_argv(command, "/p/a")


def test_open_runs_the_configured_command(conf, spawned, tmp_path):
    path = write(tmp_path / "a.jpg", b"x")
    assert open_file(path) is None
    assert spawned == [[TEST_OPEN_COMMAND, path]]


def test_open_reads_the_command_at_the_click(conf, spawned, tmp_path):
    path = write(tmp_path / "a.jpg", b"x")
    conf(open_command="xdg-open %s")
    assert open_file(path) is None
    assert spawned == [["/usr/bin/xdg-open", path]]


def test_open_on_a_vanished_file_says_so(conf, spawned, tmp_path):
    error = open_file(str(tmp_path / "gone.jpg"))
    assert error and "no longer exists" in error
    assert spawned == []


def test_a_program_not_on_path_is_named(conf, spawned, tmp_path):
    conf(open_command="no-such-program-here")
    error = open_file(write(tmp_path / "a", b"x"))
    assert error and "no-such-program-here" in error and "Settings" in error
    assert spawned == []


def test_the_folder_button_opens_the_containing_folder(spawned, tmp_path):
    path = write(tmp_path / "sub" / "a.jpg", b"x")
    assert open_folder(path) is None
    assert spawned == [["/usr/bin/xdg-open", str(tmp_path / "sub")]]


def test_the_non_widget_modules_never_import_qt():
    """Everything below the widgets is plain Python, which is what lets the
    .deb smoke test import it without Qt — and the scanner be tested without
    an application. A Qt import creeping into one of these fails here first."""
    modules = "config patterns sizes scanner launch".split()
    code = (
        "import sys\n"
        + "".join(f"import dupfinder.{name}\n" for name in modules)
        + "print(sorted(m for m in sys.modules if m.startswith('PyQt6')))"
    )
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"
