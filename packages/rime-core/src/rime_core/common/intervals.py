"""Shared interval helpers used across analysis and export code."""

from __future__ import annotations

from collections.abc import Iterable

from rime_core.annotations import Annotation


def interval_iou(
    start_a: float,
    end_a: float,
    start_b: float,
    end_b: float,
) -> float:
    """Return temporal IoU for two intervals or coincident point events."""
    intersection = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    union = max(0.0, max(end_a, end_b) - min(start_a, start_b))
    if union <= 0.0:
        return 1.0 if start_a == start_b and end_a == end_b else 0.0
    return intersection / union


def annotation_iou(left: Annotation, right: Annotation) -> float:
    """Return temporal IoU for two annotations."""
    return interval_iou(left.start_ms, left.end_ms, right.start_ms, right.end_ms)


def merge_intervals(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping intervals and discard degenerate spans."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def union_duration_ms(intervals: Iterable[tuple[float, float]]) -> float:
    """Return the total merged duration across intervals."""
    return float(sum(end - start for start, end in merge_intervals(intervals)))
