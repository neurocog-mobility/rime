"""Scoped interval calculations, immutable captures, verification, and comparison.

This module has no dependency on Qt, media files, or workspace persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math

from rime_core.common.intervals import merge_intervals
from rime_core.outcomes import OutcomeDefinition
from rime_core.records.models import new_id
from rime_core.records.revisions import CapturedRevision

Span = tuple[float, float]
RECORD_VERSION = "0.3"


@dataclass(frozen=True)
class MeasurementDefinition:
    outcome: OutcomeDefinition
    observation: tuple[Span, ...]
    exclusions: tuple[Span, ...] = ()
    review_status: str = "unknown"
    review_note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, OutcomeDefinition):
            raise ValueError("Select a protocol outcome definition.")
        if self.review_status not in {"unknown", "incomplete", "complete"}:
            raise ValueError("Unknown human review status.")
        if not isinstance(self.review_note, str) or not self.observation:
            raise ValueError("Declare an observation scope and a textual review note.")
        for key in ("observation", "exclusions"):
            spans = tuple(tuple(s) for s in getattr(self, key))
            if any(len(s) != 2 or not all(math.isfinite(v) for v in s)
                   or s[0] > s[1] for s in spans):
                raise ValueError("Scope intervals must be finite and ordered.")
            object.__setattr__(self, key, spans)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> MeasurementDefinition:
        return cls(**{**data, "outcome": OutcomeDefinition.from_dict(data["outcome"])})


@dataclass(frozen=True)
class Contribution:
    annotation_id: str
    original: Span
    clipped: tuple[Span, ...]


@dataclass(frozen=True)
class Quantity:
    label: str
    value: float | int
    unit: str


@dataclass(frozen=True)
class MeasurementResult:
    value: float | int | None
    unit: str
    undefined_reason: str | None
    components: tuple[Quantity, ...]
    covered_ms: float
    eligible_ms: float
    event_spans: tuple[Span, ...]
    eligible_spans: tuple[Span, ...]
    contributors: tuple[Contribution, ...]
    scope_contributors: tuple[Contribution, ...]

    def to_dict(self) -> dict:
        import json
        return json.loads(json.dumps(asdict(self), allow_nan=False))



def intersect(left: tuple[Span, ...] | list[Span],
              right: tuple[Span, ...] | list[Span]) -> tuple[Span, ...]:
    return tuple(merge_intervals((max(a, c), min(b, d))
                                for a, b in left for c, d in right
                                if max(a, c) < min(b, d)))


def subtract(spans: tuple[Span, ...], exclusions: tuple[Span, ...]) -> tuple[Span, ...]:
    remaining = list(merge_intervals(spans))
    for start, end in merge_intervals(exclusions):
        pieces = []
        for a, b in remaining:
            if end <= a or start >= b:
                pieces.append((a, b))
            else:
                if a < start:
                    pieces.append((a, start))
                if end < b:
                    pieces.append((end, b))
        remaining = pieces
    return tuple(remaining)


def _covered_duration(covered_ms, eligible_ms, count):
    return covered_ms / 1000, "s", (Quantity("Covered duration", covered_ms / 1000, "s"),)


def _percentage_coverage(covered_ms, eligible_ms, count):
    return (100 * covered_ms / eligible_ms if eligible_ms else None), "%", (
        Quantity("Covered duration", covered_ms / 1000, "s"),
        Quantity("Eligible time", eligible_ms / 1000, "s"),
    )


def _count(covered_ms, eligible_ms, count):
    return count, "count", (Quantity("Counted annotations", count, "count"),)


_CALCULATORS = {"covered_duration": _covered_duration,
               "percentage_coverage": _percentage_coverage, "count": _count}


def calculate(revision: CapturedRevision, definition: MeasurementDefinition) -> MeasurementResult:
    domain = revision.domain()
    ann_set = domain["annotation_set"]
    outcome = definition.outcome
    lanes = {lane["name"]: lane for lane in ann_set["protocol"]["lanes"]}
    event_lane = lanes.get(outcome.events.lane)
    if event_lane is None:
        raise ValueError("The outcome selects an unknown event lane.")
    if outcome.calculation != "count" and event_lane.get("lane_type", "interval") != "interval":
        raise ValueError("Duration and percentage coverage require interval annotations.")
    if outcome.scope is not None and (
        outcome.scope.lane not in lanes or lanes[outcome.scope.lane].get("lane_type", "interval") != "interval"
    ):
        raise ValueError("The outcome scope must select an interval lane.")
    annotations = [a for a in ann_set["annotations"] if not a["ghost"]]

    def selected(selector):
        return [a for a in annotations if a["lane"] == selector.lane
                and (selector.label is None or a["label"] == selector.label)]

    def contributions(items, scope, include_points=False):
        result = []
        for a in items:
            original = (a["start_ms"], a["end_ms"])
            if a["event_type"] == "point":
                if include_points and any(start <= original[0] < end for start, end in scope):
                    result.append(Contribution(a["id"], original, (original,)))
            else:
                clipped = intersect([original], scope)
                if clipped:
                    result.append(Contribution(a["id"], original, clipped))
        return tuple(result)

    observation = subtract(definition.observation, definition.exclusions)
    scope_annotations = selected(outcome.scope) if outcome.scope else []
    eligible = (intersect(observation, [(a["start_ms"], a["end_ms"])
                                      for a in scope_annotations if a["event_type"] == "interval"])
                if outcome.scope else observation)
    contributors = contributions(selected(outcome.events), eligible, outcome.calculation == "count")
    event_spans = tuple(merge_intervals(span for c in contributors for span in c.clipped))
    covered_ms = math.fsum(b-a for a, b in event_spans)
    eligible_ms = math.fsum(b-a for a, b in eligible)
    value, unit, components = _CALCULATORS[outcome.calculation](covered_ms, eligible_ms, len(contributors))
    reason = None
    if eligible_ms == 0:
        reason = "The eligible observation duration is zero."
    elif not contributors and definition.review_status != "complete" and outcome.calculation != "count":
        reason = "No selected events; human review of the eligible scope is not declared complete."
    return MeasurementResult(None if reason else value, unit, reason, components,
                             covered_ms, eligible_ms, event_spans, eligible, contributors,
                             contributions(scope_annotations, eligible))


@dataclass(frozen=True)
class MeasurementRecord:
    id: str
    captured_at: str
    definition: MeasurementDefinition
    revision: CapturedRevision
    result: MeasurementResult

    @classmethod
    def capture(cls, revision: CapturedRevision,
                definition: MeasurementDefinition) -> MeasurementRecord:
        return cls(new_id("measurement"), datetime.now(timezone.utc).isoformat(),
                   definition, revision, calculate(revision, definition))

    def verify(self) -> bool:
        return self.result == calculate(self.revision, self.definition)

    def to_dict(self) -> dict:
        return {"format": "rime-measurement-record", "version": RECORD_VERSION,
                "id": self.id, "captured_at": self.captured_at,
                "definition": self.definition.to_dict(), "revision": self.revision.to_dict(),
                "result": self.result.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> MeasurementRecord:
        if data.get("format") != "rime-measurement-record" or data.get("version") != RECORD_VERSION:
            raise ValueError("Unsupported measurement record format/version.")
        if not isinstance(data["id"], str) or not data["id"].startswith("measurement-"):
            raise ValueError("Invalid measurement identity.")
        if datetime.fromisoformat(data["captured_at"]).tzinfo is None:
            raise ValueError("Capture timestamp requires a timezone.")
        definition = MeasurementDefinition.from_dict(data["definition"])
        revision = CapturedRevision.from_dict(data["revision"])
        result = calculate(revision, definition)
        if result.to_dict() != data["result"]:
            raise ValueError("Saved measurement result does not match its inputs.")
        return cls(data["id"], data["captured_at"], definition, revision, result)


def compare(left: MeasurementRecord, right: MeasurementRecord) -> dict[str, bool]:
    """Declared dependency differences, not causal or clinical judgments."""
    a, b = left.revision.domain(), right.revision.domain()
    return {
        "Scoring rule and event selection": (left.definition.outcome.calculation, left.definition.outcome.calculation_version, left.definition.outcome.events)
            != (right.definition.outcome.calculation, right.definition.outcome.calculation_version, right.definition.outcome.events),
        "Observation scope and exclusions": (
            left.definition.observation, left.definition.outcome.scope, left.definition.exclusions)
            != (right.definition.observation, right.definition.outcome.scope, right.definition.exclusions),
        "Human review declaration": (left.definition.review_status, left.definition.review_note)
            != (right.definition.review_status, right.definition.review_note),
        "Annotation set and boundaries": a["annotation_set"]["annotations"]
            != b["annotation_set"]["annotations"] or a["annotation_set"]["id"]
            != b["annotation_set"]["id"],
        "Clinical protocol": a["annotation_set"]["protocol"] != b["annotation_set"]["protocol"],
        "Annotation origin": (a["annotation_set"]["provenance"], a["annotation_set"]["rater"])
            != (b["annotation_set"]["provenance"], b["annotation_set"]["rater"]),
        "Research context": a["research_context"] != b["research_context"],
        "Source descriptions and timing (evidence)": a["recordings"] != b["recordings"],
    }
