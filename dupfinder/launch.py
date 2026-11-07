"""Handing a file to another program — the Open command, or the file manager —
and the one thing DupFinder does to a file itself: `delete_file`.

`open_file` is the Open button. Which program it runs is a config key
(`open.command`, `xdg-open` by default), read at the moment of the click, so
changing it in the settings dialog takes effect on the next Open rather than
the next run.

`open_folder` is the same handoff aimed one level up — the folder the file
sits in, given to the desktop's file manager through `xdg-open`.

Everything here returns an error message rather than raising, because it runs
in a button handler, and every spawn is an argv list — never a shell, since
the command comes from a text field. Taken from Sonar's `launch.py`, minus
everything to do with archives and PDFs.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

from .config import open_command

# Where the selected file goes in a configured command, if the user says.
# Without it the path is appended, which is what almost every program wants;
# with it, the path can sit in the middle — `gnome-terminal -- vim %s`.
PATH_PLACEHOLDER = "%s"

# What a folder is handed to. `xdg-open` is the freedesktop way to ask "open
# this with whatever is registered for it", and what is registered for a
# directory is the desktop's file manager. Deliberately not a config key: the
# point of it is that the *system* decides.
SYSTEM_OPEN_COMMAND = "xdg-open"


def _child_env() -> dict[str, str]:
    """Our environment, minus DupFinder's own virtualenv.

    start.sh runs the app through `uv run`, which puts .venv/bin on PATH and
    sets VIRTUAL_ENV. Left in place those are inherited by whatever Open
    starts, so an editor would offer DupFinder's interpreter as the Python
    environment for the project it opens. The program should see the
    environment a terminal would give it, not ours.
    """
    env = os.environ.copy()
    venv = env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    if venv:
        bin_dir = os.path.normpath(os.path.join(venv, "bin"))
        kept = [
            p
            for p in env.get("PATH", "").split(os.pathsep)
            if p and os.path.normpath(p) != bin_dir
        ]
        env["PATH"] = os.pathsep.join(kept)
    return env


def build_open_argv(command: str, path: str) -> list[str]:
    """`command` as an argv list with `path` in it.

    Split the way a shell would split it — quotes and escapes honored — but
    nothing is handed to a shell, so a program whose path has a space in it
    works while a pipe or a redirection in the command does not.

    The path is substituted for `%s` wherever it appears, in whole tokens or
    inside one (`--file=%s`), and appended as the last argument when it does
    not appear at all.

    Raises ValueError on a command shlex cannot split, e.g. one with an
    unbalanced quote; the caller turns that into a message.
    """
    parts = shlex.split(command)
    if not parts:
        raise ValueError("the command is empty")
    if any(PATH_PLACEHOLDER in part for part in parts):
        return [part.replace(PATH_PLACEHOLDER, path) for part in parts]
    return parts + [path]


def _start_detached(argv: list[str], subject: str, hint: str) -> str | None:
    """Run `argv`, detached from DupFinder. An error message, or None.

    The program is checked on PATH first, so a missing one is reported as the
    missing program it is instead of a bare OSError from the spawn.

    Spawned with `start_new_session=True` and its streams discarded, so the
    program is not a child that dies with DupFinder and cannot stall the GUI
    by filling a pipe nobody reads.
    """
    program = argv[0]
    if not os.path.isabs(program):
        resolved = shutil.which(program)
        if resolved is None:
            return f"Cannot open {subject}: '{program}' is not on PATH.{hint}"
        argv[0] = resolved
    elif not os.path.exists(program):
        return f"Cannot open {subject}: {program} is not installed.{hint}"

    try:
        subprocess.Popen(
            argv,
            env=_child_env(),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return f"Could not open {subject}:\n{exc}"
    return None


def open_file(path: str) -> str | None:
    """Open `path` with the configured command. An error message, or None."""
    if not os.path.isfile(path):
        return f"Cannot open — the file no longer exists:\n{path}"
    command = open_command()
    hint = "\n\nChange the Open command under Options ▸ Settings."
    try:
        argv = build_open_argv(command, path)
    except ValueError as exc:
        return (
            f"The Open command cannot be run as written:\n\n    {command}\n\n"
            f"{exc}{hint}"
        )
    return _start_detached(argv, f"'{os.path.basename(path)}'", hint)


def open_folder(path: str) -> str | None:
    """Show the folder holding `path` in the file manager. An error, or None."""
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        return f"Cannot open — the folder no longer exists:\n{folder}"
    hint = (
        f"\n\nFolders are opened with the system's file manager, "
        f"through '{SYSTEM_OPEN_COMMAND}'."
    )
    return _start_detached([SYSTEM_OPEN_COMMAND, folder], f"'{folder}'", hint)


def delete_file(path: str) -> str | None:
    """Delete `path` for good. An error message, or None.

    The Delete button, after the window has asked. Permanent — `os.remove`,
    not the desktop's Trash — and only ever the one path: never a folder,
    since a scan lists nothing else, and a path that is now a folder fails
    here rather than being emptied. A symlink put where the file was is
    removed itself, never what it points to.

    A file that is already gone counts as deleted: what was asked for is
    true, and the window should take its row away just the same.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        return f"Could not delete the file:\n{path}\n\n{exc.strerror or exc}"
    return None
