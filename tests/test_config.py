"""The config file: defaults, round trips, and forgiving loads."""

from __future__ import annotations

import os

import yaml

from dupfinder import config
from dupfinder.config import DEFAULTS, Settings, ensure_config, load_settings, save_settings


def test_first_run_writes_the_defaults(conf):
    os.remove(config.CONFIG_PATH)
    ensure_config()
    settings, error = load_settings()
    assert error is None
    assert settings == DEFAULTS
    assert "*/node_modules/*" in settings.excluded
    assert settings.open_command == "xdg-open"
    assert settings.min_size_mb == "0"


def test_a_missing_file_is_the_fallbacks_and_no_error(conf):
    os.remove(config.CONFIG_PATH)
    settings, error = load_settings()
    assert error is None
    assert settings == Settings()


def test_round_trip(conf):
    saved = Settings(
        included=("*.jpg",),
        excluded=("*/cache/*", "*.log"),
        use_included=False,
        use_excluded=True,
        min_size_mb="10",
        open_command="eog --fullscreen",
    )
    assert save_settings(saved) is None
    assert load_settings() == (saved, None)


def test_switched_off_lists_are_kept_but_not_applied():
    settings = Settings(included=("*.jpg",), excluded=("*.log",), use_included=False,
                        use_excluded=False)
    assert settings.active_included == () and settings.active_excluded == ()
    assert settings.included == ("*.jpg",)


def test_broken_yaml_degrades_to_defaults_with_a_message(conf):
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan: [unclosed\n")
    settings, error = load_settings()
    assert settings == Settings()
    assert error


def test_one_bad_key_costs_only_that_key(conf):
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan:\n  included: 7\n  min_size_mb: \"4\"\nopen:\n  command: true\n")
    settings, _ = load_settings()
    assert settings.included == ()
    assert settings.min_size_mb == "4"
    assert settings.open_command == "xdg-open"


def test_a_bare_number_is_a_size(conf):
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan:\n  min_size_mb: 10\n")
    assert load_settings()[0].min_size_mb == "10"
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan:\n  min_size_mb: 0.5\n")
    assert load_settings()[0].min_size_mb == "0.5"


def test_the_old_byte_count_key_is_not_read_as_megabytes(conf):
    """Before the setting was in MB it was `min_size`, defaulting to one byte.
    Read as megabytes, that old default would hide every file under 1 MB."""
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan:\n  min_size: \"1\"\n")
    assert load_settings()[0].min_size_mb == "0"


def test_unknown_keys_survive_a_save(conf):
    with open(config.CONFIG_PATH, "w") as handle:
        handle.write("scan:\n  future_key: 3\nextra:\n  thing: yes\n")
    assert save_settings(Settings()) is None
    with open(config.CONFIG_PATH) as handle:
        data = yaml.safe_load(handle)
    assert data["scan"]["future_key"] == 3
    assert data["extra"] == {"thing": True}


def test_the_written_file_explains_itself(conf):
    with open(config.CONFIG_PATH) as handle:
        text = handle.read()
    assert text.startswith("# DupFinder configuration.")
    assert "min_size_mb:" in text and "command:" in text
