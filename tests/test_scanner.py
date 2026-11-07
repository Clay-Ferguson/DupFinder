"""The duplicate search itself, with no Qt: `scanner.find_duplicates`.

Every case asserts on the exact set of groups, as paths relative to the tree,
so a test fails by showing what was found instead of only that it differed.
"""

from __future__ import annotations

import os
import threading

import pytest

from dupfinder import scanner
from dupfinder.patterns import PathFilter
from dupfinder.scanner import (
    PHASE_HASH,
    PHASE_SAMPLE,
    PHASE_WALK,
    SAMPLE_BYTES,
    WHOLE_FILE_BYTES,
    find_duplicates,
)

from conftest import block, needs_fifo, needs_permissions, write


def found(result, root):
    """The groups as a set of frozensets of paths relative to `root`."""
    return {frozenset(os.path.relpath(p, root) for p in group.paths) for group in result.groups}


@pytest.fixture
def full_reads(monkeypatch):
    """Every path `full_digest` is asked to read, in order."""
    paths = []
    original = scanner.full_digest

    def spy(path, cancel, progress):
        paths.append(path)
        return original(path, cancel, progress)

    monkeypatch.setattr(scanner, "full_digest", spy)
    return paths


# -- what is a duplicate ------------------------------------------------------------


def test_identical_files_are_grouped_and_different_ones_are_not(dup_tree):
    result = find_duplicates(dup_tree)
    assert found(result, dup_tree) == {
        frozenset({"photos/a.jpg", "backup/a-copy.jpg", "deep/x/y/a.jpg"}),
        frozenset({"docs/r.txt", "docs/r (1).txt", "node_modules/r.txt"}),
    }
    assert result.errors == [] and not result.cancelled


def test_paths_are_absolute_and_sorted_within_a_group(dup_tree):
    for group in find_duplicates(dup_tree).groups:
        assert list(group.paths) == sorted(group.paths)
        assert all(os.path.isabs(p) for p in group.paths)


def test_groups_come_largest_waste_first(tmp_path):
    root = str(tmp_path)
    write(tmp_path / "big1", block(1, 10_000))
    write(tmp_path / "big2", block(1, 10_000))
    for n in range(4):  # 3 spare copies of 5,000 bytes beat 1 of 10,000
        write(tmp_path / f"mid{n}", block(2, 5_000))
    result = find_duplicates(root)
    assert [g.reclaimable for g in result.groups] == [15_000, 10_000]
    assert result.reclaimable == 25_000
    assert result.duplicate_files == 6


def test_same_size_different_content_is_not_a_group(tmp_path):
    write(tmp_path / "a", block(1, 4096))
    write(tmp_path / "b", block(2, 4096))
    assert find_duplicates(str(tmp_path)).groups == []


def test_files_differing_only_in_the_tail_are_ruled_out_without_a_full_read(
    tmp_path, full_reads
):
    """Same first 64 KB — a shared camera or container header — but a
    different end. The sample stage's tail read is what separates them."""
    head = block(1, SAMPLE_BYTES * 3)
    write(tmp_path / "a", head + block(2, 1000))
    write(tmp_path / "b", head + block(3, 1000))
    assert find_duplicates(str(tmp_path)).groups == []
    assert full_reads == []


def test_files_differing_only_in_the_middle_need_the_full_hash(tmp_path, full_reads):
    """Head and tail identical: only reading every byte can tell them apart."""
    head, tail = block(1, SAMPLE_BYTES), block(2, SAMPLE_BYTES)
    write(tmp_path / "a", head + block(3, 50_000) + tail)
    write(tmp_path / "b", head + block(4, 50_000) + tail)
    write(tmp_path / "c", head + block(3, 50_000) + tail)  # a's twin
    result = find_duplicates(str(tmp_path))
    assert found(result, str(tmp_path)) == {frozenset({"a", "c"})}
    assert sorted(os.path.basename(p) for p in full_reads) == ["a", "b", "c"]


