from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.schema import ProtocolSchema
from rime_ui.timeline import AnnotationLanes, TimelineWidget


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_timeline_routes_focus_to_lanes_for_keyboard_shortcuts() -> None:
    app = _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.show()
    app.processEvents()

    assert timeline.focusProxy() is timeline.lanes
    assert timeline.scroll_area.focusProxy() is timeline.lanes

    store = AnnotationStore()
    store.add(
        Annotation(
            id="a1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=300.0,
        )
    )
    timeline.set_store(store)
    timeline.select_annotation("a1")
    app.processEvents()

    assert timeline.lanes.hasFocus() is True

    timeline.close()


def test_timeline_left_right_move_playhead_when_nothing_is_selected() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.set_duration(10_000.0)
    timeline.set_position(1_000.0)

    emitted: list[float] = []
    timeline.position_clicked.connect(emitted.append)

    timeline.lanes.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    timeline.lanes.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier))

    assert emitted == [1033.0, 703.0]


def test_timeline_left_right_move_playhead_even_when_annotation_is_selected() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.set_duration(10_000.0)
    timeline.set_position(1_000.0)

    store = AnnotationStore()
    store.add(
        Annotation(
            id="a1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=300.0,
        )
    )
    timeline.set_store(store)
    timeline.select_annotation("a1")

    emitted: list[float] = []
    timeline.position_clicked.connect(emitted.append)

    timeline.lanes.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    timeline.lanes.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier))

    assert emitted == [1033.0, 703.0]


def test_timeline_seek_to_preserves_existing_zoom_span() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.set_duration(10_000.0)
    timeline.set_view_range(1_000.0, 3_000.0)

    emitted: list[float] = []
    timeline.position_clicked.connect(emitted.append)

    timeline.seek_to(7_000.0)

    start_ms, end_ms = timeline.get_view_range()
    assert end_ms - start_ms == 2_000.0
    assert start_ms == 6_100.0
    assert end_ms == 8_100.0
    assert emitted == [7_000.0]


def test_timeline_alt_left_right_move_selected_point_annotation() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.set_duration(10_000.0)

    store = AnnotationStore()
    store.add(
        Annotation(
            id="p1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=100.0,
            event_type="point",
        )
    )
    timeline.set_store(store)
    timeline.select_annotation("p1")

    modified: list[tuple[str, float, float]] = []
    timeline.lanes.annotation_modified.connect(
        lambda ann_id, start_ms, end_ms: modified.append((ann_id, start_ms, end_ms))
    )

    timeline.lanes.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.AltModifier,
        )
    )
    timeline.lanes.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier,
        )
    )

    assert modified == [("p1", 110.0, 110.0)]


def test_timeline_alt_left_right_move_selected_snap_point() -> None:
    _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.set_duration(10_000.0)
    timeline.add_snap_point(100.0)
    timeline.lanes._selected_snap_index = 0

    modified_count: list[str] = []
    timeline.lanes.snap_point_modified.connect(lambda: modified_count.append("changed"))

    timeline.lanes.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.AltModifier,
        )
    )
    timeline.lanes.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier,
        )
    )

    assert modified_count == ["changed"]
    assert timeline.lanes._snap_points == [110.0]


def test_timeline_double_click_requests_accept_for_ghost_only() -> None:
    app = _app()
    timeline = TimelineWidget(ProtocolSchema.default())
    timeline.resize(1200, 500)
    timeline.set_duration(10_000.0)

    store = AnnotationStore()
    store.add(
        Annotation(
            id="ghost1",
            lane="Core",
            label="Core",
            start_ms=1_000.0,
            end_ms=2_000.0,
            ghost=True,
        )
    )
    store.add(
        Annotation(
            id="manual1",
            lane="Core",
            label="Core",
            start_ms=3_000.0,
            end_ms=4_000.0,
        )
    )
    timeline.set_store(store)
    timeline.show()
    app.processEvents()

    accepted: list[str] = []
    timeline.ghost_accept_requested.connect(accepted.append)

    level = timeline.lanes._lane_name_to_level("Core")
    assert level is not None
    row_top = timeline.lanes._sub_row_y(level, timeline.lanes._primary_row_source("manual"))

    def bar_center(start_ms: float, end_ms: float) -> tuple[int, int]:
        x = int((timeline.lanes._time_to_x(start_ms) + timeline.lanes._time_to_x(end_ms)) / 2)
        y = int(row_top + 8)
        return x, y

    ghost_x, ghost_y = bar_center(1_000.0, 2_000.0)
    QTest.mouseDClick(timeline.lanes, Qt.MouseButton.LeftButton, pos=QPoint(ghost_x, ghost_y))
    app.processEvents()

    manual_x, manual_y = bar_center(3_000.0, 4_000.0)
    QTest.mouseDClick(timeline.lanes, Qt.MouseButton.LeftButton, pos=QPoint(manual_x, manual_y))
    app.processEvents()

    assert accepted == ["ghost1"]

    timeline.close()


