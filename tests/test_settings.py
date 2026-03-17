from __future__ import annotations

from pathlib import Path

from rime_core.settings import AppSettings, load_settings, save_settings


def test_settings_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = AppSettings(
        default_rater="AZ",
        default_export_dir="/tmp/rime-exports",
        default_playback_speed=1.5,
        shortcut_overrides={"show_shortcuts": "Ctrl+/", "delete_selection": ""},
    )

    written = save_settings(settings, path)
    loaded = load_settings(path)

    assert written == path
    assert loaded == settings


def test_load_settings_defaults_for_missing_or_invalid_file(tmp_path: Path) -> None:
    missing = load_settings(tmp_path / "missing.json")
    assert missing == AppSettings()

    invalid_path = tmp_path / "bad.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    invalid = load_settings(invalid_path)

    assert invalid == AppSettings()
