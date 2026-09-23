from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation
from rime_ui.presentation.overview import OverviewStrip
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


def test_embedded_zoom_handles_pan_seek_and_fit():
    app = _app()
    widget = OverviewStrip(embedded=True)
    widget.resize(800, 20)
    widget.set_duration(10000)
    widget.set_view_range(0, 10000)
    widget.show()
    app.processEvents()
    positions = []
    widget.position_selected.connect(positions.append)

    def point(time):
        return QPoint(round(widget._time_to_x(time, widget._strip_rect())), 10)

    def drag(start, end):
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=point(start))
        QTest.mouseMove(widget, point(end))
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=point(end))

    # At zero the zoom edge, not the overlapping playhead, owns the handle.
    drag(0, 2000)
    start, end = widget.get_view_range()
    assert abs(start - 2000) < 20 and end == 10000
    assert not positions
    drag(10000, 6000)
    start, end = widget.get_view_range()
    assert abs(start - 2000) < 20 and abs(end - 6000) < 20
    span = end - start
    drag(4000, 5000)
    start, end = widget.get_view_range()
    assert abs(start - 3000) < 30 and abs((end - start) - span) < 1
    # Resizing past either recording boundary keeps the other edge fixed.
    drag(start, -2000)
    assert widget.get_view_range()[0] == 0
    assert abs(widget.get_view_range()[1] - end) < 1
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=point(9000))
    assert abs(positions[-1] - 9000) < 20
    assert widget.get_view_range()[0] <= positions[-1] <= widget.get_view_range()[1]
    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=point(5000))
    assert widget.get_view_range() == (0, 10000)
    widget.close()
    widget.deleteLater()
    app.processEvents()