def test_playback_strip_hover_click_and_drag_leave_annotations_unchanged():
    app = _app()
    lanes = AnnotationLanes(ProtocolSchema.default(), single_set=True)
    lanes.native_palette = True
    store = AnnotationStore()
    annotation = Annotation("event", "FOG", "FOG", 1000, 2000)
    store.add(annotation)
    lanes.set_store(store)
    lanes.set_duration(10000)
    lanes.resize(1100, lanes.minimumHeight())
    lanes.show()
    app.processEvents()
    positions, creations, edits = [], [], []
    lanes.position_clicked.connect(positions.append)
    lanes.annotation_created.connect(lambda *args: creations.append(args))
    lanes.annotation_modified.connect(lambda *args: edits.append(args))
    def point(time):
        return QPoint(round(lanes._time_to_x(time)), 8)

    QTest.mouseMove(lanes, point(3000))
    assert not positions
    assert lanes.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert abs(lanes._seek_hover_ms - 3000) < 15
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=point(3000))
    assert abs(positions[-1] - 3000) < 15
    handle = QPoint(round(lanes._time_to_x(positions[-1])), 9)
    QTest.mouseMove(lanes, handle)
    assert lanes.cursor().shape() == Qt.CursorShape.OpenHandCursor
    QTest.mousePress(lanes, Qt.MouseButton.LeftButton, pos=handle)
    QTest.mouseMove(lanes, point(5000))
    assert abs(positions[-1] - 5000) < 15  # Updates before release.
    QTest.mouseRelease(lanes, Qt.MouseButton.LeftButton, pos=point(6000))
    assert abs(positions[-1] - 6000) < 15
    assert not creations and not edits
    assert (annotation.start_ms, annotation.end_ms) == (1000, 2000)
    # The descriptive gutter is not part of the seek target.
    count = len(positions)
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=QPoint(10, 8))
    assert len(positions) == count
    lanes.close()
    lanes.deleteLater()
    app.processEvents()


def test_playback_scrubbing_keeps_loop_and_snap_markers_and_clamps_to_view():
    app = _app()
    lanes = AnnotationLanes(ProtocolSchema.default(), single_set=True)
    lanes.native_palette = True
    lanes.set_schema(lanes.schema)
    lanes.set_duration(10000)
    lanes.set_view_range(2000, 6000)
    lanes.set_loop_region(3000, 5000)
    lanes.add_snap_point(4000)
    lanes.resize(1100, lanes.minimumHeight())
    lanes.show()
    app.processEvents()
    positions = []
    lanes.position_clicked.connect(positions.append)
    # Upper ruler seeks even above a snap marker or loop region.
    QTest.mousePress(lanes, Qt.MouseButton.LeftButton, pos=QPoint(round(lanes._time_to_x(4000)), 8))
    QTest.mouseMove(lanes, QPoint(lanes.width() + 50, 8))
    assert positions[-1] == 6000
    QTest.mouseRelease(lanes, Qt.MouseButton.LeftButton, pos=QPoint(0, 8))
    assert positions[-1] == 2000
    assert lanes.get_loop_region() == (3000, 5000)
    assert lanes.get_snap_points() == [4000]
    # Lower marker band still supports snap-point dragging.
    lanes.clear_loop_region()
    start = QPoint(round(lanes._time_to_x(4000)), lanes._ruler_height - 6)
    end = QPoint(round(lanes._time_to_x(4500)), lanes._ruler_height - 6)
    QTest.mousePress(lanes, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(lanes, end)
    QTest.mouseRelease(lanes, Qt.MouseButton.LeftButton, pos=end)
    assert abs(lanes.get_snap_points()[0] - 4500) < 15
    lanes.close()
    lanes.deleteLater()
    app.processEvents()
