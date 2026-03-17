from __future__ import annotations

import json
from pathlib import Path

import pytest

from rime_core import ProtocolSchema, SchemaValidationError, suggest_next_schema_version


def test_default_schema_loads() -> None:
    schema = ProtocolSchema.default()

    assert schema.name == "FOG-COA"
    assert "FOG" in schema.get_lane_names()
    assert schema.get_default_label("FOG") == "FOG"


def test_schema_validation_error_for_missing_name(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "lanes": [{"name": "FOG", "level": 1, "color": "#fff", "labels": ["FOG"]}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SchemaValidationError, match="name"):
        ProtocolSchema.load(path)


def test_schema_queries() -> None:
    schema = ProtocolSchema.default()

    assert schema.get_lane("fog") is not None
    assert schema.get_lane_by_level(2) is not None
    assert schema.is_valid_label("Manifestations", "Akinetic") is True
    assert schema.get_labels("Notes") == ["Notes"]
    assert schema.is_point_lane("FOG") is False


def test_schema_accepts_point_lane_type(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "name": "Point Demo",
                "lanes": [
                    {
                        "name": "Steps",
                        "level": 1,
                        "color": "#fff",
                        "labels": ["step"],
                        "lane_type": "point",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    schema = ProtocolSchema.load(path)

    assert schema.is_point_lane("Steps") is True
    assert schema.get_lane("Steps") is not None
    assert schema.get_lane("Steps").lane_type == "point"


def test_schema_rejects_invalid_lane_type(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "name": "Bad Point Demo",
                "lanes": [
                    {
                        "name": "Steps",
                        "level": 1,
                        "color": "#fff",
                        "labels": ["step"],
                        "lane_type": "marker",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SchemaValidationError, match="lane_type"):
        ProtocolSchema.load(path)


def test_schema_save_roundtrip(tmp_path: Path) -> None:
    schema = ProtocolSchema.default()

    path = tmp_path / "saved-schema.json"
    schema.save(path)
    loaded = ProtocolSchema.load(path)

    assert loaded.name == schema.name
    assert loaded.version == schema.version
    assert loaded.get_lane_names() == schema.get_lane_names()


def test_suggest_next_schema_version() -> None:
    assert suggest_next_schema_version("1.0") == "1.1"
    assert suggest_next_schema_version("2") == "2.1"
    assert suggest_next_schema_version("release-candidate") == "release-candidate"
