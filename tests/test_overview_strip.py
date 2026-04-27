from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation
from rime_ui.widgets.overview_strip import OverviewStrip
from rime_ui.widgets.signals import SignalTrackWidget


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_overview_strip_click_emits_position_selection() -> None:
    _app()
    widget = OverviewStrip()
    widget.resize(400, 52)
    widget.set_duration(10_000.0)
    widget.set_view_range(2_000.0, 4_000.0)
    widget.show()

    positions: list[float] = []
    widget.position_selected.connect(positions.append)

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 24))

    assert positions
    assert 4_500.0 <= positions[-1] <= 5_500.0


def test_overview_strip_dragging_window_emits_view_range_change() -> None:
    _app()
    widget = OverviewStrip()
    widget.resize(400, 52)
    widget.set_duration(10_000.0)
    widget.set_view_range(2_000.0, 4_000.0)
    widget.show()

    ranges: list[tuple[float, float]] = []
    widget.view_range_changed.connect(lambda start, end: ranges.append((start, end)))

    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(118, 24))
    QTest.mouseMove(widget, QPoint(160, 24))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(160, 24))

    assert ranges
    assert ranges[-1][0] > 2_000.0
    assert ranges[-1][1] > 4_000.0


def test_signal_track_widget_no_longer_exposes_range_changed_signal() -> None:
    assert not hasattr(SignalTrackWidget, "range_changed")


def test_overview_strip_filters_out_ghost_annotations() -> None:
    widget = OverviewStrip()
    annotations = [
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=1000.0, end_ms=2000.0),
        Annotation(id="a2", lane="FOG", label="FOG", start_ms=3000.0, end_ms=4000.0, ghost=True),
    ]

    widget.set_annotations(annotations)

    assert [annotation.id for annotation in widget._activity_annotations] == ["a1"]


def test_overview_strip_annotation_alpha_uses_equal_per_annotation_weight() -> None:
    alpha_one = OverviewStrip._annotation_alpha(1)
    alpha_two = OverviewStrip._annotation_alpha(2)
    alpha_many = OverviewStrip._annotation_alpha(30)

    assert alpha_one > alpha_two > alpha_many
    assert alpha_many >= 20
