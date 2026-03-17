"""Inter-rater reliability helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import isnan

from rime_core.annotations import Annotation, AnnotationStore


@dataclass(frozen=True)
class IRRLabelResult:
    """Agreement metrics for one label."""

    label: str
    cohens_kappa: float
    percent_agreement: float
    episode_iou: float
    matched: int
    unmatched_a: int
    unmatched_b: int


@dataclass(frozen=True)
class IRRResult:
    """Aggregate IRR result for one lane selection."""

    cohens_kappa: float
    frame_iou: float
    percent_agreement: float
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
    matched_ious = [_annotation_iou(a, b) for a, b in matched]
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
        label_ious = [_annotation_iou(a, b) for a, b in label_matched]
        per_label[label] = IRRLabelResult(
            label=label,
            cohens_kappa=_cohens_kappa(label_states_a, label_states_b),
            percent_agreement=_percent_agreement(label_states_a, label_states_b),
            episode_iou=float("nan") if not label_ious else sum(label_ious) / len(label_ious),
            matched=len(label_matched),
            unmatched_a=len(label_unmatched_a),
            unmatched_b=len(label_unmatched_b),
        )

    return IRRResult(
        cohens_kappa=_cohens_kappa(states_a, states_b),
        frame_iou=float("nan") if not matched_ious else sum(matched_ious) / len(matched_ious),
        percent_agreement=_percent_agreement(states_a, states_b),
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
            iou = _annotation_iou(annotation_a, annotation_b)
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


def _annotation_iou(annotation_a: Annotation, annotation_b: Annotation) -> float:
    start = max(annotation_a.start_ms, annotation_b.start_ms)
    end = min(annotation_a.end_ms, annotation_b.end_ms)
    intersection = max(0.0, end - start)
    union_start = min(annotation_a.start_ms, annotation_b.start_ms)
    union_end = max(annotation_a.end_ms, annotation_b.end_ms)
    union = max(0.0, union_end - union_start)
    if union == 0.0:
        return 1.0 if annotation_a.start_ms == annotation_b.start_ms else 0.0
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