def test_a_small_file_is_finished_by_the_sample_stage(tmp_path, full_reads):
    """A file of WHOLE_FILE_BYTES or less is read whole when sampled, so it is
    never read a second time — and differences anywhere in it still count."""
    data = block(1, WHOLE_FILE_BYTES)
    write(tmp_path / "a", data)
    write(tmp_path / "b", data)
    middle = bytearray(data)
    middle[WHOLE_FILE_BYTES // 2] ^= 0xFF
    write(tmp_path / "c", bytes(middle))
    result = find_duplicates(str(tmp_path))
    assert found(result, str(tmp_path)) == {frozenset({"a", "b"})}
    assert full_reads == []


@needs_permissions
def test_a_file_with_a_unique_size_is_never_opened(tmp_path):
    """Unreadable, but its size is shared by nothing, so nothing tries."""
    path = write(tmp_path / "lonely", block(1, 777))
    write(tmp_path / "a", block(2, 100))
    write(tmp_path / "b", block(2, 100))
    os.chmod(path, 0)
    try:
        result = find_duplicates(str(tmp_path))
    finally:
        os.chmod(path, 0o644)
    assert result.errors == []
    assert found(result, str(tmp_path)) == {frozenset({"a", "b"})}


# -- what is never a duplicate ---------------------------------------------------------


def test_hard_links_are_one_file(tmp_path):
    write(tmp_path / "a", block(1, 1000))
    os.link(tmp_path / "a", tmp_path / "a-link")
    assert find_duplicates(str(tmp_path)).groups == []


def test_a_hard_linked_file_with_a_real_copy_is_listed_once(tmp_path):
    write(tmp_path / "a", block(1, 1000))
    os.link(tmp_path / "a", tmp_path / "b-link")
    write(tmp_path / "c", block(1, 1000))
    # Entries are walked in name order, so the first name met is "a".
    assert found(find_duplicates(str(tmp_path)), str(tmp_path)) == {frozenset({"a", "c"})}


def test_symlinks_are_never_followed(tmp_path):
    write(tmp_path / "real" / "a", block(1, 1000))
    os.symlink(tmp_path / "real" / "a", tmp_path / "file-link")
    # A link back up the tree: following it would loop forever.
    os.symlink(tmp_path, tmp_path / "real" / "loop")
    result = find_duplicates(str(tmp_path))
    assert result.groups == [] and result.errors == []
    assert result.files_scanned == 1


def test_empty_files_are_never_a_group(tmp_path):
    for name in "abc":
        write(tmp_path / name, b"")
    result = find_duplicates(str(tmp_path))
    assert result.groups == [] and result.files_scanned == 0


def test_files_below_the_minimum_size_are_left_out(tmp_path):
    write(tmp_path / "small1", block(1, 100))
    write(tmp_path / "small2", block(1, 100))
    write(tmp_path / "big1", block(2, 5000))
    write(tmp_path / "big2", block(2, 5000))
    result = find_duplicates(str(tmp_path), min_size=4096)
    assert found(result, str(tmp_path)) == {frozenset({"big1", "big2"})}
    assert result.files_scanned == 2


@needs_fifo
def test_a_fifo_is_ignored_rather_than_read(tmp_path):
    """Opening a FIFO to hash it would block the scan forever."""
    os.mkfifo(tmp_path / "pipe1")
    os.mkfifo(tmp_path / "pipe2")
    result = find_duplicates(str(tmp_path))
    assert result.groups == [] and result.files_scanned == 0


# -- the patterns ------------------------------------------------------------------------


def test_an_excluded_folder_is_not_entered(dup_tree):
    result = find_duplicates(dup_tree, PathFilter(excluded=["*/node_modules/*"]))
    assert frozenset({"docs/r.txt", "docs/r (1).txt"}) in found(result, dup_tree)


@needs_permissions
def test_an_excluded_folder_is_never_even_listed(tmp_path):
    """Unreadable, but skipped by name, so no error: it was never opened."""
    locked = tmp_path / "node_modules"
    write(locked / "x", b"x")
    os.chmod(locked, 0)
    try:
        result = find_duplicates(str(tmp_path), PathFilter(excluded=["*/node_modules/*"]))
    finally:
        os.chmod(locked, 0o755)
    assert result.errors == []


def test_include_patterns_limit_the_files_compared(dup_tree):
    result = find_duplicates(dup_tree, PathFilter(included=["*.jpg"]))
    assert found(result, dup_tree) == {
        frozenset({"photos/a.jpg", "backup/a-copy.jpg", "deep/x/y/a.jpg"})
    }


# -- errors and cancelling ----------------------------------------------------------------


@needs_permissions
def test_an_unreadable_copy_is_reported_and_the_rest_of_its_group_survives(tmp_path):
    for name in "abc":
        write(tmp_path / name, block(1, 1000))
    os.chmod(tmp_path / "c", 0)
    try:
        result = find_duplicates(str(tmp_path))
    finally:
        os.chmod(tmp_path / "c", 0o644)
    assert found(result, str(tmp_path)) == {frozenset({"a", "b"})}
    assert len(result.errors) == 1 and result.errors[0].startswith(str(tmp_path / "c"))


@needs_permissions
def test_an_unreadable_folder_is_reported_and_skipped(tmp_path):
    write(tmp_path / "locked" / "a", block(1, 1000))
    write(tmp_path / "open" / "a", block(1, 1000))
    write(tmp_path / "open" / "b", block(1, 1000))
    os.chmod(tmp_path / "locked", 0)
    try:
        result = find_duplicates(str(tmp_path))
    finally:
        os.chmod(tmp_path / "locked", 0o755)
    assert found(result, str(tmp_path)) == {frozenset({"open/a", "open/b"})}
    assert len(result.errors) == 1


def test_a_cancelled_scan_returns_no_groups(dup_tree):
    cancel = threading.Event()
    cancel.set()
    result = find_duplicates(dup_tree, cancel=cancel)
    assert result.cancelled and result.groups == []


def test_cancelling_during_the_full_hash_ends_the_scan(tmp_path):
    """Set from the progress callback the moment hashing starts — the way a
    Stop press from another thread lands mid-read."""
    head, tail = block(1, SAMPLE_BYTES), block(2, SAMPLE_BYTES)
    for name in "ab":
        write(tmp_path / name, head + block(3, 5 * 1024 * 1024) + tail)
    cancel = threading.Event()

    def progress(report):
        if report.phase == PHASE_HASH:
            cancel.set()

    result = find_duplicates(str(tmp_path), progress=progress, cancel=cancel)
    assert result.cancelled and result.groups == []


def test_progress_runs_through_the_stages_in_order(dup_tree):
    phases = []
    find_duplicates(dup_tree, progress=lambda p: phases.append(p.phase))
    order = [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p]
    assert order == [PHASE_WALK, PHASE_SAMPLE, PHASE_HASH]


def test_progress_comes_from_the_calling_thread(dup_tree):
    """The worker turns each report into a signal; reports from the hashing
    threads would arrive from threads Qt has never seen."""
    threads = set()
    find_duplicates(dup_tree, progress=lambda _p: threads.add(threading.get_ident()))
    assert threads == {threading.get_ident()}
