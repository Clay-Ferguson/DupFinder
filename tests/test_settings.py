"""The settings dialog: what it shows, and what Save writes or refuses."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from dupfinder import config
from dupfinder.config import load_settings
from dupfinder.settings import SettingsDialog


def make(qtbot):
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    return dialog


def test_it_shows_the_file(qtbot, conf):
    conf(included=["*.jpg"], excluded=["*.log"], use_excluded=False, min_size_mb="4",
         open_command="eog")
    dialog = make(qtbot)
    assert dialog.included_edit.toPlainText() == "*.jpg"
    assert dialog.excluded_edit.toPlainText() == "*.log"
    assert dialog.included_check.isChecked() and not dialog.excluded_check.isChecked()
    assert not dialog.excluded_edit.isEnabled()
    assert dialog.min_size_edit.text() == "4"
    assert dialog.open_edit.text() == "eog"


def test_save_writes_every_field(qtbot, conf):
    dialog = make(qtbot)
    dialog.included_edit.setPlainText("*.png\n\n  *.jpg  \n")
    dialog.excluded_edit.setPlainText("*/cache/*")
    dialog.included_check.setChecked(False)
    dialog.min_size_edit.setText("0.5")
    dialog.open_edit.setText("gimp")
    dialog._save()
    settings, _ = load_settings()
    assert settings.included == ("*.png", "*.jpg")
    assert settings.excluded == ("*/cache/*",)
    assert not settings.use_included and settings.use_excluded
    assert settings.min_size_mb == "0.5"
    assert settings.open_command == "gimp"


def test_the_size_label_names_its_unit(qtbot, conf):
    dialog = make(qtbot)
    assert any("(MB)" in label.text() for label in dialog.findChildren(QLabel))


def test_an_empty_size_means_zero(qtbot, conf):
    dialog = make(qtbot)
    dialog.min_size_edit.setText("  ")
    dialog._save()
    assert load_settings()[0].min_size_mb == "0"


def test_bad_patterns_and_sizes_are_refused(qtbot, conf, dialogs):
    dialog = make(qtbot)
    dialog.included_edit.setPlainText("photos/*.jpg")
    dialog.min_size_edit.setText("big")
    dialog._save()
    message = dialogs[-1][1]
    assert "photos/*.jpg" in message and "big" in message
    # Nothing written: the file still holds the fixture's settings.
    assert load_settings()[0].included == ()


def test_an_unreadable_file_is_announced(qtbot, conf):
    """Save replaces the file, so someone looking at empty fields over a
    broken one has to be told that is what they are looking at."""
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan: [broken\n")
    dialog = make(qtbot)
    assert any("could not be read" in label.text() for label in dialog.findChildren(QLabel))
