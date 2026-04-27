"""Inter-rater reliability helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import isnan

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.common.intervals import annotation_iou, merge_intervals


@dataclass(frozen=True)
class IRRLabelResult:
    """Agreement metrics for one label."""

    label: str
    cohens_kappa: float
    set_iou: float
    matched: int
    unmatched_a: int
    unmatched_b: int


@dataclass(frozen=True)
class IRRResult:
    """Aggregate IRR result for one lane selection."""

    cohens_kappa: float
    set_iou: float
    matched_episodes: list[tuple[Annotation, Annotation]]
    unmatched_a: list[Annotation]
    unmatched_b: list[Annotation]
    per_label: dict[str, IRRLabelResult]


def compute_irr(
    store_a: AnnotationStore,
    store_b: AnnotationStore,
    duration_ms: float,
    *,
    lane: str | None = None,
    source_a: str | None = None,
    source_b: str | None = None,
    frame_resolution_ms: float = 40.0,
) -> IRRResult:
    """Compute pairwise inter-rater reliability over accepted annotations."""
    annotations_a = _accepted_annotations(store_a, lane=lane, source=source_a)
    annotations_b = _accepted_annotations(store_b, lane=lane, source=source_b)

    states_a = _frame_states(
        annotations_a,
        duration_ms,
        frame_resolution_ms=frame_resolution_ms,
        lane=lane,
    )
    states_b = _frame_states(
        annotations_b,
        duration_ms,
        frame_resolution_ms=frame_resolution_ms,
        lane=lane,
    )
    matched, unmatched_a, unmatched_b = _match_episodes(annotations_a, annotations_b)
    labels = sorted({annotation.label for annotation in [*annotations_a, *annotations_b]})

    per_label: dict[str, IRRLabelResult] = {}
    for label in labels:
        label_annotations_a = [annotation for annotation in annotations_a if annotation.label == label]
        label_annotations_b = [annotation for annotation in annotations_b if annotation.label == label]
        label_states_a = _binary_label_states(
            label_annotations_a,
            duration_ms,
            frame_resolution_ms=frame_resolution_ms,
        )
        label_states_b = _binary_label_states(
            label_annotations_b,
            duration_ms,
            frame_resolution_ms=frame_resolution_ms,
        )
        label_matched, label_unmatched_a, label_unmatched_b = _match_episodes(
            label_annotations_a,
            label_annotations_b,
        )
        per_label[label] = IRRLabelResult(
            label=label,
            cohens_kappa=_cohens_kappa(label_states_a, label_states_b),
            set_iou=_set_iou(label_annotations_a, label_annotations_b),
            matched=len(label_matched),
            unmatched_a=len(label_unmatched_a),
            unmatched_b=len(label_unmatched_b),
        )

    return IRRResult(
        cohens_kappa=_cohens_kappa(states_a, states_b),
        set_iou=_set_iou(annotations_a, annotations_b),
        matched_episodes=matched,
        unmatched_a=unmatched_a,
        unmatched_b=unmatched_b,
        per_label=per_label,
    )


def _accepted_annotations(
    store: AnnotationStore,
    *,
    lane: str | None,
    source: str | None = None,
) -> list[Annotation]:
    return [
        annotation
        for annotation in store.all()
        if not annotation.ghost
        and (lane is None or annotation.lane == lane)
        and (source is None or annotation.source == source)
    ]


def _frame_states(
    annotations: list[Annotation],
    duration_ms: float,
    *,
    frame_resolution_ms: float,
    lane: str | None,
) -> list[str]:
    frame_count = _frame_count(duration_ms, frame_resolution_ms)
    states: list[str] = []
    for index in range(frame_count):
        frame_start = index * frame_resolution_ms
        frame_end = frame_start + frame_resolution_ms
        active = {
            annotation.label
            if lane is not None
            else f"{annotation.lane}:{annotation.label}"
            for annotation in annotations
            if _annotation_overlaps_frame(annotation, frame_start, frame_end)
        }
        states.append("|".join(sorted(active)) if active else "none")
    return states


def _binary_label_states(
    annotations: list[Annotation],
    duration_ms: float,
    *,
    frame_resolution_ms: float,
) -> list[str]:
    frame_count = _frame_count(duration_ms, frame_resolution_ms)
    states: list[str] = []
    for index in range(frame_count):
        frame_start = index * frame_resolution_ms
        frame_end = frame_start + frame_resolution_ms
        active = any(
            _annotation_overlaps_frame(annotation, frame_start, frame_end)
            for annotation in annotations
        )
        states.append("label" if active else "none")
    return states


def _frame_count(duration_ms: float, frame_resolution_ms: float) -> int:
    if duration_ms <= 0 or frame_resolution_ms <= 0:
        return 0
    return max(1, int((duration_ms + frame_resolution_ms - 1) // frame_resolution_ms))


def _annotation_overlaps_frame(annotation: Annotation, frame_start: float, frame_end: float) -> bool:
    if annotation.event_type == "point":
        return frame_start <= annotation.start_ms < frame_end
    return annotation.start_ms < frame_end and frame_start < annotation.end_ms


def _match_episodes(
    annotations_a: list[Annotation],
    annotations_b: list[Annotation],
) -> tuple[list[tuple[Annotation, Annotation]], list[Annotation], list[Annotation]]:
    matched: list[tuple[Annotation, Annotation]] = []
    matched_b_ids: set[str] = set()
    unmatched_a: list[Annotation] = []

    for annotation_a in annotations_a:
        best_match: Annotation | None = None
        best_iou = 0.0
        for annotation_b in annotations_b:
            if annotation_b.id in matched_b_ids:
                continue
            if not _same_matching_key(annotation_a, annotation_b):
                continue
            iou = annotation_iou(annotation_a, annotation_b)
            if iou >= 0.1 and iou > best_iou:
                best_iou = iou
                best_match = annotation_b
        if best_match is None:
            unmatched_a.append(annotation_a)
            continue
        matched.append((annotation_a, best_match))
        matched_b_ids.add(best_match.id)

    unmatched_b = [annotation for annotation in annotations_b if annotation.id not in matched_b_ids]
    return matched, unmatched_a, unmatched_b


def _same_matching_key(annotation_a: Annotation, annotation_b: Annotation) -> bool:
    return (
        annotation_a.lane == annotation_b.lane
        and annotation_a.label == annotation_b.label
        and annotation_a.event_type == annotation_b.event_type
    )

def _merge_intervals(annotations: list[Annotation]) -> list[tuple[float, float]]:
    return merge_intervals(
        (annotation.start_ms, annotation.end_ms)
        for annotation in annotations
        if annotation.event_type != "point"
    )


def _set_iou(annotations_a: list[Annotation], annotations_b: list[Annotation]) -> float:
    """Temporal set IoU: intersection/union of annotation masks, independent of episode matching."""
    intervals_a = _merge_intervals(annotations_a)
    intervals_b = _merge_intervals(annotations_b)
    if not intervals_a and not intervals_b:
        return float("nan")
    if not intervals_a or not intervals_b:
        return 0.0

    intersection = 0.0
    i, j = 0, 0
    while i < len(intervals_a) and j < len(intervals_b):
        start = max(intervals_a[i][0], intervals_b[j][0])
        end = min(intervals_a[i][1], intervals_b[j][1])
        if start < end:
            intersection += end - start
        if intervals_a[i][1] < intervals_b[j][1]:
            i += 1
        else:
            j += 1

    all_intervals = sorted(intervals_a + intervals_b)
    union = 0.0
    cur_start, cur_end = all_intervals[0]
    for start, end in all_intervals[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            union += cur_end - cur_start
            cur_start, cur_end = start, end
    union += cur_end - cur_start

    return intersection / union


def _percent_agreement(states_a: list[str], states_b: list[str]) -> float:
    if not states_a or not states_b or len(states_a) != len(states_b):
        return float("nan")
    matches = sum(1 for a, b in zip(states_a, states_b, strict=False) if a == b)
    return matches / len(states_a)


def _cohens_kappa(states_a: list[str], states_b: list[str]) -> float:
    if not states_a or not states_b or len(states_a) != len(states_b):
        return float("nan")

    categories = sorted(set(states_a) | set(states_b))
    total = len(states_a)
    observed = _percent_agreement(states_a, states_b)
    probs_a = {category: 0.0 for category in categories}
    probs_b = {category: 0.0 for category in categories}
    for state in states_a:
        probs_a[state] += 1.0 / total
    for state in states_b:
        probs_b[state] += 1.0 / total
    expected = sum(probs_a[category] * probs_b[category] for category in categories)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def format_irr_value(value: float, *, percent: bool = False) -> str:
    """Format an IRR float with empty-state handling."""
    if isnan(value):
        return "—"
    if percent:
        return f"{value * 100.0:.1f}"
    return f"{value:.2f}"
