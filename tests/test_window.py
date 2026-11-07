"""The main window, driven the way a user drives it."""

from __future__ import annotations

import os
import threading

import pytest
from PyQt6.QtCore import Qt

from dupfinder import worker
from dupfinder.scanner import ScanResult
from dupfinder.window import FIND_LABEL, PATH_ROLE, STOP_LABEL, MainWindow

from conftest import TEST_OPEN_COMMAND, needs_permissions, write


def groups(window):
    """The tree as [(group label, [relative paths])]."""
    out = []
    for i in range(window.results.topLevelItemCount()):
        parent = window.results.topLevelItem(i)
        children = [parent.child(j).text(0) for j in range(parent.childCount())]
        out.append((parent.text(0), children))
    return out


def first_file_row(window):
    return window.results.topLevelItem(0).child(0)


def test_the_title_is_only_the_app_name(qtbot, tmp_path):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    assert window.windowTitle() == "DupFinder"


def test_a_scan_lists_the_groups_largest_first(scan, dup_tree):
    window = scan(dup_tree)
    assert groups(window) == [
        (
            "3 copies · 300.0 KiB each · 600.0 KiB reclaimable",
            ["backup/a-copy.jpg", "deep/x/y/a.jpg", "photos/a.jpg"],
        ),
        (
            "3 copies · 2.0 KiB each · 4.0 KiB reclaimable",
            ["docs/r (1).txt", "docs/r.txt", "node_modules/r.txt"],
        ),
    ]
    assert window._status.message.text() == (
        f"2 groups · 6 files · 604.0 KiB reclaimable — 7 files scanned in {dup_tree}"
    )
    assert not window._status.busy


def test_the_config_skip_list_applies(scan, conf, dup_tree):
    conf(excluded=["*/node_modules/*"])
    window = scan(dup_tree)
    assert groups(window)[1][1] == ["docs/r (1).txt", "docs/r.txt"]


def test_file_rows_carry_the_absolute_path_size_and_time(scan, dup_tree):
    row = first_file_row(scan(dup_tree))
    path = row.data(0, PATH_ROLE)
    assert path == os.path.join(dup_tree, "backup", "a-copy.jpg")
    assert row.toolTip(0) == path
    assert row.text(1) == "300.0 KiB"
    assert row.text(2)[:2] in ("19", "20")


def test_no_duplicates(scan, tmp_path):
    write(tmp_path / "a", b"one")
    window = scan(str(tmp_path))
    assert window.results.topLevelItemCount() == 0
    assert window._status.message.text().startswith("No duplicates — 1 file scanned in ")


def test_open_and_folder_act_only_on_file_rows(scan, dup_tree, spawned):
    window = scan(dup_tree)
    assert not window.open_button.isEnabled()

    window.results.setCurrentItem(window.results.topLevelItem(0))
    assert not window.open_button.isEnabled() and not window.folder_button.isEnabled()

    row = first_file_row(window)
    window.results.setCurrentItem(row)
    assert window.open_button.isEnabled() and window.folder_button.isEnabled()

    window.open_button.click()
    window.folder_button.click()
    path = row.data(0, PATH_ROLE)
    assert spawned == [
        [TEST_OPEN_COMMAND, path],
        ["/usr/bin/xdg-open", os.path.dirname(path)],
    ]


def test_open_on_a_file_deleted_since_the_scan_reports_it(scan, dup_tree, dialogs, spawned):
    window = scan(dup_tree)
    row = first_file_row(window)
    os.remove(row.data(0, PATH_ROLE))
    window.results.setCurrentItem(row)
    window.open_button.click()
    assert spawned == []
    assert "no longer exists" in dialogs[-1][1]


def test_not_a_folder_is_reported(qtbot, conf, tmp_path, dialogs):
    window = MainWindow(str(tmp_path / "missing"))
    qtbot.addWidget(window)
    window.start_scan()
    assert not window.scanning
    assert "Not a folder" in dialogs[-1][1]


def test_bad_settings_stop_the_scan_before_it_starts(qtbot, conf, tmp_path, dialogs):
    conf(excluded=["build/*"], min_size_mb="lots")
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    window.start_scan()
    assert not window.scanning
    message = dialogs[-1][1]
    assert "build/*" in message and "lots" in message


@needs_permissions
def test_unreadable_files_are_counted_and_listed(scan, tmp_path, dialogs):
    for name in "abc":
        write(tmp_path / name, b"same bytes")
    os.chmod(tmp_path / "c", 0)
    try:
        window = scan(str(tmp_path))
    finally:
        os.chmod(tmp_path / "c", 0o644)
    assert window._status.message.text().endswith("· 1 unreadable")
    assert str(tmp_path / "c") in dialogs[-1][1]


@pytest.fixture
def slow_scan(monkeypatch):
    """Replace the scanner with one that runs until it is cancelled."""
    started = threading.Event()

    def fake(root, path_filter, min_size, progress, cancel):
        started.set()
        cancel.wait(10)
        return ScanResult(root, files_scanned=3, cancelled=cancel.is_set())

    monkeypatch.setattr(worker, "find_duplicates", fake)
    return started


def test_stop_ends_a_running_scan(qtbot, conf, tmp_path, slow_scan):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    window.find_button.click()
    assert slow_scan.wait(5)
    assert window.scanning and window.find_button.text() == STOP_LABEL
    assert not window.folder_edit.isEnabled() and not window.settings_action.isEnabled()

    window.find_button.click()
    qtbot.waitUntil(lambda: not window.scanning, timeout=5000)
    assert window.find_button.text() == FIND_LABEL
    assert window.folder_edit.isEnabled() and window.settings_action.isEnabled()
    assert window._status.message.text() == "Stopped — 3 files scanned"
    assert window.results.topLevelItemCount() == 0


def test_closing_mid_scan_stops_the_worker(qtbot, conf, tmp_path, slow_scan):
    window = MainWindow(str(tmp_path))
    qtbot.addWidget(window)
    window.start_scan()
    assert slow_scan.wait(5)
    worker_thread = window._worker
    window.close()
    assert worker_thread is not None and worker_thread.isFinished()


def test_enter_in_the_folder_row_scans(qtbot, conf, dup_tree):
    window = MainWindow(dup_tree)
    qtbot.addWidget(window)
    qtbot.keyClick(window.folder_edit, Qt.Key.Key_Return)
    assert window.scanning
    qtbot.waitUntil(lambda: not window.scanning, timeout=30000)
    assert window.results.topLevelItemCount() == 2
