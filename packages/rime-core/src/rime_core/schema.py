"""Schema value types for protocol-specific lane/rule definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA_PATH = Path(__file__).parent / "config" / "gpfog_schema.json"
NOTES_ONLY_SCHEMA_PATH = Path(__file__).parent / "config" / "notes_only_schema.json"


class SchemaValidationError(Exception):
    """Raised when a schema JSON is missing required fields or has bad structure."""


@dataclass
class LaneSchema:
    """One lane declaration in a protocol schema."""

    name: str
    level: int
    color: str
    labels: list[str]
    allow_overlap: bool = True
    lane_type: str = "interval"


@dataclass
class ProtocolSchema:
    """In-memory value type for a full annotation protocol schema."""

    version: str
    name: str
    lanes: list[LaneSchema]
    groups: list[dict[str, Any]]
    rules: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path | str) -> ProtocolSchema:
        """Load a schema from a JSON file."""
        schema_path = Path(path)
        try:
            raw = json.loads(schema_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SchemaValidationError(f"Schema file not found: {schema_path}") from exc
        except json.JSONDecodeError as exc:
            raise SchemaValidationError(f"Invalid schema JSON in {schema_path}: {exc}") from exc

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SchemaValidationError(f"Missing or invalid 'name' in {schema_path}")

        lanes_raw = raw.get("lanes")
        if not isinstance(lanes_raw, list) or not lanes_raw:
            raise SchemaValidationError(f"Missing or invalid 'lanes' in {schema_path}")

        lanes: list[LaneSchema] = []
        for idx, lane_raw in enumerate(lanes_raw):
            if not isinstance(lane_raw, dict):
                raise SchemaValidationError(f"Lane {idx} must be an object in {schema_path}")

            lane_name = lane_raw.get("name")
            lane_level = lane_raw.get("level")
            lane_color = lane_raw.get("color")
            lane_labels = lane_raw.get("labels")
            allow_overlap = lane_raw.get("allow_overlap", True)
            lane_type = lane_raw.get("lane_type", "interval")

            if not isinstance(lane_name, str) or not lane_name.strip():
                raise SchemaValidationError(f"Lane {idx} missing valid 'name' in {schema_path}")
            if not isinstance(lane_level, int):
                raise SchemaValidationError(f"Lane {lane_name!r} missing valid 'level' in {schema_path}")
            if not isinstance(lane_color, str) or not lane_color.strip():
                raise SchemaValidationError(f"Lane {lane_name!r} missing valid 'color' in {schema_path}")
            if not isinstance(lane_labels, list) or not lane_labels or not all(
                isinstance(label, str) and label.strip() for label in lane_labels
            ):
                raise SchemaValidationError(
                    f"Lane {lane_name!r} missing valid non-empty 'labels' in {schema_path}"
                )
            if not isinstance(allow_overlap, bool):
                raise SchemaValidationError(
                    f"Lane {lane_name!r} has invalid 'allow_overlap' in {schema_path}"
                )
            if lane_type not in {"interval", "point"}:
                raise SchemaValidationError(
                    f"Lane {lane_name!r} has invalid 'lane_type' (must be 'interval' or 'point')"
                )

            lanes.append(
                LaneSchema(
                    name=lane_name,
                    level=lane_level,
                    color=lane_color,
                    labels=lane_labels,
                    allow_overlap=allow_overlap,
                    lane_type=lane_type,
                )
            )

        groups = raw.get("groups", [])
        if not isinstance(groups, list):
            raise SchemaValidationError(f"Invalid 'groups' in {schema_path}")

        rules = raw.get("rules", [])
        if not isinstance(rules, list):
            raise SchemaValidationError(f"Invalid 'rules' in {schema_path}")

        version = raw.get("version", "1.0")
        if not isinstance(version, str) or not version.strip():
            raise SchemaValidationError(f"Missing or invalid 'version' in {schema_path}")

        return cls(
            version=version,
            name=name,
            lanes=lanes,
            groups=groups,
            rules=rules,
        )

    @classmethod
    def default(cls) -> ProtocolSchema:
        """Return the built-in GP-FOG schema."""
        return cls.load(DEFAULT_SCHEMA_PATH)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the schema back to JSON-compatible data."""
        return {
            "version": self.version,
            "name": self.name,
            "lanes": [
                {
                    "name": lane.name,
                    "level": lane.level,
                    "color": lane.color,
                    "labels": list(lane.labels),
                    "allow_overlap": lane.allow_overlap,
                    "lane_type": lane.lane_type,
                }
                for lane in self.lanes
            ],
            "groups": list(self.groups),
            "rules": list(self.rules),
        }

    def save(self, path: Path | str) -> Path:
        """Persist the schema JSON to disk and return the written path."""
        schema_path = Path(path)
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return schema_path

    def get_lane(self, name: str) -> LaneSchema | None:
        """Case-insensitive lane lookup by name."""
        needle = name.strip().casefold()
        for lane in self.lanes:
            if lane.name.casefold() == needle:
                return lane
        return None

    def get_lane_names(self) -> list[str]:
        """All lane names in schema order."""
        return [lane.name for lane in self.lanes]

    def is_point_lane(self, name: str) -> bool:
        """Return True if the named lane stores instantaneous events."""
        lane = self.get_lane(name)
        return lane.lane_type == "point" if lane else False

    def get_lane_by_level(self, level: int) -> LaneSchema | None:
        """Lookup by numeric level."""
        for lane in self.lanes:
            if lane.level == level:
                return lane
        return None

    def is_valid_label(self, lane: str, label: str) -> bool:
        """Return True if label is declared in the given lane."""
        lane_schema = self.get_lane(lane)
        return label in lane_schema.labels if lane_schema else False

    def get_labels(self, lane: str) -> list[str]:
        """Declared labels for a lane. Empty list if lane unknown."""
        lane_schema = self.get_lane(lane)
        return list(lane_schema.labels) if lane_schema else []

    def get_default_label(self, lane: str) -> str | None:
        """First declared label for a lane, or None."""
        labels = self.get_labels(lane)
        return labels[0] if labels else None


def suggest_next_schema_version(version: str) -> str:
    """Return a simple incremented version suggestion for schema edits."""
    parts = version.strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return version
    if len(parts) == 1:
        return f"{parts[0]}.1"
    incremented = parts[:-1] + [str(int(parts[-1]) + 1)]
    return ".".join(incremented)
