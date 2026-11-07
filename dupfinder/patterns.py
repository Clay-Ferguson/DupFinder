"""The config's glob patterns, and what the folder walk makes of them.

The settings keep two lists, spelled exactly the way Sonar spells them so the
two apps' configs read the same: files to consider (`included`) and files and
folders to skip (`excluded`), the latter written in `find -path` style. Sonar
hands its lists to ugrep and find; DupFinder walks the tree itself, in
`scanner`, and asks a `PathFilter` about every entry it meets.

    */node_modules/*   a folder named node_modules, at any depth — never entered
    */photos/raw/*     a folder whose path ends in photos/raw — never entered
    */docs/*.tmp       any path matching it, folders and files alike
    *.log              any file or folder whose NAME matches, at any depth

Matching is `fnmatchcase`, so it is case-sensitive and a `*` crosses `/`
inside a path pattern, exactly as find's `-path` does.

Pure string work — no disk, no Qt, nothing from the rest of the package — so
the config, the dialog and the scanner can all use it without depending on
each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatchcase

# -- the walk's filter -------------------------------------------------------


class PathFilter:
    """Decides, entry by entry, what the folder walk skips.

    The patterns are sorted once, here, into the four kinds the module
    docstring lists, so the walk does not re-read every pattern's shape for
    every one of the possibly millions of entries it meets.

    An empty filter skips nothing; `PathFilter()` is what a scan with both
    lists switched off uses.
    """

    def __init__(self, included: Sequence[str] = (), excluded: Sequence[str] = ()) -> None:
        # Names a whole folder is pruned by: `*/node_modules/*` -> `node_modules`.
        self._dir_names: list[str] = []
        # Paths a whole folder is pruned by: `*/a/b/*` -> `*/a/b`, matched
        # against the folder's own path (which never ends in a slash).
        self._dir_paths: list[str] = []
        # Anything else with a '/', matched against the full path of every
        # entry, folders and files alike.
        self._paths: list[str] = []
        # No '/': matched against the name of every entry.
        self._names: list[str] = []
        for pattern in excluded:
            if pattern.startswith("*/") and pattern.endswith("/*") and len(pattern) > 4:
                middle = pattern[2:-2]
                if "/" in middle:
                    self._dir_paths.append(pattern[:-2])
                else:
                    self._dir_names.append(middle)
            elif "/" in pattern:
                self._paths.append(pattern)
            else:
                self._names.append(pattern)
        # A whitelist of file names. Folders are never tested against it: it
        # says which *files* are worth comparing, and applied to folders it
        # would hide every one of them along with everything inside.
        self._included = list(included)

    def skip_dir(self, name: str, path: str) -> bool:
        """Whether the walk should not enter the folder `name` at `path`."""
        return (
            any(fnmatchcase(name, p) for p in self._dir_names)
            or any(fnmatchcase(path, p) for p in self._dir_paths)
            or any(fnmatchcase(path, p) for p in self._paths)
            or any(fnmatchcase(name, p) for p in self._names)
        )

    def skip_file(self, name: str, path: str) -> bool:
        """Whether the file `name` at `path` is left out of the comparison."""
        if self._included and not any(fnmatchcase(name, p) for p in self._included):
            return True
        return any(fnmatchcase(path, p) for p in self._paths) or any(
            fnmatchcase(name, p) for p in self._names
        )


# -- checking ---------------------------------------------------------------


def pattern_problems(included: Sequence[str], excluded: Sequence[str]) -> list[str]:
    """One message per pattern that cannot do what it says; `[]` if none.

    The same two rules as Sonar, for the same underlying reason — every path
    the walk sees is absolute, so a pattern is either about a name or has to
    reach the absolute path from its start:

      included  Any '/' at all. Include patterns are matched against a file's
                name only, so `docs/*.md` would match nothing, ever, and quietly
                empty every scan. `*.md` already means "at any depth".
      excluded  A '/' without a leading `*/`. `docs/*.tmp` can never match an
                absolute path, so it would skip nothing.

    Checked by the settings dialog before it saves and by the window before it
    scans, since the file can be edited by hand.
    """
    problems = [
        f"Include pattern \"{p}\" contains '/'. Include patterns match a "
        "file's name at any depth, so use just the name part, e.g. \"*.jpg\"."
        for p in included
        if "/" in p
    ]
    problems += [
        f"Skip pattern \"{p}\" contains '/' but does not start with \"*/\". "
        "It would skip nothing; write it as \"*/" + p.lstrip("/") + "\"."
        for p in excluded
        if "/" in p and not p.startswith("*/")
    ]
    return problems


# -- the settings dialog's text areas --------------------------------------


def parse_pattern_lines(text: str) -> list[str]:
    """A text area's contents as a pattern list: one pattern per line.

    Blank lines are dropped and surrounding whitespace is stripped, so the
    trailing newline every text area ends up with does not become an empty
    pattern.
    """
    return [stripped for stripped in (line.strip() for line in text.splitlines()) if stripped]


def pattern_lines(patterns: Sequence[str]) -> str:
    """The inverse: a pattern list as text for a text area."""
    return "\n".join(patterns)
