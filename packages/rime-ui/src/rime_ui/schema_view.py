"""UI-side compatibility helpers over ProtocolSchema."""

from __future__ import annotations

from typing import Any

from rime_core.schema import LaneSchema, ProtocolSchema


class SchemaView:
    """Expose ProtocolSchema through the shape the existing UI expects."""

    def __init__(self, schema: ProtocolSchema) -> None:
        self.set_schema(schema)

    def set_schema(self, schema: ProtocolSchema) -> None:
        self.schema = schema

    @property
    def lanes(self) -> list[dict[str, Any]]:
        return [self._lane_to_dict(lane) for lane in self.schema.lanes]

    @property
    def groups(self) -> list[dict[str, Any]]:
        return self.schema.groups

    def get_lane_config(self, level: int) -> dict[str, Any] | None:
        lane = self.schema.get_lane_by_level(level)
        return self._lane_to_dict(lane) if lane else None

    def get_lane_by_name(self, name: str) -> dict[str, Any] | None:
        lane = self.schema.get_lane(name)
        return self._lane_to_dict(lane) if lane else None

    def get_lane_names(self) -> list[str]:
        return self.schema.get_lane_names()

    def get_labels(self, level: int) -> list[str]:
        lane = self.schema.get_lane_by_level(level)
        return list(lane.labels) if lane else []

    @staticmethod
    def _lane_to_dict(lane: LaneSchema) -> dict[str, Any]:
        return {
            "name": lane.name,
            "level": lane.level,
            "color": lane.color,
            "labels": list(lane.labels),
            "allow_overlap": lane.allow_overlap,
            "lane_type": lane.lane_type,
        }
