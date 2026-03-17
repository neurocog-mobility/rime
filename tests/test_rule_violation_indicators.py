from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.rule_engine import RuleEngine
from rime_core.schema import ProtocolSchema
from rime_ui.main_window import RimeMainWindow
from rime_ui.timeline import TimelineWidget
from rime_ui.timeline import annotation_indicator_symbols


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_annotation_indicator_symbols_cover_ghost_and_violation_states() -> None:
    assert annotation_indicator_symbols() == ()
    assert annotation_indicator_symbols(ghost=True) == ("?",)
    assert annotation_indicator_symbols(violating=True) == ("!",)
    assert annotation_indicator_symbols(ghost=True, violating=True) == ("?", "!")


def test_main_window_computes_persistent_violation_ids_from_live_store() -> None:
    _app()
    window = RimeMainWindow()
    store = AnnotationStore()
    store.add(Annotation(id="c1", lane="Core", label="Core", start_ms=100.0, end_ms=400.0))

    window.annotations = store
    window.context = SimpleNamespace(rule_engine=RuleEngine(ProtocolSchema.default()))

    violation_ids = window._compute_rule_violation_ids()

    assert violation_ids == {"c1"}

    store.add(
        Annotation(
            id="m1",
            lane="Manifestations",
            label="Akinetic",
            start_ms=500.0,
            end_ms=600.0,
        )
    )

    violation_ids = window._compute_rule_violation_ids()

    assert violation_ids == {"c1", "m1"}

    window.close()


def test_status_badges_do_not_change_interval_fill_color() -> None:
    _app()
    schema = ProtocolSchema.default()

    def render_midpoint_color(*, lane: str, label: str, ghost: bool, violating: bool) -> tuple[int, int, int, int]:
        timeline = TimelineWidget(schema)
        timeline.resize(1200, 500)

        store = AnnotationStore()
        store.add(
            Annotation(
                id="c1",
                lane=lane,
                label=label,
                start_ms=1000.0,
                end_ms=4000.0,
                ghost=ghost,
            )
        )
        timeline.set_store(store)
        timeline.set_duration(6_000.0)
        timeline.set_position(0.0)
        timeline.set_violation_ids({"c1"} if violating else set())
        timeline.show()

        image = QImage(timeline.lanes.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            timeline.lanes.render(painter, QPoint(0, 0))
        finally:
            painter.end()

        level = timeline.lanes._lane_name_to_level(lane)
        assert level is not None
        row_top = timeline.lanes._sub_row_y(level, timeline.lanes._primary_row_source("manual"))
        x = int((timeline.lanes._time_to_x(1000.0) + timeline.lanes._time_to_x(4000.0)) / 2)
        y = int(row_top + 8)
        color = image.pixelColor(x, y)
        timeline.close()
        return color.red(), color.green(), color.blue(), color.alpha()

    for lane, label in (("Tasks", "Walk"), ("FOG", "FOG"), ("Core", "Core")):
        plain = render_midpoint_color(lane=lane, label=label, ghost=False, violating=False)
        ghost_only = render_midpoint_color(lane=lane, label=label, ghost=True, violating=False)
        violation_only = render_midpoint_color(lane=lane, label=label, ghost=False, violating=True)
        both = render_midpoint_color(lane=lane, label=label, ghost=True, violating=True)

        assert violation_only == plain
        assert ghost_only != plain
        assert both == ghost_only


def test_interval_selection_does_not_change_fill_color() -> None:
    _app()
    schema = ProtocolSchema.default()

    def midpoint_color(*, lane: str, label: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        timeline = TimelineWidget(schema)
        timeline.resize(1200, 500)

        store = AnnotationStore()
        store.add(
            Annotation(
                id="ann1",
                lane=lane,
                label=label,
                start_ms=1000.0,
                end_ms=4000.0,
            )
        )
        timeline.set_store(store)
        timeline.set_duration(6_000.0)
        timeline.set_position(0.0)
        timeline.show()

        def render() -> tuple[int, int, int, int]:
            image = QImage(timeline.lanes.size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            try:
                timeline.lanes.render(painter, QPoint(0, 0))
            finally:
                painter.end()

            level = timeline.lanes._lane_name_to_level(lane)
            assert level is not None
            row_top = timeline.lanes._sub_row_y(level, timeline.lanes._primary_row_source("manual"))
            x = int((timeline.lanes._time_to_x(1000.0) + timeline.lanes._time_to_x(4000.0)) / 2)
            y = int(row_top + 8)
            color = image.pixelColor(x, y)
            return color.red(), color.green(), color.blue(), color.alpha()

        plain = render()
        timeline.select_annotation("ann1")
        selected = render()
        timeline.close()
        return plain, selected

    for lane, label in (("Tasks", "Walk"), ("FOG", "FOG"), ("Core", "Core")):
        plain, selected = midpoint_color(lane=lane, label=label)
        assert selected == plain


def test_selected_interval_fill_does_not_inherit_previous_badge_brush() -> None:
    _app()
    schema = ProtocolSchema.default()
    timeline = TimelineWidget(schema)
    timeline.resize(1200, 500)

    store = AnnotationStore()
    store.add(
        Annotation(
            id="ghost-core",
            lane="Core",
            label="Core",
            start_ms=1000.0,
            end_ms=2000.0,
            ghost=True,
        )
    )
    store.add(
        Annotation(
            id="fog-selected",
            lane="FOG",
            label="FOG",
            start_ms=3000.0,
            end_ms=4500.0,
        )
    )
    timeline.set_store(store)
    timeline.set_duration(6_000.0)
    timeline.set_position(0.0)
    timeline.show()

    def render_color(selected: bool) -> tuple[int, int, int, int]:
        if selected:
            timeline.select_annotation("fog-selected")
        else:
            timeline.clear_selection()

        image = QImage(timeline.lanes.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            timeline.lanes.render(painter, QPoint(0, 0))
        finally:
            painter.end()

        level = timeline.lanes._lane_name_to_level("FOG")
        assert level is not None
        row_top = timeline.lanes._sub_row_y(level, timeline.lanes._primary_row_source("manual"))
        x = int((timeline.lanes._time_to_x(3000.0) + timeline.lanes._time_to_x(4500.0)) / 2)
        y = int(row_top + 8)
        color = image.pixelColor(x, y)
        return color.red(), color.green(), color.blue(), color.alpha()

    plain = render_color(selected=False)
    selected = render_color(selected=True)

    assert selected == plain

    timeline.close()
