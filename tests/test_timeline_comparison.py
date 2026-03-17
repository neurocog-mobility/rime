from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.schema import ProtocolSchema
from rime_ui.timeline import COMPARISON_SOURCE, SESSION_A_SOURCE, TimelineWidget


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_timeline_tracks_comparison_store_and_lane_differences() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    primary = AnnotationStore()
    primary.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"))
    comparison = AnnotationStore()
    comparison.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0, source="manual"))

    timeline.set_store(primary)
    timeline.set_comparison_store(comparison)
    timeline.set_comparison_filters("FOG", "manual", "manual")
    timeline.set_show_comparison(True)

    assert timeline.lanes._comparison_store is comparison
    assert timeline.lanes._lane_has_comparison_diff("FOG") is True

    timeline.set_show_comparison(False)

    assert timeline.lanes._lane_has_comparison_diff("FOG") is False


def test_timeline_adds_dedicated_comparison_source_row() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    primary = AnnotationStore()
    primary.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"))
    comparison = AnnotationStore()
    comparison.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0, source="manual"))

    timeline.set_store(primary)
    timeline.set_comparison_store(comparison)
    timeline.set_comparison_filters("FOG", "manual", "manual")
    timeline.set_show_comparison(True)

    level = timeline.lanes._lane_name_to_level("FOG")
    assert level is not None
    assert timeline.lanes._lane_sources(level) == ["__session_a__", "__comparison__"]
    assert "__comparison__" in timeline.lanes._lane_sources(level)


def test_timeline_comparison_respects_source_filters() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    primary = AnnotationStore()
    primary.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"))
    primary.add(Annotation(id="a2", lane="FOG", label="FOG", start_ms=500.0, end_ms=700.0, source="model:demo"))
    comparison = AnnotationStore()
    comparison.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0, source="manual"))
    comparison.add(Annotation(id="b2", lane="FOG", label="FOG", start_ms=520.0, end_ms=680.0, source="model:demo"))

    timeline.set_store(primary)
    timeline.set_comparison_store(comparison)
    timeline.set_comparison_filters("FOG", "manual", "manual")
    timeline.set_show_comparison(True)

    filtered_primary = timeline.lanes._comparison_annotations(
        timeline.lanes._store,
        "FOG",
        source=timeline.lanes._primary_source_filter,
    )
    filtered_comparison = timeline.lanes._comparison_annotations(
        timeline.lanes._comparison_store,
        "FOG",
        source=timeline.lanes._comparison_source_filter,
    )

    assert [annotation.id for annotation in filtered_primary] == ["a1"]
    assert [annotation.id for annotation in filtered_comparison] == ["b1"]


def test_timeline_tracks_matched_and_unmatched_ids_for_compare_styling() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.set_comparison_store(AnnotationStore())
    timeline.set_show_comparison(True)
    timeline.set_comparison_match_state(
        matched_primary_ids={"a1"},
        matched_comparison_ids={"b1"},
        unmatched_primary_ids={"a2"},
        unmatched_comparison_ids={"b2"},
    )

    assert timeline.lanes._annotation_translucent("a1", comparison=False) is False
    assert timeline.lanes._annotation_translucent("a2", comparison=False) is True
    assert timeline.lanes._annotation_translucent("b1", comparison=True) is False
    assert timeline.lanes._annotation_translucent("b2", comparison=True) is True


def test_timeline_set_loop_region_emits_signal() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    emitted: list[tuple[float, float]] = []
    timeline.loop_region_changed.connect(lambda start, end: emitted.append((start, end)))

    timeline.set_duration(10_000.0)
    start, end = timeline.set_loop_region(1000.0, 2500.0)

    assert emitted == [(start, end)]


def test_timeline_shows_source_labels_for_both_compare_rows() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    primary = AnnotationStore()
    primary.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"))
    comparison = AnnotationStore()
    comparison.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0, source="model:demo"))

    timeline.set_store(primary)
    timeline.set_comparison_store(comparison)
    timeline.set_comparison_filters("FOG", "manual", "model:demo")
    timeline.set_show_comparison(True)

    assert timeline.lanes._show_source_label(0) is True
    assert timeline.lanes._show_source_label(1) is True
    assert timeline.lanes._source_short_label(SESSION_A_SOURCE) == "A"
    assert timeline.lanes._source_short_label(COMPARISON_SOURCE) == "B"


def test_timeline_resolves_source_row_from_y_position() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"))
    store.add(Annotation(id="a2", lane="FOG", label="FOG", start_ms=500.0, end_ms=700.0, source="model:demo"))

    timeline.set_store(store)
    timeline.resize(1200, 500)

    level = timeline.lanes._lane_name_to_level("FOG")
    assert level is not None
    lane_y = timeline.lanes._lane_y(level)

    assert timeline.lanes._source_at_y(level, lane_y + 5) == "manual"
    assert timeline.lanes._source_at_y(level, lane_y + 29) == "model:demo"


def test_signal_overlays_follow_active_lane_source() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"))
    store.add(Annotation(id="a2", lane="FOG", label="FOG", start_ms=500.0, end_ms=700.0, source="model:demo"))

    timeline.set_store(store)
    timeline.set_active_overlay_target("FOG", "manual")

    assert set(timeline.signals._overlay_data) == {"a1"}

    timeline.set_active_overlay_target("FOG", "model:demo")

    assert set(timeline.signals._overlay_data) == {"a2"}
