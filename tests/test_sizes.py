"""Sizes as typed into the settings, and as the window shows them."""

from __future__ import annotations

import pytest

from dupfinder.sizes import MEGABYTE, format_size, megabytes_problem, parse_megabytes


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0", 0),
        ("1", MEGABYTE),
        (" 10 ", 10 * MEGABYTE),
        ("0.5", MEGABYTE // 2),
        (".25", MEGABYTE // 4),
        ("2.", 2 * MEGABYTE),
        ("0.0000001", 0),
    ],
)
def test_parse_megabytes(text, expected):
    assert parse_megabytes(text) == expected


@pytest.mark.parametrize("text", ["", ".", "abc", "-1", "4K", "10M", "10 MB", "1e3", "1,5"])
def test_not_megabytes(text):
    assert parse_megabytes(text) is None
    assert megabytes_problem(text)


def test_megabytes_have_no_problem():
    assert megabytes_problem("10") is None


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, "0 B"),
        (1023, "1,023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (5 * 1024 * 1024, "5.0 MB"),
        (3 << 30, "3.0 GB"),
        (2048 << 40, "2048.0 TB"),
    ],
)
def test_format_size(count, expected):
    assert format_size(count) == expected
