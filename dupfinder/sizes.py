"""Byte counts as people write them, and as the window shows them.

`parse_megabytes` reads the settings' "Ignore files smaller than (MB)" field
— `0`, `1`, `0.5`, `10` — and `format_size` is what every size in the window
and the status bar goes through on the way out. Both use binary multiples
(1 MB = 1024 × 1024 bytes), which is what file managers and `du -h` mean by
them, and so a minimum typed here matches the sizes the results list shows.

Pure: no disk, no Qt, nothing from the rest of the package.
"""

from __future__ import annotations

import re

# Bytes in one megabyte, the unit the minimum-size setting is written in.
MEGABYTE = 1 << 20

# A non-negative decimal number and nothing else. No unit suffix: the field's
# label says MB, and accepting "4K" as well would make "4" ambiguous to read.
_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d*)?|\.\d+)\s*$")

_UNITS = ("B", "KB", "MB", "GB", "TB")


def parse_megabytes(text: str) -> int | None:
    """`text`, a number of megabytes, as a number of bytes; None if it is not one.

    Fractions are allowed (`0.5` is 512 KB) and rounded down to whole bytes.
    """
    match = _NUMBER_RE.match(text)
    if not match:
        return None
    return int(float(match.group(1)) * MEGABYTE)


def megabytes_problem(text: str) -> str | None:
    """A message if `text` cannot be read as megabytes; None if it can."""
    if parse_megabytes(text) is None:
        return (
            f"\"{text}\" is not a number of megabytes. Write a number such as "
            "0, 0.5 or 10 (0 compares every non-empty file)."
        )
    return None


def format_size(count: int) -> str:
    """`count` bytes for a person: `512 B`, `4.0 KB`, `1.2 GB`.

    Whole bytes below a KB, where a decimal would be noise; one decimal place
    above it, which tells 1.0 GB from 1.4 GB without pretending to more
    precision than anyone deciding what to delete needs.
    """
    value = float(count)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            return f"{count:,} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")  # pragma: no cover
