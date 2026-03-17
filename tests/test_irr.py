from __future__ import annotations

import pytest

from rime_core import Annotation, AnnotationStore, compute_irr


def _store(*annotations: Annotation) -> AnnotationStore:
    store = AnnotationStore()
    for annotation in annotations:
        store.add(annotation)
    return store


def test_compute_irr_reports_perfect_agreement_for_identical_intervals() -> None:
    store_a = _store(
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0),
    )
    store_b = _store(
        Annotation(id="b1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0),
    )

    result = compute_irr(store_a, store_b, 1000.0, lane="FOG", frame_resolution_ms=100.0)

    assert result.cohens_kappa == pytest.approx(1.0)
    assert result.percent_agreement == pytest.approx(1.0)
    assert result.frame_iou == pytest.approx(1.0)
    assert len(result.matched_episodes) == 1
    assert not result.unmatched_a
    assert not result.unmatched_b
    assert result.per_label["FOG"].matched == 1
    assert result.per_label["FOG"].episode_iou == pytest.approx(1.0)


def test_compute_irr_tracks_unmatched_annotations_and_label_breakdown() -> None:
    store_a = _store(
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0),
        Annotation(id="a2", lane="FOG", label="FOG", start_ms=500.0, end_ms=700.0),
    )
    store_b = _store(
        Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0),
    )

    result = compute_irr(store_a, store_b, 1000.0, lane="FOG", frame_resolution_ms=100.0)

    assert len(result.matched_episodes) == 1
    assert [annotation.id for annotation in result.unmatched_a] == ["a2"]
    assert not result.unmatched_b
    assert result.frame_iou == pytest.approx(0.8)
    assert result.per_label["FOG"].matched == 1
    assert result.per_label["FOG"].unmatched_a == 1
    assert result.per_label["FOG"].unmatched_b == 0


def test_compute_irr_excludes_ghost_annotations() -> None:
    store_a = _store(
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, ghost=True),
    )
    store_b = _store()

    result = compute_irr(store_a, store_b, 1000.0, lane="FOG")

    assert result.matched_episodes == []
    assert result.unmatched_a == []
    assert result.unmatched_b == []
    assert result.per_label == {}


def test_compute_irr_uses_lane_and_label_for_all_lane_matching() -> None:
    store_a = _store(
        Annotation(id="a1", lane="Tasks", label="Walk", start_ms=0.0, end_ms=500.0),
    )
    store_b = _store(
        Annotation(id="b1", lane="FOG", label="Walk", start_ms=0.0, end_ms=500.0),
    )

    result = compute_irr(store_a, store_b, 1000.0, lane=None, frame_resolution_ms=100.0)

    assert result.matched_episodes == []
    assert [annotation.id for annotation in result.unmatched_a] == ["a1"]
    assert [annotation.id for annotation in result.unmatched_b] == ["b1"]


def test_compute_irr_can_filter_each_session_by_source() -> None:
    store_a = _store(
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"),
        Annotation(id="a2", lane="FOG", label="FOG", start_ms=500.0, end_ms=700.0, source="model:demo"),
    )
    store_b = _store(
        Annotation(id="b1", lane="FOG", label="FOG", start_ms=110.0, end_ms=290.0, source="manual"),
        Annotation(id="b2", lane="FOG", label="FOG", start_ms=520.0, end_ms=680.0, source="model:demo"),
    )

    result = compute_irr(
        store_a,
        store_b,
        1000.0,
        lane="FOG",
        source_a="manual",
        source_b="manual",
        frame_resolution_ms=100.0,
    )

    assert len(result.matched_episodes) == 1
    assert not result.unmatched_a
    assert not result.unmatched_b
