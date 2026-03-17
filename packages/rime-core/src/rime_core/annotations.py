"""Lane-based annotation model and store for RIME."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


AnnotationSource = Literal["manual", "corrected", "elan_import"] | str
AnnotationEventType = Literal["interval", "point"]

_SORT_KEY = lambda ann: (ann.start_ms, ann.end_ms, ann.id)  # noqa: E731


@dataclass
class Annotation:
    """A single annotation on a schema-defined lane."""

    id: str
    lane: str
    label: str
    start_ms: float
    end_ms: float
    event_type: AnnotationEventType = "interval"
    source: AnnotationSource = "manual"
    ghost: bool = False
    confidence: float = 1.0
    human_modified: bool = False
    origin_confidence: float | None = None
    origin_start_ms: float | None = None
    origin_end_ms: float | None = None

    @property
    def duration_ms(self) -> float:
        """Duration of the annotation in milliseconds."""
        return self.end_ms - self.start_ms

    def contains(self, time_ms: float) -> bool:
        """Check if a time point is within this annotation."""
        return self.start_ms <= time_ms <= self.end_ms

    def overlaps(self, other: Annotation) -> bool:
        """Check if this annotation overlaps another annotation."""
        return self.start_ms < other.end_ms and other.start_ms < self.end_ms

    def is_subset_of(self, other: Annotation) -> bool:
        """Check if this annotation is fully contained by another annotation."""
        return self.start_ms >= other.start_ms and self.end_ms <= other.end_ms


class AnnotationStore:
    """In-memory flat store for annotations with lane queries."""

    def __init__(self) -> None:
        self.annotations: dict[str, Annotation] = {}
        self._session_id: str = ""
        self._session_name: str = ""

    # --- CRUD ---

    def add(self, annotation: Annotation) -> None:
        """Add an annotation to the store."""
        self.annotations[annotation.id] = annotation

    def remove(self, ann_id: str) -> None:
        """Remove an annotation if present."""
        self.annotations.pop(ann_id, None)

    def get(self, ann_id: str) -> Annotation | None:
        """Fetch an annotation by ID."""
        return self.annotations.get(ann_id)

    def clear(self) -> None:
        """Clear all annotations."""
        self.annotations.clear()

    # --- Queries ---

    def get_by_lane(self, lane_name: str) -> list[Annotation]:
        """Return annotations for one lane sorted by start time."""
        return sorted(
            [ann for ann in self.annotations.values() if ann.lane == lane_name],
            key=_SORT_KEY,
        )

    def get_at_time(self, time_ms: float, lane_name: str | None = None) -> list[Annotation]:
        """Return annotations active at a timepoint, optionally lane-filtered."""
        items = self.annotations.values()
        if lane_name is not None:
            items = (ann for ann in items if ann.lane == lane_name)
        return sorted(
            [ann for ann in items if ann.contains(time_ms)],
            key=_SORT_KEY,
        )

    def get_overlapping(
        self, start_ms: float, end_ms: float, lane_name: str | None = None
    ) -> list[Annotation]:
        """Return annotations overlapping a time range, optionally lane-filtered."""
        items = self.annotations.values()
        if lane_name is not None:
            items = (ann for ann in items if ann.lane == lane_name)
        return sorted(
            [ann for ann in items if ann.start_ms < end_ms and start_ms < ann.end_ms],
            key=_SORT_KEY,
        )

    def all(self) -> list[Annotation]:
        """Return all annotations sorted by start time."""
        return sorted(self.annotations.values(), key=_SORT_KEY)

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Convert store to dictionary for JSON serialization."""
        serialized = [
            {
                "id": ann.id,
                "lane": ann.lane,
                "label": ann.label,
                "start_ms": ann.start_ms,
                "end_ms": ann.end_ms,
                "event_type": ann.event_type,
                "source": ann.source,
                "ghost": ann.ghost,
                "confidence": ann.confidence,
                "human_modified": ann.human_modified,
                "origin_confidence": ann.origin_confidence,
                "origin_start_ms": ann.origin_start_ms,
                "origin_end_ms": ann.origin_end_ms,
            }
            for ann in sorted(self.annotations.values(), key=_SORT_KEY)
        ]
        return {
            "version": "1.1",
            "session": {"id": self._session_id, "name": self._session_name},
            "annotations": serialized,
        }

    def save(self, path: str | Path) -> None:
        """Save annotations to JSON file."""
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> AnnotationStore:
        """Load annotations from an in-memory dictionary."""
        store = cls()
        session = data.get("session", {})
        store._session_id = session.get("id", "")
        store._session_name = session.get("name", "")

        for raw in data.get("annotations", []):
            store.add(
                Annotation(
                    id=raw["id"],
                    lane=raw.get("lane", ""),
                    label=raw.get("label", ""),
                    start_ms=raw.get("start_ms", 0.0),
                    end_ms=raw.get("end_ms", 0.0),
                    event_type=raw.get("event_type", "interval"),
                    source=raw.get("source", "manual"),
                    ghost=raw.get("ghost", False),
                    confidence=raw.get("confidence", 1.0),
                    human_modified=raw.get("human_modified", False),
                    origin_confidence=raw.get("origin_confidence"),
                    origin_start_ms=raw.get("origin_start_ms"),
                    origin_end_ms=raw.get("origin_end_ms"),
                )
            )
        return store

    @classmethod
    def load(cls, path: str | Path) -> AnnotationStore:
        """Load annotations from JSON file."""
        in_path = Path(path)
        with open(in_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls.from_dict(data)


def generate_id() -> str:
    """Generate a short unique annotation ID."""
    return uuid.uuid4().hex[:8]
