from __future__ import annotations

from rime_core import Annotation, AnnotationStore, CoverageSpec, compute_coverage


def test_compute_coverage_uses_interval_union_across_multiple_specs() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=0.0, end_ms=100.0))
    store.add(Annotation(id="a2", lane="Manifest", label="Trembling", start_ms=50.0, end_ms=150.0))

    result = compute_coverage(
        store,
        [CoverageSpec(lane="FOG"), CoverageSpec(lane="Manifest", label="Trembling")],
        session_duration_ms=300.0,
    )

    assert result.numerator_ms == 150.0
    assert result.numerator_episodes == 1
    assert result.denominator_ms == 300.0
    assert result.denominator_episodes == -1
    assert result.percent == 50.0


def test_compute_coverage_skips_ghost_and_point_annotations() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=0.0, end_ms=100.0, ghost=True))
    store.add(
        Annotation(
            id="a2",
            lane="FOG",
            label="FOG",
            start_ms=200.0,
            end_ms=200.0,
            event_type="point",
        )
    )
    store.add(Annotation(id="a3", lane="FOG", label="FOG", start_ms=300.0, end_ms=450.0))

    result = compute_coverage(store, [CoverageSpec(lane="FOG")], session_duration_ms=1000.0)

    assert result.numerator_ms == 150.0
    assert result.numerator_episodes == 1
    assert result.percent == 15.0


def test_compute_coverage_lane_denominator_uses_union() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=200.0))
    store.add(Annotation(id="a2", lane="Tasks", label="Walk", start_ms=0.0, end_ms=120.0))
    store.add(Annotation(id="a3", lane="Tasks", label="Walk", start_ms=100.0, end_ms=300.0))

    result = compute_coverage(
        store,
        [CoverageSpec(lane="FOG")],
        denominator=[CoverageSpec(lane="Tasks", label="Walk")],
        session_duration_ms=1000.0,
    )

    assert result.numerator_ms == 100.0
    assert result.denominator_ms == 300.0
    assert result.denominator_episodes == 1
    assert result.percent == (100.0 / 300.0) * 100.0
