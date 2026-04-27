"""Clinical coverage computations over accepted annotations."""

from __future__ import annotations

from dataclasses import dataclass

from rime_core.annotations import AnnotationStore
from rime_core.common.intervals import merge_intervals, union_duration_ms


@dataclass(frozen=True)
class CoverageSpec:
    """One lane/label selector for a coverage numerator or denominator."""

    lane: str
    label: str | None = None


@dataclass
class CoverageResult:
    """Coverage ratio plus merged-interval summary counts."""

    ratio: float
    percent: float
    numerator_ms: float
    denominator_ms: float
    numerator_episodes: int
    denominator_episodes: int


def compute_coverage(
    store: AnnotationStore,
    numerator: list[CoverageSpec],
    *,
    denominator: list[CoverageSpec] | None = None,
    session_duration_ms: float,
) -> CoverageResult:
    """Compute merged-interval coverage over non-ghost annotations."""
    numerator_ms, numerator_episodes = _union_duration_ms(_matched_intervals(store, numerator))

    if denominator is None:
        denominator_ms = max(0.0, float(session_duration_ms))
        denominator_episodes = -1
    else:
        denominator_ms, denominator_episodes = _union_duration_ms(
            _matched_intervals(store, denominator)
        )

    ratio = 0.0 if denominator_ms <= 0 else float(numerator_ms / denominator_ms)
    return CoverageResult(
        ratio=ratio,
        percent=ratio * 100.0,
        numerator_ms=numerator_ms,
        denominator_ms=denominator_ms,
        numerator_episodes=numerator_episodes,
        denominator_episodes=denominator_episodes,
    )


def _matched_intervals(store: AnnotationStore, specs: list[CoverageSpec]) -> list[tuple[float, float]]:
    if not specs:
        return []

    intervals: list[tuple[float, float]] = []
    for annotation in store.all():
        if annotation.ghost or annotation.event_type == "point":
            continue
        if any(_matches_spec(annotation.lane, annotation.label, spec) for spec in specs):
            intervals.append((annotation.start_ms, annotation.end_ms))
    return intervals


def _matches_spec(lane: str, label: str, spec: CoverageSpec) -> bool:
    if lane != spec.lane:
        return False
    return spec.label is None or label == spec.label


def _union_duration_ms(intervals: list[tuple[float, float]]) -> tuple[float, int]:
    """Return merged duration and merged-episode count."""
    merged = merge_intervals(intervals)
    return union_duration_ms(merged), len(merged)
