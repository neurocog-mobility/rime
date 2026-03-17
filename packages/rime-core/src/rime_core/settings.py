"""Persistent application settings for RIME."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AppSettings:
    """User-level application preferences."""

    default_rater: str = ""
    default_export_dir: str = ""
    default_playback_speed: float = 1.0
    shortcut_overrides: dict[str, str] = field(default_factory=dict)


def default_settings_dir() -> Path:
    """Return the platform-appropriate settings directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "rime"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "rime"
        return Path.home() / "AppData" / "Roaming" / "rime"
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "rime"
    return Path.home() / ".config" / "rime"


def default_settings_path() -> Path:
    """Default location of settings.json."""
    return default_settings_dir() / "settings.json"


def load_settings(path: str | Path | None = None) -> AppSettings:
    """Load settings from disk, falling back to defaults on missing or invalid data."""
    settings_path = Path(path) if path is not None else default_settings_path()
    if not settings_path.exists():
        return AppSettings()

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    if not isinstance(raw, dict):
        return AppSettings()

    return AppSettings(
        default_rater=_coerce_str(raw.get("default_rater", "")),
        default_export_dir=_coerce_str(raw.get("default_export_dir", "")),
        default_playback_speed=_coerce_speed(raw.get("default_playback_speed", 1.0)),
        shortcut_overrides=_coerce_shortcut_overrides(raw.get("shortcut_overrides", {})),
    )


def save_settings(settings: AppSettings, path: str | Path | None = None) -> Path:
    """Persist settings.json and return the written path."""
    settings_path = Path(path) if path is not None else default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    payload = asdict(settings)
    payload["default_playback_speed"] = _coerce_speed(payload.get("default_playback_speed", 1.0))
    payload["shortcut_overrides"] = _coerce_shortcut_overrides(
        payload.get("shortcut_overrides", {})
    )
    settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return settings_path


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_speed(value: Any) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if speed <= 0:
        return 1.0
    return speed


def _coerce_shortcut_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        cleaned[key.strip()] = item.strip()
    return cleaned
