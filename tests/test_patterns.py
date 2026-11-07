"""The pattern lists: what the walk's `PathFilter` skips, and what is refused."""

from __future__ import annotations

import pytest

from dupfinder.patterns import (
    PathFilter,
    parse_pattern_lines,
    pattern_lines,
    pattern_problems,
)


@pytest.mark.parametrize(
    "pattern,name,path,skipped",
    [
        ("*/node_modules/*", "node_modules", "/r/a/node_modules", True),
        ("*/node_modules/*", "node_modules2", "/r/node_modules2", False),
        ("*/photos/raw/*", "raw", "/r/x/photos/raw", True),
        ("*/photos/raw/*", "raw", "/r/x/raw", False),
        ("*/cache*/*", "cache-v2", "/r/cache-v2", True),
        ("*.app", "Thing.app", "/r/Thing.app", True),
        ("*/docs/*.tmp", "docs", "/r/docs", False),
    ],
)
def test_folders(pattern, name, path, skipped):
    assert PathFilter(excluded=[pattern]).skip_dir(name, path) is skipped


@pytest.mark.parametrize(
    "pattern,name,path,skipped",
    [
        ("*.log", "x.log", "/r/a/x.log", True),
        ("*.log", "x.log.txt", "/r/a/x.log.txt", False),
        ("*/docs/*.tmp", "a.tmp", "/r/docs/a.tmp", True),
        # find's -path `*` crosses '/', and so does this.
        ("*/docs/*.tmp", "a.tmp", "/r/docs/sub/a.tmp", True),
        ("*/docs/*.tmp", "a.tmp", "/r/other/a.tmp", False),
        # A folder pattern says nothing about a file of the same name.
        ("*/node_modules/*", "node_modules", "/r/node_modules", False),
        # Case-sensitive, like Sonar's.
        ("*.log", "X.LOG", "/r/X.LOG", False),
    ],
)
def test_files(pattern, name, path, skipped):
    assert PathFilter(excluded=[pattern]).skip_file(name, path) is skipped


def test_include_patterns_are_a_whitelist_of_file_names():
    only_photos = PathFilter(included=["*.jpg", "*.png"])
    assert not only_photos.skip_file("a.jpg", "/r/a.jpg")
    assert only_photos.skip_file("a.txt", "/r/a.txt")
    # ...and never hide a folder, or nothing inside it would be reached.
    assert not only_photos.skip_dir("Pictures", "/r/Pictures")


def test_an_empty_filter_skips_nothing():
    nothing = PathFilter()
    assert not nothing.skip_dir(".git", "/r/.git")
    assert not nothing.skip_file("a", "/r/a")


def test_pattern_problems_are_sonars():
    assert pattern_problems(["*.md"], ["*/build/*", "*.log"]) == []
    problems = pattern_problems(["docs/*.md"], ["build/*"])
    assert len(problems) == 2
    assert "docs/*.md" in problems[0]
    assert '"*/build/*"' in problems[1]


def test_text_area_round_trip():
    assert parse_pattern_lines("  *.jpg \n\n*.png\n") == ["*.jpg", "*.png"]
    assert pattern_lines(["*.jpg", "*.png"]) == "*.jpg\n*.png"
