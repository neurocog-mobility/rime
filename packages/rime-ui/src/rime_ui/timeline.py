"""Timeline widget for RIME annotation display and creation."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygon, QWheelEvent
from PySide6.QtWidgets import QScrollArea, QSplitter, QToolTip, QVBoxLayout, QWidget

from rime_core.annotations import AnnotationStore
from rime_core.schema import ProtocolSchema
from rime_ui.schema_view import SchemaView
from rime_ui.signals import SignalTrackWidget
from rime_ui.shortcuts import (
    ADD_SNAP_POINT,
    CLEAR_SELECTION,
    event_matches_shortcut,
    resolve_shortcuts,
)
from rime_ui.theme import (
    COLOR_ACCENT_MUTED,
    COLOR_ANCHOR,
    COLOR_BORDER,
    COLOR_COMPARISON,
    COLOR_CONFIDENCE_ERROR,
    COLOR_CONFIDENCE_WARN,
    COLOR_LOOP_ACCENT,
    COLOR_LOOP_BORDER,
    COLOR_PENDING,
    COLOR_TEXT,
    COLOR_TEXT_EMPHASIS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_STRONG,
    COLOR_TEXT_SUBTLE,
    COLOR_TIMELINE_ROW_BG,
    COLOR_TRIM_EDGE,
    COLOR_VIDEO_BG,
    COLOR_WINDOW_ALT_BG,
    COLOR_WINDOW_BG,
)


RULER_HEIGHT = 24
SUB_ROW_HEIGHT = 24
LANE_MIN_HEIGHT = SUB_ROW_HEIGHT
HEADER_HEIGHT = 20  # Slimmer headers
LABEL_WIDTH_MIN = 80
LABEL_WIDTH_MAX = 160
SNAP_THRESHOLD_MS = 500  # Snap within 500ms
SNAP_HIT_RADIUS = 8  # Pixel radius for clicking snap points
POINT_HIT_RADIUS = 6
LOOP_EDGE_HIT_RADIUS = 8
LOOP_MIN_SPAN_MS = 100
SESSION_A_SOURCE = "__session_a__"
COMPARISON_SOURCE = "__comparison__"


def annotation_indicator_symbols(*, ghost: bool = False, violating: bool = False) -> tuple[str, ...]:
    """Return the status badge symbols shown alongside annotation labels."""
    symbols: list[str] = []
    if ghost:
        symbols.append("?")
    if violating:
        symbols.append("!")
    return tuple(symbols)


class AnnotationLanes(QWidget):
    """
    Widget responsible for drawing annotation swimlanes and handling interaction.
    """

    # Signals
    position_clicked = Signal(float)  # time_ms
    annotation_created = Signal(int, float, float)  # (level, start_ms, end_ms)
    annotation_selected = Signal(str)  # annotation_id
    ghost_accept_requested = Signal(str)  # annotation_id
    annotation_deleted = Signal(str)  # annotation_id
    annotation_modified = Signal(str, float, float)  # id, start_ms, end_ms
    snap_point_added = Signal(float)  # time_ms
    snap_point_removed = Signal(float)  # time_ms
    snap_point_modified = Signal()  # Emit to trigger full refresh of signal lines
    view_range_changed = Signal(float, float)  # start_ms, end_ms (for sync)
    selection_changed = Signal(bool, bool)  # has_annotation, has_snap
    loop_region_changed = Signal(float, float)  # start_ms, end_ms

    # Internal signals for hovering (to update overlays)
    annotation_hovered = Signal(str)  # annotation_id
    annotation_unhovered = Signal(str)  # annotation_id

    # Signal for overlay lane selection
    overlay_level_changed = Signal(int, object)  # level, source
    lane_header_context_requested = Signal(str, object, object)

    def __init__(self, schema: ProtocolSchema, parent=None) -> None:
        super().__init__(parent)

        self.config = SchemaView(schema)

        # Group state
        self._group_state: dict[str, bool] = {}  # name -> collapsed
        self._init_group_state()

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # State
        self._duration_ms: float = 60000  # Default 1 minute
        self._current_position_ms: float = 0
        self._store: AnnotationStore | None = None
        self._comparison_store: AnnotationStore | None = None
        self._show_comparison = True
        self._comparison_lane_filter: str | None = None
        self._primary_source_filter: str | None = None
        self._comparison_source_filter: str | None = None
        self._matched_primary_ids: set[str] = set()
        self._matched_comparison_ids: set[str] = set()
        self._unmatched_primary_ids: set[str] = set()
        self._unmatched_comparison_ids: set[str] = set()
        self._violating_annotation_ids: set[str] = set()
        self._selected_id: str | None = None
        self._active_overlay_level: int = 1  # Default to level 1
        self._active_overlay_source: str = "manual"

        # View state (for zooming/panning)
        self._view_start_ms: float = 0
        self._view_end_ms: float = 60000

        # Snap points
        self._snap_points: list[float] = []  # times in ms
        self._snap_threshold_ms: float = SNAP_THRESHOLD_MS
        self._selected_snap_index: int | None = None

        self._last_hovered_id: str | None = None

        # Drag state
        self._is_dragging = False
        self._drag_lane: int | None = None
        self._drag_start_x: float = 0
        self._drag_end_x: float = 0

        self._is_dragging_snap = False
        self._drag_snap_index: int | None = None

        self._drag_ann_id: str | None = None
        self._drag_edge: str | None = None  # "start" or "end"
        self._is_panning = False
        self._pan_last_x = 0.0
        self._loop_start_ms: float | None = None
        self._loop_end_ms: float | None = None
        self._loop_drag_mode: str | None = None  # "start" | "end" | "move"
        self._loop_drag_anchor_ms: float = 0.0
        self._loop_drag_initial_start_ms: float = 0.0
        self._loop_drag_initial_end_ms: float = 0.0

        self._shortcuts = resolve_shortcuts()
        self._keys_pressed: set[int] = set()
        self._label_width = LABEL_WIDTH_MIN

        self._update_label_width()
        self._recalculate_height()

    def set_schema(self, schema: ProtocolSchema) -> None:
        self.config.set_schema(schema)
        self._group_state.clear()
        self._init_group_state()
        self._update_label_width()
        self._recalculate_height()

    def _update_label_width(self) -> None:
        metrics = self.fontMetrics()
        widest_label = max(
            (metrics.horizontalAdvance(str(lane["name"])) for lane in self.config.lanes),
            default=0,
        )
        padded_width = widest_label + 36
        self._label_width = max(LABEL_WIDTH_MIN, min(LABEL_WIDTH_MAX, padded_width))

    def _init_group_state(self) -> None:
        """Initialize group collapsed state from config."""
        for group in self.config.groups:
            self._group_state[group["name"]] = group.get("collapsed", False)

    def _recalculate_height(self) -> None:
        """Calculate and set the required height based on visible lanes."""
        total_height = RULER_HEIGHT + 20  # Buffer

        for item in self._display_items():
            if item["kind"] == "group_header":
                total_height += HEADER_HEIGHT
            else:
                total_height += self._lane_total_height(item["lane"]["level"])

        self.setMinimumHeight(total_height)
        self.update()

    def set_store(self, store: AnnotationStore) -> None:
        """Set the annotation store for rendering."""
        self._store = store
        self._selected_id = None
        self._selected_snap_index = None
        self._ensure_active_overlay_target()
        self._emit_selection_state()
        self.update()

    def set_comparison_store(self, store: AnnotationStore | None) -> None:
        """Set an optional read-only comparison store for overlay rendering."""
        self._comparison_store = store
        self._ensure_active_overlay_target()
        self.update()

    def set_show_comparison(self, visible: bool) -> None:
        """Toggle visibility of comparison annotations."""
        self._show_comparison = visible
        self._ensure_active_overlay_target()
        self.update()

    def set_comparison_filters(
        self,
        lane: str | None,
        primary_source: str | None,
        comparison_source: str | None,
    ) -> None:
        """Set the active lane/source filters for comparison mode."""
        self._comparison_lane_filter = lane
        self._primary_source_filter = primary_source
        self._comparison_source_filter = comparison_source
        self._ensure_active_overlay_target()
        self.update()

    def set_comparison_match_state(
        self,
        *,
        matched_primary_ids: set[str] | None = None,
        matched_comparison_ids: set[str] | None = None,
        unmatched_primary_ids: set[str] | None = None,
        unmatched_comparison_ids: set[str] | None = None,
    ) -> None:
        """Set match-state styling for comparison-mode annotations."""
        self._matched_primary_ids = set(matched_primary_ids or set())
        self._matched_comparison_ids = set(matched_comparison_ids or set())
        self._unmatched_primary_ids = set(unmatched_primary_ids or set())
        self._unmatched_comparison_ids = set(unmatched_comparison_ids or set())
        self.update()

    def set_violation_ids(self, annotation_ids: set[str] | None = None) -> None:
        """Set the annotations that should display a persistent rule violation marker."""
        self._violating_annotation_ids = set(annotation_ids or set())
        self.update()

    def set_duration(self, duration_ms: float) -> None:
        """Set the total duration of the timeline."""
        self._duration_ms = max(1, duration_ms)
        self._view_start_ms = max(0.0, min(self._view_start_ms, self._duration_ms))
        self._view_end_ms = max(self._view_start_ms + 1, min(self._view_end_ms, self._duration_ms))
        if self.has_loop_region():
            start, end = self._normalized_loop_bounds(
                self._loop_start_ms or 0.0,
                self._loop_end_ms or self._duration_ms,
            )
            self._loop_start_ms = start
            self._loop_end_ms = end
        self.update()

    def set_position(self, position_ms: float) -> None:
        """Set the current playback position."""
        self._current_position_ms = position_ms
        self.update()

    def get_selected_id(self) -> str | None:
        """Get the currently selected annotation ID."""
        return self._selected_id

    def get_selected_snap_index(self) -> int | None:
        return self._selected_snap_index

    def clear_selection(self) -> None:
        """Clear the current selection."""
        self._selected_id = None
        self._selected_snap_index = None
        QToolTip.hideText()
        self._emit_selection_state()
        self.update()

    def select_annotation(self, ann_id: str) -> bool:
        """Select an annotation by id if present in the current store."""
        if not self._store or ann_id not in self._store.annotations:
            return False
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._selected_id = ann_id
        self._selected_snap_index = None
        self.annotation_selected.emit(ann_id)
        self._emit_selection_state()
        self.update()
        return True

    def zoom_to_fit(self) -> None:
        self.set_view_range(0, self._duration_ms)

    def seek_to(self, time_ms: float, context_ms: float = 3000.0) -> None:
        """Move the playhead to a time and pan only when it falls outside the current view."""
        del context_ms
        span = max(1.0, self._view_end_ms - self._view_start_ms)
        target_offset_ms = span * 0.45
        start = self._view_start_ms
        end = self._view_end_ms

        if time_ms < start:
            start = max(0.0, min(time_ms - target_offset_ms, self._duration_ms - span))
            end = start + span
        elif time_ms > end:
            start = max(0.0, min(time_ms - target_offset_ms, self._duration_ms - span))
            end = start + span

        self.set_view_range(start, min(self._duration_ms, end))
        self._current_position_ms = time_ms
        self.position_clicked.emit(time_ms)
        self.update()

    def set_loop_region(self, start_ms: float, end_ms: float) -> tuple[float, float]:
        start, end = self._normalized_loop_bounds(start_ms, end_ms)
        self._loop_start_ms = start
        self._loop_end_ms = end
        self.update()
        return start, end

    def get_loop_region(self) -> tuple[float, float] | None:
        if self._loop_start_ms is None or self._loop_end_ms is None:
            return None
        return self._loop_start_ms, self._loop_end_ms

    def has_loop_region(self) -> bool:
        return self.get_loop_region() is not None

    def clear_loop_region(self) -> None:
        self._loop_start_ms = None
        self._loop_end_ms = None
        self._loop_drag_mode = None
        self.update()

    def _emit_selection_state(self) -> None:
        self.selection_changed.emit(self._selected_id is not None, self._selected_snap_index is not None)

    def _normalized_loop_bounds(self, start_ms: float, end_ms: float) -> tuple[float, float]:
        start = float(min(start_ms, end_ms))
        end = float(max(start_ms, end_ms))
        start = max(0.0, min(start, self._duration_ms))
        end = max(0.0, min(end, self._duration_ms))
        if end - start < LOOP_MIN_SPAN_MS:
            end = min(self._duration_ms, start + LOOP_MIN_SPAN_MS)
            if end - start < LOOP_MIN_SPAN_MS:
                start = max(0.0, end - LOOP_MIN_SPAN_MS)
        return start, end

    # --- Snap point methods ---

    def add_snap_point(self, time_ms: float) -> None:
        """Add a snap point at the given time."""
        # Avoid duplicates (within 50ms)
        for existing in self._snap_points:
            if abs(existing - time_ms) < 50:
                return
        self._snap_points.append(time_ms)
        self._snap_points.sort()
        self.snap_point_added.emit(time_ms)
        self.update()

    def remove_snap_point(self, index: int) -> None:
        """Remove snap point at index."""
        if 0 <= index < len(self._snap_points):
            time_ms = self._snap_points.pop(index)
            self._selected_snap_index = None
            self.snap_point_removed.emit(time_ms)
            self._emit_selection_state()
            self.update()

    def clear_all_snap_points(self) -> None:
        """Remove all snap points."""
        self._snap_points.clear()
        self._selected_snap_index = None
        self._emit_selection_state()
        self.update()

    def get_snap_points(self) -> list[float]:
        """Get list of snap point times."""
        return self._snap_points.copy()

    def set_snap_points(self, snap_points: list[float]) -> None:
        self._snap_points = sorted({float(value) for value in snap_points})
        self._selected_snap_index = None
        self._emit_selection_state()
        self.snap_point_modified.emit()
        self.update()

    def _get_level_for_label(self, label: str) -> int:
        """Find the lane level for a given label from config."""
        for lane in self.config.lanes:
            if label in lane["labels"]:
                return lane["level"]
        return 0  # Not found

    def _lane_name_to_level(self, lane_name: str) -> int | None:
        """Resolve lane name to configured level."""
        lane = self.config.get_lane_by_name(lane_name)
        return lane["level"] if lane else None

    def _level_to_lane_name(self, level: int) -> str | None:
        lane = self.config.get_lane_config(level)
        return str(lane["name"]) if lane else None

    def _ensure_active_overlay_target(self) -> None:
        visible_levels = [
            item["lane"]["level"]
            for item in self._display_items()
            if item["kind"] == "lane"
        ]
        if not visible_levels:
            self._active_overlay_level = 1
            self._active_overlay_source = "manual"
            return
        if self._active_overlay_level not in visible_levels:
            self._active_overlay_level = visible_levels[0]
        sources = self._lane_sources(self._active_overlay_level)
        if not sources:
            self._active_overlay_source = "manual"
        elif self._active_overlay_source not in sources:
            self._active_overlay_source = sources[0]

    def set_active_overlay_target(self, level: int, source: str) -> None:
        self._active_overlay_level = level
        self._active_overlay_source = source
        self._ensure_active_overlay_target()
        self.overlay_level_changed.emit(self._active_overlay_level, self._active_overlay_source)
        self.update()

    def _source_at_y(self, level: int, y: float) -> str | None:
        lane_y = self._lane_y(level)
        if lane_y < 0:
            return None
        row_index = int((y - lane_y) // SUB_ROW_HEIGHT)
        sources = self._lane_sources(level)
        if not sources:
            return None
        row_index = max(0, min(row_index, len(sources) - 1))
        return sources[row_index]

    def _lane_sources(self, level: int) -> list[str]:
        """Ordered unique sources in this lane: manual first, remainder alphabetical."""
        if self._comparison_mode_active():
            return [SESSION_A_SOURCE, COMPARISON_SOURCE]

        if not self._store:
            sources = ["manual"]
        else:
            sources = {
                ann.source or "manual"
                for ann in self._store.annotations.values()
                if self._lane_name_to_level(ann.lane) == level
            }
            sources.discard("manual")
            sources = ["manual"] + sorted(sources)

        if (
            self._show_comparison
            and self._comparison_store is not None
            and any(self._lane_name_to_level(ann.lane) == level for ann in self._comparison_store.annotations.values())
        ):
            sources.append(COMPARISON_SOURCE)
        return sources

    def _lane_total_height(self, level: int) -> int:
        return max(LANE_MIN_HEIGHT, len(self._lane_sources(level)) * SUB_ROW_HEIGHT)

    def _sub_row_y(self, level: int, source: str) -> int:
        lane_y = self._lane_y(level)
        if lane_y < RULER_HEIGHT:
            return lane_y
        sources = self._lane_sources(level)
        source_name = source or "manual"
        row_index = sources.index(source_name) if source_name in sources else len(sources) - 1
        return lane_y + row_index * SUB_ROW_HEIGHT

    def _source_short_label(self, source: str) -> str:
        if source == SESSION_A_SOURCE:
            return "A"
        if source == "manual":
            return "manual"
        if source == COMPARISON_SOURCE:
            return "B"
        if source.startswith("model:"):
            return source[len("model:") :]
        if source.startswith("rater:"):
            return source[len("rater:") :]
        return source

    @staticmethod
    def _display_source_name(source: str | None) -> str:
        if not source:
            return "all"
        if source == "manual":
            return "manual"
        if source.startswith("model:"):
            return source[len("model:") :]
        if source.startswith("rater:"):
            return source[len("rater:") :]
        return source

    def _show_source_label(self, row_index: int) -> bool:
        if self._comparison_mode_active():
            return True
        return row_index > 0

    def _display_items(self) -> list[dict]:
        items: list[dict] = []
        grouped_lanes = set()
        for group in self.config.groups:
            grouped_lanes.update(group["lanes"])

        for lane in self.config.lanes:
            if lane["level"] in grouped_lanes:
                continue
            if not self._should_show_lane(lane["name"]):
                continue
            items.append({"kind": "lane", "lane": lane, "is_child": False})

        for group in self.config.groups:
            child_items = []
            for level in group["lanes"]:
                lane = self.config.get_lane_config(level)
                if lane and self._should_show_lane(lane["name"]):
                    child_items.append({"kind": "lane", "lane": lane, "is_child": True})
            if not child_items:
                continue
            items.append({"kind": "group_header", "name": group["name"]})
            if self._group_state.get(group["name"], False):
                continue
            items.extend(child_items)

        return items

    def _get_lane_color(self, level: int) -> str:
        """Resolve configured lane color by level."""
        for lane in self.config.lanes:
            if lane["level"] == level:
                return lane["color"]
        return COLOR_TEXT_MUTED

    def _comparison_mode_active(self) -> bool:
        return self._show_comparison and self._comparison_store is not None

    def _should_show_lane(self, lane_name: str) -> bool:
        if not self._comparison_mode_active():
            return True
        if self._comparison_lane_filter is not None:
            return lane_name == self._comparison_lane_filter
        return bool(
            self._comparison_annotations(
                self._store,
                lane_name,
                source=self._primary_source_filter,
            )
            or self._comparison_annotations(
                self._comparison_store,
                lane_name,
                source=self._comparison_source_filter,
            )
        )

    def _comparison_annotations(
        self,
        store: AnnotationStore | None,
        lane_name: str | None = None,
        *,
        source: str | None = None,
    ) -> list:
        if store is None:
            return []
        return [
            ann
            for ann in store.annotations.values()
            if not ann.ghost and (lane_name is None or ann.lane == lane_name)
            and (source is None or ann.source == source)
        ]

    def _primary_row_source(self, source: str | None) -> str:
        if self._comparison_mode_active():
            return SESSION_A_SOURCE
        return source or "manual"

    def _annotation_translucent(self, ann_id: str, *, comparison: bool) -> bool:
        if not self._comparison_mode_active():
            return False
        unmatched = self._unmatched_comparison_ids if comparison else self._unmatched_primary_ids
        matched = self._matched_comparison_ids if comparison else self._matched_primary_ids
        if ann_id in unmatched:
            return True
        if ann_id in matched:
            return False
        return False

    def _lane_is_point(self, level: int) -> bool:
        lane = self.config.get_lane_config(level)
        return bool(lane and lane.get("lane_type", "interval") == "point")

    def _snap_to_nearest(self, time_ms: float) -> float:
        """Snap time to nearest snap point if within threshold."""
        if not self._snap_points:
            return time_ms
        for snap_time in self._snap_points:
            if abs(snap_time - time_ms) <= self._snap_threshold_ms:
                return snap_time
        return time_ms

    def set_snap_tolerance_ms(self, tolerance_ms: float) -> None:
        self._snap_threshold_ms = max(0.0, float(tolerance_ms))

    def snap_tolerance_ms(self) -> float:
        return self._snap_threshold_ms

    # --- Coordinate conversion ---

    # --- Coordinate conversion ---

    def _time_to_x(self, time_ms: float) -> float:
        """Convert time to x coordinate based on current view range."""
        content_width = max(1, self.width() - self._label_width)
        view_duration = self._view_end_ms - self._view_start_ms
        if view_duration <= 0:
            return self._label_width

        relative_time = time_ms - self._view_start_ms
        return self._label_width + (relative_time / view_duration) * content_width

    def _x_to_time(self, x: float) -> float:
        """Convert x coordinate to time based on current view range."""
        content_width = max(1, self.width() - self._label_width)
        view_duration = self._view_end_ms - self._view_start_ms

        x_relative = max(0, x - self._label_width)
        return self._view_start_ms + (x_relative / content_width) * view_duration

    def _y_to_lane(self, y: float) -> int | None:
        """Get lane level from y coordinate, or None if not in a lane."""
        if y < RULER_HEIGHT:
            return None

        current_y = RULER_HEIGHT

        for item in self._display_items():
            if item["kind"] == "group_header":
                if current_y <= y < current_y + HEADER_HEIGHT:
                    return None
                current_y += HEADER_HEIGHT
                continue

            lane = item["lane"]
            lane_height = self._lane_total_height(lane["level"])
            if current_y <= y < current_y + lane_height:
                return lane["level"]
            current_y += lane_height

        return None

    def _lane_y(self, level: int) -> int:
        """Get y coordinate for a lane level."""
        current_y = RULER_HEIGHT

        for item in self._display_items():
            if item["kind"] == "group_header":
                current_y += HEADER_HEIGHT
                continue

            lane = item["lane"]
            if lane["level"] == level:
                return current_y
            current_y += self._lane_total_height(lane["level"])

        return -100  # Not found or hidden

    # --- Painting ---

    def paintEvent(self, event) -> None:
        """Draw the timeline."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # Background
        painter.fillRect(0, 0, width, height, QColor(COLOR_WINDOW_ALT_BG))

        # Draw time ruler
        self._draw_ruler(painter, width)

        # Draw swimlanes
        self._draw_lanes(painter, width)

        # Draw loop region behind annotations
        self._draw_loop_region(painter, height)

        # Draw annotations
        if self._store:
            self._draw_annotations(painter)
        self._draw_comparison_annotations(painter)

        # Draw drag preview
        if self._is_dragging and self._drag_lane is not None:
            self._draw_drag_preview(painter)

        # Draw snap points
        self._draw_snap_points(painter)

        # Draw playhead
        self._draw_playhead(painter, height)

        painter.end()

    def _draw_ruler(self, painter: QPainter, width: int) -> None:
        """Draw time ruler at top."""
        painter.fillRect(0, 0, width, RULER_HEIGHT, QColor(COLOR_WINDOW_BG))

        painter.setPen(QPen(QColor(COLOR_TEXT_SUBTLE), 1))
        num_markers = 10
        for i in range(num_markers + 1):
            x = self._label_width + int(i * (width - self._label_width) / num_markers)
            painter.drawLine(x, RULER_HEIGHT - 8, x, RULER_HEIGHT)

            painter.drawLine(x, RULER_HEIGHT - 8, x, RULER_HEIGHT)

            time_ms = self._view_start_ms + (i / num_markers) * (
                self._view_end_ms - self._view_start_ms
            )
            time_str = self._format_time(int(time_ms))
            if i < num_markers:
                painter.drawText(x + 4, RULER_HEIGHT - 10, time_str)

    def _draw_lanes(self, painter: QPainter, width: int) -> None:
        """Draw swimlane backgrounds, labels, and group headers."""
        current_y = RULER_HEIGHT
        for item in self._display_items():
            if item["kind"] == "group_header":
                collapsed = self._group_state.get(item["name"], False)
                self._draw_group_header(painter, width, current_y, item["name"], collapsed)
                current_y += HEADER_HEIGHT
                continue

            lane = item["lane"]
            lane_height = self._lane_total_height(lane["level"])
            self._draw_single_lane(painter, width, current_y, lane, is_child=item["is_child"])
            current_y += lane_height

    def _draw_group_header(
        self, painter: QPainter, width: int, y: int, name: str, collapsed: bool
    ) -> None:
        """Draw a collapsible group header."""
        painter.save()

        painter.fillRect(0, y, width, HEADER_HEIGHT, QColor(COLOR_WINDOW_BG))

        # Border
        painter.setPen(QPen(QColor(COLOR_BORDER), 1))
        painter.drawLine(0, y + HEADER_HEIGHT - 1, width, y + HEADER_HEIGHT - 1)

        # Icon
        icon = "▶" if collapsed else "▼"
        painter.setPen(QPen(QColor(COLOR_TEXT), 1))

        # Font settings for header
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)

        # Vertically centered text for 20px height (approx baseline at 14)
        text_y = y + 14

        painter.drawText(8, text_y, icon)
        painter.drawText(24, text_y, name.upper())

        painter.restore()

    def _draw_single_lane(
        self, painter: QPainter, width: int, y: int, lane: dict, is_child: bool = False
    ) -> None:
        """Helper to draw a single lane."""
        lane_height = self._lane_total_height(lane["level"])

        # Alternating background (simplified)
        bg_color = COLOR_TIMELINE_ROW_BG
        painter.fillRect(0, y, width, lane_height, QColor(bg_color))
        if self._comparison_mode_active():
            tint = QColor(lane["color"])
            tint.setAlpha(32 if self._lane_has_comparison_diff(lane["name"]) else 18)
            painter.fillRect(self._label_width, y, width - self._label_width, lane_height, tint)

        # Label background
        label_bg = COLOR_WINDOW_ALT_BG if is_child else COLOR_WINDOW_BG
        painter.fillRect(0, y, self._label_width, lane_height, QColor(label_bg))

        # Lane label
        lane_is_active = lane["level"] == self._active_overlay_level
        label_color = COLOR_TEXT_STRONG if lane_is_active else COLOR_TEXT_SUBTLE
        painter.setPen(QPen(QColor(label_color), 1))

        font = painter.font()
        font.setBold(lane_is_active)
        painter.setFont(font)

        if not self._comparison_mode_active():
            indent = 20 if is_child else 8
            label_text = painter.fontMetrics().elidedText(
                str(lane["name"]),
                Qt.TextElideMode.ElideRight,
                max(8, self._label_width - indent - 8),
            )
            painter.drawText(indent, y + 20, label_text)

        # Active indicator
        if lane_is_active:
            painter.fillRect(0, y, 4, lane_height, QColor(COLOR_ACCENT_MUTED))

        for index, source in enumerate(self._lane_sources(lane["level"])):
            sub_y = y + index * SUB_ROW_HEIGHT
            if index > 0:
                painter.setPen(QPen(QColor(COLOR_BORDER), 1, Qt.PenStyle.DotLine))
                painter.drawLine(self._label_width, sub_y, width, sub_y)
            if self._show_source_label(index):
                row_is_active = lane_is_active and source == self._active_overlay_source
                painter.setPen(QPen(QColor(COLOR_TEXT_EMPHASIS if row_is_active else COLOR_TEXT_SUBTLE), 1))
                row_font = painter.font()
                row_font.setBold(row_is_active)
                painter.setFont(row_font)
                painter.drawText(
                    4,
                    sub_y,
                    self._label_width - 8,
                    SUB_ROW_HEIGHT,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    self._source_short_label(source),
                )

        # Separator
        painter.setPen(QPen(QColor(COLOR_BORDER), 1))
        painter.drawLine(0, y + lane_height - 1, width, y + lane_height - 1)

    def _draw_annotations(self, painter: QPainter) -> None:
        """Draw all annotations from the store."""
        if not self._store:
            return

        annotations = (
            self._comparison_annotations(
                self._store,
                source=self._primary_source_filter,
            )
            if self._comparison_mode_active()
            else list(self._store.annotations.values())
        )
        for ann in annotations:
            level = self._lane_name_to_level(ann.lane)
            if level is None:
                continue
            sub_row_top = self._sub_row_y(level, self._primary_row_source(ann.source))
            sub_row_height = SUB_ROW_HEIGHT
            if ann.event_type == "point":
                self._draw_point_marker(
                    painter,
                    ann.id,
                    ann.start_ms,
                    level,
                    ann.label,
                    ghost=ann.ghost,
                    has_violation=ann.id in self._violating_annotation_ids,
                    sub_row_top=sub_row_top,
                    sub_row_height=sub_row_height,
                    color_override=COLOR_COMPARISON if self._comparison_mode_active() else None,
                    translucent=self._annotation_translucent(ann.id, comparison=False),
                )
            else:
                self._draw_annotation_bar(
                    painter,
                    ann.id,
                    ann.start_ms,
                    ann.end_ms,
                    level,
                    ann.label,
                    ghost=ann.ghost,
                    has_violation=ann.id in self._violating_annotation_ids,
                    bar_top=sub_row_top + 3,
                    bar_height=sub_row_height - 6,
                    color_override=COLOR_COMPARISON if self._comparison_mode_active() else None,
                    translucent=self._annotation_translucent(ann.id, comparison=False),
                )

    def _draw_comparison_annotations(self, painter: QPainter) -> None:
        """Draw comparison annotations in a separate non-interactive overlay pass."""
        if not self._comparison_store or not self._show_comparison:
            return

        for ann in self._comparison_annotations(
            self._comparison_store,
            source=self._comparison_source_filter,
        ):
            level = self._lane_name_to_level(ann.lane)
            if level is None:
                continue
            sub_row_top = self._sub_row_y(level, COMPARISON_SOURCE)
            sub_row_height = SUB_ROW_HEIGHT
            if ann.event_type == "point":
                self._draw_point_marker(
                    painter,
                    ann.id,
                    ann.start_ms,
                    level,
                    ann.label,
                    sub_row_top=sub_row_top,
                    sub_row_height=sub_row_height,
                    color_override=COLOR_PENDING,
                    comparison=True,
                    translucent=self._annotation_translucent(ann.id, comparison=True),
                )
            else:
                self._draw_annotation_bar(
                    painter,
                    ann.id,
                    ann.start_ms,
                    ann.end_ms,
                    level,
                    ann.label,
                    bar_top=sub_row_top + 3,
                    bar_height=sub_row_height - 6,
                    color_override=COLOR_PENDING,
                    comparison=True,
                    translucent=self._annotation_translucent(ann.id, comparison=True),
                )

    def _draw_annotation_bar(
        self,
        painter: QPainter,
        ann_id: str,
        start_ms: float,
        end_ms: float,
        level: int,
        label: str,
        ghost: bool = False,
        has_violation: bool = False,
        bar_top: int | None = None,
        bar_height: int | None = None,
        color_override: str | None = None,
        comparison: bool = False,
        translucent: bool = False,
    ) -> None:
        """Draw a single annotation bar."""
        x1 = self._time_to_x(start_ms)
        x2 = self._time_to_x(end_ms)
        y = self._lane_y(level) + 4 if bar_top is None else bar_top
        bar_height = SUB_ROW_HEIGHT - 6 if bar_height is None else bar_height

        color = color_override or self._get_lane_color(level)

        # Selected state
        is_selected = not comparison and ann_id == self._selected_id

        # Draw bar
        bar_color = self._annotation_fill_color(
            color,
            comparison=comparison,
            translucent=translucent,
            ghost=ghost,
        )
        painter.fillRect(int(x1), y, int(x2 - x1), bar_height, bar_color)

        # Draw border if selected
        if is_selected:
            painter.setPen(QPen(QColor(COLOR_TEXT_STRONG), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(x1), y, int(x2 - x1), bar_height)
        elif comparison:
            painter.setPen(QPen(QColor(color), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(x1), y, int(x2 - x1), bar_height)

        # Draw label text if bar is wide enough
        bar_width = x2 - x1
        self._draw_status_badges(
            painter,
            left=self._status_badge_x(
                int(x1),
                int(x2),
                ghost=ghost,
                violating=has_violation,
            ),
            top=y,
            height=bar_height,
            ghost=ghost,
            violating=has_violation,
        )
        if bar_width > 40:
            painter.setPen(QPen(QColor(COLOR_TEXT_STRONG), 1))
            text = label[: int(bar_width / 8)]  # Rough character estimate
            painter.drawText(int(x1) + 4, y + bar_height - 6, text)

    def _draw_point_marker(
        self,
        painter: QPainter,
        ann_id: str,
        time_ms: float,
        level: int,
        label: str,
        ghost: bool = False,
        has_violation: bool = False,
        sub_row_top: int | None = None,
        sub_row_height: int | None = None,
        color_override: str | None = None,
        comparison: bool = False,
        translucent: bool = False,
    ) -> None:
        """Draw a point event marker within a lane."""
        x = int(self._time_to_x(time_ms))
        row_top = self._lane_y(level) if sub_row_top is None else sub_row_top
        row_height = SUB_ROW_HEIGHT if sub_row_height is None else sub_row_height
        y = row_top + 2
        if y < RULER_HEIGHT:
            return

        color = self._point_marker_color(
            color_override or self._get_lane_color(level),
            comparison=comparison,
            translucent=translucent,
            ghost=ghost,
        )

        stem_pen = QPen(color, 2)
        painter.setPen(stem_pen)
        painter.drawLine(x, y + 8, x, row_top + row_height - 4)

        tip_size = 5
        painter.setBrush(color)
        painter.drawPolygon(
            QPolygon(
                [
                    QPoint(x - tip_size, y),
                    QPoint(x + tip_size, y),
                    QPoint(x, y + tip_size * 2),
                ]
            )
        )

        if not comparison and ann_id == self._selected_id:
            painter.setPen(QPen(QColor(COLOR_TEXT_STRONG), 1))
            painter.drawLine(x - 4, row_top + row_height - 5, x + 4, row_top + row_height - 5)

        badge_width = self._draw_status_badges(
            painter,
            left=x + 4,
            top=row_top + 2,
            height=12,
            ghost=ghost,
            violating=has_violation,
        )
        text_x = x + 6 + badge_width

        available_width = self.width() - x - 8
        if available_width > 36:
            painter.setPen(QPen(QColor(COLOR_TEXT_STRONG), 1))
            painter.drawText(
                text_x,
                row_top + row_height - 8,
                label[: int(available_width / 8)],
            )

    def _annotation_fill_color(
        self,
        color: str,
        *,
        comparison: bool = False,
        translucent: bool = False,
        ghost: bool = False,
    ) -> QColor:
        """Resolve interval fill color from schema color plus display state."""
        fill = QColor(color)
        if comparison and translucent:
            fill.setAlpha(55)
        elif comparison:
            fill.setAlpha(170)
        elif translucent:
            fill.setAlpha(70)
        elif ghost:
            fill.setAlpha(90)
        return fill

    def _point_marker_color(
        self,
        color: str,
        *,
        comparison: bool = False,
        translucent: bool = False,
        ghost: bool = False,
    ) -> QColor:
        """Resolve point marker color from schema color plus display state."""
        marker = QColor(color)
        if comparison and translucent:
            marker.setAlpha(90)
        elif comparison:
            marker.setAlpha(220)
        elif translucent:
            marker.setAlpha(100)
        elif ghost:
            marker.setAlpha(115)
        return marker

    def _draw_status_badges(
        self,
        painter: QPainter,
        *,
        left: int,
        top: int,
        height: int,
        ghost: bool = False,
        violating: bool = False,
    ) -> int:
        """Draw compact status badges and return the horizontal space used."""
        x = left
        for symbol in annotation_indicator_symbols(ghost=ghost, violating=violating):
            self._draw_status_badge(
                painter,
                left=x,
                top=top,
                height=height,
                symbol=symbol,
            )
            x += 14
        return max(0, x - left)

    def _status_badge_x(
        self,
        left_edge: int,
        right_edge: int,
        *,
        ghost: bool = False,
        violating: bool = False,
    ) -> int:
        """Place interval badges just outside the bar so they never tint the fill."""
        badge_count = len(annotation_indicator_symbols(ghost=ghost, violating=violating))
        badge_width = max(0, badge_count * 14)
        preferred_left = left_edge - badge_width - 4
        if preferred_left >= self._label_width + 2:
            return preferred_left
        return right_edge + 4

    def _draw_status_badge(
        self,
        painter: QPainter,
        *,
        left: int,
        top: int,
        height: int,
        symbol: str,
    ) -> None:
        """Draw a compact badge for ghost or rule-violation state."""
        badge_size = max(10, min(14, height - 2 if height > 2 else 10))
        badge_y = top + max(0, (height - badge_size) // 2)
        painter.setPen(Qt.PenStyle.NoPen)
        badge_color = QColor(COLOR_CONFIDENCE_WARN) if symbol == "?" else QColor(COLOR_CONFIDENCE_ERROR)
        painter.setBrush(badge_color)
        painter.drawEllipse(left, badge_y, badge_size, badge_size)
        painter.setPen(QPen(QColor(COLOR_TEXT_STRONG), 1))
        painter.drawText(left, badge_y, badge_size, badge_size, Qt.AlignmentFlag.AlignCenter, symbol)

    def _draw_drag_preview(self, painter: QPainter) -> None:
        """Draw rubber-band preview during drag-to-create."""
        x1 = min(self._drag_start_x, self._drag_end_x)
        x2 = max(self._drag_start_x, self._drag_end_x)
        y = self._sub_row_y(self._drag_lane, "manual") + 3
        bar_height = SUB_ROW_HEIGHT - 6

        # Semi-transparent preview
        preview_color = QColor(COLOR_ACCENT_MUTED)
        preview_color.setAlpha(128)
        painter.fillRect(int(x1), y, int(x2 - x1), bar_height, preview_color)

        # Dashed border
        pen = QPen(QColor(COLOR_TEXT_STRONG), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(int(x1), y, int(x2 - x1), bar_height)

    def _draw_playhead(self, painter: QPainter, height: int) -> None:
        """Draw the playhead indicator."""
        if self._duration_ms > 0:
            playhead_x = int(self._time_to_x(self._current_position_ms))
            color = QColor(COLOR_TRIM_EDGE)
            painter.setPen(QPen(color, 2))
            painter.drawLine(playhead_x, RULER_HEIGHT, playhead_x, height)

            # Downward-pointing triangle head at the ruler/lane boundary
            tip_size = 6
            triangle = QPolygon([
                QPoint(playhead_x, RULER_HEIGHT + tip_size),        # tip
                QPoint(playhead_x - tip_size, RULER_HEIGHT - 2),    # left
                QPoint(playhead_x + tip_size, RULER_HEIGHT - 2),    # right
            ])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(triangle)

    def _draw_snap_points(self, painter: QPainter) -> None:
        """Draw snap point markers on the ruler."""
        for i, snap_time in enumerate(self._snap_points):
            x = int(self._time_to_x(snap_time))
            is_selected = i == self._selected_snap_index

            # Draw diamond marker
            color = QColor(COLOR_ANCHOR) if not is_selected else QColor(COLOR_TEXT_STRONG)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(COLOR_VIDEO_BG), 1))

            # Diamond shape at top of ruler
            size = 6
            points = [
                (x, RULER_HEIGHT - size * 2),  # top
                (x + size, RULER_HEIGHT - size),  # right
                (x, RULER_HEIGHT),  # bottom
                (x - size, RULER_HEIGHT - size),  # left
            ]
            polygon = QPolygon([QPoint(px, py) for px, py in points])
            painter.drawPolygon(polygon)

            # Draw vertical guide line (subtle)
            if is_selected:
                pen = QPen(QColor(COLOR_ANCHOR), 1, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(x, RULER_HEIGHT, x, self.height())

    def _draw_loop_region(self, painter: QPainter, height: int) -> None:
        region = self.get_loop_region()
        if not region:
            return
        start_ms, end_ms = region
        x1 = int(self._time_to_x(start_ms))
        x2 = int(self._time_to_x(end_ms))
        if x2 <= x1:
            return

        fill = QColor(COLOR_LOOP_BORDER)
        fill.setAlpha(45)
        painter.fillRect(x1, RULER_HEIGHT, x2 - x1, max(0, height - RULER_HEIGHT), fill)

        edge_pen = QPen(QColor(COLOR_LOOP_ACCENT), 2)
        painter.setPen(edge_pen)
        painter.drawLine(x1, RULER_HEIGHT, x1, height)
        painter.drawLine(x2, RULER_HEIGHT, x2, height)

        painter.setBrush(QColor(COLOR_LOOP_ACCENT))
        handle_size = 5
        left_handle = QPolygon(
            [
                QPoint(x1, RULER_HEIGHT),
                QPoint(x1 - handle_size, RULER_HEIGHT - handle_size),
                QPoint(x1 + handle_size, RULER_HEIGHT - handle_size),
            ]
        )
        right_handle = QPolygon(
            [
                QPoint(x2, RULER_HEIGHT),
                QPoint(x2 - handle_size, RULER_HEIGHT - handle_size),
                QPoint(x2 + handle_size, RULER_HEIGHT - handle_size),
            ]
        )
        painter.drawPolygon(left_handle)
        painter.drawPolygon(right_handle)

    # --- Mouse events ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press for selection and drag start."""
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        x = event.position().x()
        y = event.position().y()

        if event.button() == Qt.MouseButton.MiddleButton and x >= self._label_width:
            self._is_panning = True
            self._pan_last_x = x
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.RightButton:
            if x < self._label_width and y >= RULER_HEIGHT:
                lane = self._y_to_lane(y)
                lane_name = self._level_to_lane_name(lane) if lane is not None else None
                if lane_name:
                    self.lane_header_context_requested.emit(
                        lane_name,
                        self._source_at_y(lane, y),
                        event.globalPosition().toPoint(),
                    )
                    event.accept()
                    return
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Keep keyboard actions like Delete bound to the timeline after click selection.
        self.setFocus(Qt.FocusReason.MouseFocusReason)

        # Check if clicking on lane label (for overlay toggle) OR group header
        if x < self._label_width and y >= RULER_HEIGHT:
            # Check if group header clicked
            current_y = RULER_HEIGHT
            for item in self._display_items():
                if item["kind"] == "group_header":
                    if current_y <= y < current_y + HEADER_HEIGHT:
                        name = item["name"]
                        self._group_state[name] = not self._group_state[name]
                        self._recalculate_height()
                        return
                    current_y += HEADER_HEIGHT
                    continue
                current_y += self._lane_total_height(item["lane"]["level"])

            # Check for overlay level selection
            lane = self._y_to_lane(y)
            if lane is not None:
                source = self._source_at_y(lane, y) or "manual"
                self.set_active_overlay_target(lane, source)
                return

        # Check if clicking on the ruler (seek or snap point)
        if y < RULER_HEIGHT:
            edge = self._hit_test_loop_edge(x, y)
            if edge is not None:
                self._loop_drag_mode = edge
                self._loop_drag_anchor_ms = self._x_to_time(x)
                event.accept()
                return

            if self._hit_test_loop_body(x, y):
                region = self.get_loop_region()
                if region:
                    self._loop_drag_mode = "move"
                    self._loop_drag_anchor_ms = self._x_to_time(x)
                    self._loop_drag_initial_start_ms = region[0]
                    self._loop_drag_initial_end_ms = region[1]
                    self.setCursor(Qt.CursorShape.ClosedHandCursor)
                    event.accept()
                    return

            # Check for snap point click first
            snap_index = self._hit_test_snap_point(x)
            if snap_index is not None:
                self._selected_snap_index = snap_index
                self._is_dragging_snap = True
                self._drag_snap_index = snap_index
                self._selected_id = None
                self._emit_selection_state()
                snap_time = self._snap_points[snap_index]
                self._current_position_ms = snap_time
                self.position_clicked.emit(snap_time)
                self.update()
                return

            # Otherwise seek
            self._selected_snap_index = None
            self._selected_id = None
            self._emit_selection_state()
            time_ms = self._x_to_time(x)
            self._current_position_ms = time_ms
            self.position_clicked.emit(time_ms)
            self.update()
            return

        # Check if clicking on an annotation edge
        edge_hit = self._hit_test_annotation_edge(x, y)
        if edge_hit:
            self._drag_ann_id, self._drag_edge = edge_hit
            self.select_annotation(self._drag_ann_id)
            return

        # Check if clicking on existing annotation body
        clicked_id = self._hit_test_annotation(x, y)
        if clicked_id:
            self.select_annotation(clicked_id)
            return

        # Clicked empty space
        self.clear_selection()

        # Start drag-to-create
        lane = self._y_to_lane(y)
        if lane is not None and x >= self._label_width:
            if self._lane_is_point(lane):
                time_ms = self._snap_to_nearest(self._x_to_time(x))
                self.annotation_created.emit(lane, time_ms, time_ms)
            else:
                self._is_dragging = True
                self._drag_lane = lane
                self._drag_start_x = x
                self._drag_end_x = x
                self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Accept a ghost annotation on timeline double-click."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return

        clicked_id = self._hit_test_annotation(event.position().x(), event.position().y())
        if clicked_id and self._store:
            ann = self._store.get(clicked_id)
            if ann is not None and ann.ghost:
                self.select_annotation(clicked_id)
                self.ghost_accept_requested.emit(clicked_id)
                event.accept()
                return

        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move for drag preview, edge detection, and hovering."""
        x = event.position().x()
        y = event.position().y()

        if self._is_panning:
            content_width = max(1, self.width() - self._label_width)
            view_duration = self._view_end_ms - self._view_start_ms
            delta_px = x - self._pan_last_x
            self._pan_last_x = x
            delta_ms = -(delta_px / content_width) * view_duration
            self.set_view_range(self._view_start_ms + delta_ms, self._view_end_ms + delta_ms)
            return

        if self._loop_drag_mode is not None:
            self._update_loop_region_drag(x)
            return

        if self._is_dragging_snap and self._drag_snap_index is not None:
            new_time = max(0, min(self._duration_ms, self._x_to_time(x)))
            self._snap_points[self._drag_snap_index] = new_time
            self._snap_points.sort()
            # Update index after sort
            self._drag_snap_index = self._snap_points.index(new_time)
            self._selected_snap_index = self._drag_snap_index
            self.snap_point_modified.emit()
            self.update()
            return

        if self._drag_ann_id and self._drag_edge and self._store:
            new_time = max(0, min(self._duration_ms, self._x_to_time(x)))
            # Snap to nearest point except itself
            snapped_time = self._snap_to_nearest(new_time)

            ann = self._store.get(self._drag_ann_id)

            if ann:
                if self._drag_edge == "start":
                    ann.start_ms = min(snapped_time, ann.end_ms - 1)
                else:
                    ann.end_ms = max(snapped_time, ann.start_ms + 1)
                self.update()
                # Also update overlay during drag
                self.annotation_modified.emit(self._drag_ann_id, ann.start_ms, ann.end_ms)
                self.annotation_selected.emit(self._drag_ann_id)
            return

        if self._is_dragging:
            self._drag_end_x = max(self._label_width, x)
            self.update()
            return

        if self._hit_test_loop_edge(x, y):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if self._hit_test_loop_body(x, y):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        # Ruler zone: indicate it's seekable unless a snap point is nearby
        if y < RULER_HEIGHT:
            snap_hit = any(
                abs(self._time_to_x(t) - x) <= SNAP_HIT_RADIUS
                for t in self._snap_points
            )
            if not snap_hit:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
            return

        # Hover effect for edges
        if self._hit_test_annotation_edge(x, y):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()

        # Hover effect for overlays
        hovered_id = self._hit_test_annotation(x, y)
        if hovered_id != self._last_hovered_id:
            if self._last_hovered_id:
                self.annotation_unhovered.emit(self._last_hovered_id)

            if hovered_id:
                self.annotation_hovered.emit(hovered_id)
                self._show_annotation_tooltip(hovered_id, event.globalPosition().toPoint())
            else:
                QToolTip.hideText()

            self._last_hovered_id = hovered_id

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handle mouse release to complete drag/resize operations."""
        if event.button() == Qt.MouseButton.MiddleButton and self._is_panning:
            self._is_panning = False
            self.unsetCursor()
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._loop_drag_mode is not None:
            self._loop_drag_mode = None
            self.unsetCursor()
            event.accept()
            return

        if self._is_dragging_snap:
            self._is_dragging_snap = False
            self._drag_snap_index = None

        if self._drag_ann_id:
            self._drag_ann_id = None
            self._drag_edge = None

        if self._is_dragging and self._drag_lane is not None:
            # Calculate time range
            start_x = min(self._drag_start_x, self._drag_end_x)
            end_x = max(self._drag_start_x, self._drag_end_x)

            # Only create if dragged a meaningful distance
            if end_x - start_x > 10:
                start_ms = self._x_to_time(start_x)
                end_ms = self._x_to_time(end_x)
                # Apply snapping
                start_ms = self._snap_to_nearest(start_ms)
                end_ms = self._snap_to_nearest(end_ms)
                self.annotation_created.emit(self._drag_lane, start_ms, end_ms)

            self._is_dragging = False
            self._drag_lane = None
            self.update()

    def leaveEvent(self, event) -> None:
        if self._last_hovered_id:
            self.annotation_unhovered.emit(self._last_hovered_id)
            self._last_hovered_id = None
        QToolTip.hideText()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        """Handle keyboard events for nudging, snapping, and deletion."""
        key = event.key()
        self._keys_pressed.add(key)
        modifiers = event.modifiers()

        # Deselect
        if self._matches_shortcut(event, CLEAR_SELECTION):
            self.clear_selection()
            return

        if (
            key in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            and modifiers & Qt.KeyboardModifier.AltModifier
            and not (modifiers & Qt.KeyboardModifier.ControlModifier)
            and not (modifiers & Qt.KeyboardModifier.MetaModifier)
        ):
            delta = -10 if key == Qt.Key.Key_Left else 10

            if self._selected_snap_index is not None and not (
                modifiers & Qt.KeyboardModifier.ShiftModifier
            ):
                new_time = max(
                    0,
                    min(
                        self._duration_ms,
                        self._snap_points[self._selected_snap_index] + delta,
                    ),
                )
                self._snap_points[self._selected_snap_index] = new_time
                self._snap_points.sort()
                self._selected_snap_index = self._snap_points.index(new_time)
                self.snap_point_modified.emit()
                self.update()
                return

            if self._selected_id and self._store:
                ann = self._store.get(self._selected_id)
                if ann is None:
                    return

                if ann.event_type == "point":
                    if modifiers & Qt.KeyboardModifier.ShiftModifier:
                        return
                    new_time = max(0, min(self._duration_ms, ann.start_ms + delta))
                    ann.start_ms = new_time
                    ann.end_ms = new_time
                    self.annotation_modified.emit(self._selected_id, ann.start_ms, ann.end_ms)
                    self.update()
                    return

                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    ann.end_ms = max(
                        ann.start_ms + 1, min(ann.end_ms + delta, self._duration_ms)
                    )
                else:
                    ann.start_ms = max(0, min(ann.start_ms + delta, ann.end_ms - 1))
                self.annotation_modified.emit(self._selected_id, ann.start_ms, ann.end_ms)
                self.update()
                return

        if (
            key in (Qt.Key.Key_Left, Qt.Key.Key_Right)
            and not (modifiers & Qt.KeyboardModifier.AltModifier)
            and not (modifiers & Qt.KeyboardModifier.ControlModifier)
            and not (modifiers & Qt.KeyboardModifier.MetaModifier)
        ):
            frame_ms = 33 * (10 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1)
            playhead_delta = -frame_ms if key == Qt.Key.Key_Left else frame_ms
            new_time = max(0, min(self._duration_ms, self._current_position_ms + playhead_delta))
            self._current_position_ms = new_time
            self.position_clicked.emit(new_time)
            self.update()
            return

        # Add snap point at current playhead position
        if self._matches_shortcut(event, ADD_SNAP_POINT):
            self.add_snap_point(self._current_position_ms)
            return

        super().keyPressEvent(event)

    def set_shortcuts(self, shortcuts: dict[str, str]) -> None:
        self._shortcuts = dict(shortcuts)

    def _matches_shortcut(self, event, shortcut_id: str) -> bool:
        return event_matches_shortcut(event, self._shortcuts.get(shortcut_id, ""))

    def keyReleaseEvent(self, event) -> None:
        if event.key() in self._keys_pressed:
            self._keys_pressed.remove(event.key())
        super().keyReleaseEvent(event)

    # --- Hit testing ---

    def _hit_test_loop_edge(self, x: float, y: float) -> str | None:
        if y >= RULER_HEIGHT:
            return None
        region = self.get_loop_region()
        if not region:
            return None
        x1 = self._time_to_x(region[0])
        x2 = self._time_to_x(region[1])
        if abs(x - x1) <= LOOP_EDGE_HIT_RADIUS:
            return "start"
        if abs(x - x2) <= LOOP_EDGE_HIT_RADIUS:
            return "end"
        return None

    def _hit_test_loop_body(self, x: float, y: float) -> bool:
        if y >= RULER_HEIGHT:
            return False
        region = self.get_loop_region()
        if not region:
            return False
        x1 = self._time_to_x(region[0])
        x2 = self._time_to_x(region[1])
        return x1 < x < x2

    def _update_loop_region_drag(self, x: float) -> None:
        region = self.get_loop_region()
        if not region:
            return
        start_ms, end_ms = region
        cursor_ms = self._x_to_time(x)

        if self._loop_drag_mode == "start":
            start_ms = min(cursor_ms, end_ms - LOOP_MIN_SPAN_MS)
            start_ms = max(0.0, start_ms)
        elif self._loop_drag_mode == "end":
            end_ms = max(cursor_ms, start_ms + LOOP_MIN_SPAN_MS)
            end_ms = min(self._duration_ms, end_ms)
        elif self._loop_drag_mode == "move":
            width = self._loop_drag_initial_end_ms - self._loop_drag_initial_start_ms
            delta = cursor_ms - self._loop_drag_anchor_ms
            start_ms = self._loop_drag_initial_start_ms + delta
            end_ms = self._loop_drag_initial_end_ms + delta
            if start_ms < 0:
                end_ms += -start_ms
                start_ms = 0.0
            if end_ms > self._duration_ms:
                start_ms -= end_ms - self._duration_ms
                end_ms = self._duration_ms
            if end_ms - start_ms < width:
                end_ms = min(self._duration_ms, start_ms + width)

        start_ms, end_ms = self._normalized_loop_bounds(start_ms, end_ms)
        self._loop_start_ms = start_ms
        self._loop_end_ms = end_ms
        self.loop_region_changed.emit(start_ms, end_ms)
        self.update()

    def _hit_test_annotation(self, x: float, y: float) -> str | None:
        """Check if a point hits an annotation, return its ID."""
        if not self._store:
            return None

        lane = self._y_to_lane(y)
        if lane is None:
            return None

        time_ms = self._x_to_time(x)
        view_duration = max(1.0, self._view_end_ms - self._view_start_ms)
        threshold_ms = (POINT_HIT_RADIUS / max(1, self.width() - self._label_width)) * view_duration

        lane_cfg = self.config.get_lane_config(lane)
        if not lane_cfg:
            return None

        annotations = (
            self._comparison_annotations(
                self._store,
                lane_cfg["name"],
                source=self._primary_source_filter,
            )
            if self._comparison_mode_active()
            else self._store.get_by_lane(lane_cfg["name"])
        )
        for ann in annotations:
            row_top = self._sub_row_y(lane, self._primary_row_source(ann.source))
            row_bottom = row_top + SUB_ROW_HEIGHT
            if not (row_top <= y < row_bottom):
                continue
            if ann.event_type == "point":
                if abs(time_ms - ann.start_ms) <= threshold_ms:
                    return ann.id
                continue
            if ann.start_ms <= time_ms <= ann.end_ms:
                return ann.id

        return None

    def _hit_test_snap_point(self, x: float) -> int | None:
        """Check if x coordinate hits a snap point, return index."""
        for i, snap_time in enumerate(self._snap_points):
            snap_x = self._time_to_x(snap_time)
            if abs(x - snap_x) <= SNAP_HIT_RADIUS:
                return i
        return None

    def _hit_test_annotation_edge(self, x: float, y: float) -> tuple[str, str] | None:
        """Check if a point hits an annotation edge, return (id, 'start'|'end')."""
        if not self._store:
            return None

        lane = self._y_to_lane(y)
        if lane is None:
            return None

        time_ms = self._x_to_time(x)
        threshold_px = 6
        view_duration = max(1.0, self._view_end_ms - self._view_start_ms)
        threshold_ms = (threshold_px / max(1, self.width() - self._label_width)) * view_duration

        lane_cfg = self.config.get_lane_config(lane)
        if not lane_cfg:
            return None

        annotations = (
            self._comparison_annotations(
                self._store,
                lane_cfg["name"],
                source=self._primary_source_filter,
            )
            if self._comparison_mode_active()
            else self._store.get_by_lane(lane_cfg["name"])
        )

        for ann in annotations:
            if ann.event_type == "point":
                continue
            row_top = self._sub_row_y(lane, self._primary_row_source(ann.source))
            row_bottom = row_top + SUB_ROW_HEIGHT
            if not (row_top <= y < row_bottom):
                continue
            if abs(time_ms - ann.start_ms) < threshold_ms:
                return ann.id, "start"
            if abs(time_ms - ann.end_ms) < threshold_ms:
                return ann.id, "end"

        return None

    @staticmethod
    def _format_time(ms: int) -> str:
        """Format milliseconds as M:SS."""
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"

    def set_view_range(self, start_ms: float, end_ms: float) -> None:
        """Set the visible time range."""
        duration = max(1.0, float(self._duration_ms))
        min_span = min(500.0, duration)
        span = max(min_span, float(end_ms) - float(start_ms))
        span = min(span, duration)

        start = float(start_ms)
        start = max(0.0, min(start, duration - span))
        end = start + span

        changed = start != self._view_start_ms or end != self._view_end_ms
        self._view_start_ms = start
        self._view_end_ms = end
        if changed:
            self.view_range_changed.emit(start, end)
        self.update()

    def get_view_range(self) -> tuple[float, float]:
        return self._view_start_ms, self._view_end_ms

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Ctrl+wheel zoom around cursor; regular wheel uses default behavior."""
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            super().wheelEvent(event)
            return

        if self._duration_ms <= 0 or event.position().x() < self._label_width:
            return

        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            return

        factor = 0.8 if delta > 0 else 1.25
        current_span = self._view_end_ms - self._view_start_ms
        if current_span <= 0:
            return

        min_span = min(500.0, self._duration_ms)
        new_span = min(self._duration_ms, max(min_span, current_span * factor))
        cursor_time = self._x_to_time(event.position().x())
        cursor_ratio = (cursor_time - self._view_start_ms) / current_span
        new_start = cursor_time - (cursor_ratio * new_span)
        self.set_view_range(new_start, new_start + new_span)
        event.accept()

    def _show_annotation_tooltip(self, ann_id: str, global_pos: QPoint) -> None:
        if not self._store:
            return
        ann = self._store.get(ann_id)
        if not ann:
            return

        start = self._format_precise_time(ann.start_ms)
        if ann.event_type == "point":
            text = (
                f"Lane: {ann.lane}\n"
                f"Label: {ann.label}\n"
                f"Time: {start}\n"
                f"Type: point\n"
                f"Source: {ann.source}"
            )
        else:
            end = self._format_precise_time(ann.end_ms)
            duration = self._format_precise_time(ann.duration_ms)
            text = (
                f"Lane: {ann.lane}\n"
                f"Label: {ann.label}\n"
                f"Range: {start} - {end}\n"
                f"Duration: {duration}\n"
                f"Type: interval\n"
                f"Source: {ann.source}"
            )
        QToolTip.showText(global_pos, text, self)

    @staticmethod
    def _format_precise_time(ms: float) -> str:
        value = max(0, int(ms))
        total_seconds = value // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        millis = value % 1000
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

    def _lane_has_comparison_diff(self, lane_name: str) -> bool:
        if not self._show_comparison or not self._store or not self._comparison_store:
            return False
        return self._lane_signature_set(
            self._comparison_annotations(
                self._store,
                lane_name,
                source=self._primary_source_filter,
            )
        ) != self._lane_signature_set(
            self._comparison_annotations(
                self._comparison_store,
                lane_name,
                source=self._comparison_source_filter,
            )
        )

    @staticmethod
    def _lane_signature_set(annotations: list) -> set[tuple]:
        return {
            (
                ann.label,
                ann.event_type,
                round(float(ann.start_ms), 3),
                round(float(ann.end_ms), 3),
            )
            for ann in annotations
        }


class TimelineWidget(QWidget):
    """
    Container widget for the Integrated Command Deck.
    Stacks AnnotationLanes and SignalTrackWidget using a QSplitter.
    """

    # Forward signals
    position_clicked = Signal(float)
    view_range_changed = Signal(float, float)
    annotation_created = Signal(int, float, float)
    annotation_modified = Signal(str, float, float)
    annotation_selected = Signal(str)
    ghost_accept_requested = Signal(str)
    annotation_deleted = Signal(str)
    snap_point_added = Signal(float)
    snap_point_removed = Signal(float)
    snap_point_modified = Signal()
    selection_state_changed = Signal(bool, bool)  # has_annotation, has_snap
    loop_region_changed = Signal(float, float)  # start_ms, end_ms
    lane_header_context_requested = Signal(str, object, object)

    def __init__(self, schema: ProtocolSchema) -> None:
        super().__init__()

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Main splitter for resizing
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.layout.addWidget(self.splitter)
        self._signal_panel_last_sizes: list[int] | None = None

        # Annotation Lanes (Top) in ScrollArea
        self.lanes = AnnotationLanes(schema)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.lanes)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setMinimumHeight(100)  # Reduced min height
        self.scroll_area.setFocusProxy(self.lanes)
        self.setFocusProxy(self.lanes)

        self.splitter.addWidget(self.scroll_area)

        # Signal Tracks (Bottom)
        self.signals = SignalTrackWidget()
        self.signals.setMinimumHeight(100)
        self.splitter.addWidget(self.signals)

        # Set default sizes (e.g., 50/50 starting point, but relative to window)
        self.splitter.setSizes([200, 200])

        # Connect internal signals
        self._connect_signals()

    def set_store(self, store: AnnotationStore) -> None:
        """Set the annotation store for rendering and signal overlays."""
        self.lanes.set_store(store)
        self._load_all_overlays()

    def set_comparison_store(self, store: AnnotationStore | None) -> None:
        """Set a read-only comparison store for overlay rendering."""
        self.lanes.set_comparison_store(store)

    def set_show_comparison(self, visible: bool) -> None:
        """Toggle comparison overlay visibility."""
        self.lanes.set_show_comparison(visible)

    def set_comparison_filters(
        self,
        lane: str | None,
        primary_source: str | None,
        comparison_source: str | None,
    ) -> None:
        """Set the active lane/source filters for comparison mode."""
        self.lanes.set_comparison_filters(lane, primary_source, comparison_source)

    def set_comparison_match_state(
        self,
        *,
        matched_primary_ids: set[str] | None = None,
        matched_comparison_ids: set[str] | None = None,
        unmatched_primary_ids: set[str] | None = None,
        unmatched_comparison_ids: set[str] | None = None,
    ) -> None:
        """Set comparison-mode match styling."""
        self.lanes.set_comparison_match_state(
            matched_primary_ids=matched_primary_ids,
            matched_comparison_ids=matched_comparison_ids,
            unmatched_primary_ids=unmatched_primary_ids,
            unmatched_comparison_ids=unmatched_comparison_ids,
        )

    def set_violation_ids(self, annotation_ids: set[str] | None = None) -> None:
        """Set persistent rule violation markers for primary annotations."""
        self.lanes.set_violation_ids(annotation_ids)

    def set_schema(self, schema: ProtocolSchema) -> None:
        self.lanes.set_schema(schema)
        self._load_all_overlays()

    def _connect_signals(self) -> None:
        """Connect synchronization between lanes and signals."""
        # 1. Lanes -> passive views
        self.lanes.view_range_changed.connect(self._on_lane_view_changed)

        # 2. Lanes -> Signals (Overlay & Snap sync) + Forwarding
        self.lanes.position_clicked.connect(self.position_clicked)
        self.lanes.annotation_created.connect(self._on_annotation_created)
        self.lanes.annotation_modified.connect(self._on_annotation_modified)
        self.lanes.annotation_selected.connect(self._on_annotation_selected)
        self.lanes.ghost_accept_requested.connect(self.ghost_accept_requested)
        self.lanes.annotation_deleted.connect(self._on_annotation_deleted)
        self.lanes.selection_changed.connect(self.selection_state_changed)
        self.lanes.loop_region_changed.connect(self.loop_region_changed)

        self.lanes.snap_point_added.connect(self._on_snap_point_added)
        self.lanes.snap_point_removed.connect(self._on_snap_point_removed)
        self.lanes.snap_point_modified.connect(self._on_snap_modified)
        self.lanes.lane_header_context_requested.connect(self.lane_header_context_requested)

        # 3. Highlighting
        self.lanes.annotation_hovered.connect(self._on_hover_ann)
        self.lanes.annotation_unhovered.connect(self._on_unhover_ann)
        self.lanes.overlay_level_changed.connect(self._on_overlay_level_changed)

    def _on_lane_view_changed(self, start_ms: float, end_ms: float) -> None:
        """Sync passive detail views when timeline lanes change range."""
        self.signals.set_x_range(start_ms / 1000.0, end_ms / 1000.0)
        self.view_range_changed.emit(start_ms, end_ms)

    def _on_annotation_created(self, level: int, start_ms: float, end_ms: float) -> None:
        """Handle new annotation."""
        self.annotation_created.emit(level, start_ms, end_ms)
        # New user-created annotations are manual-source annotations.
        if (
            level == self.lanes._active_overlay_level
            and self.lanes._active_overlay_source == self.lanes._primary_row_source("manual")
        ):
            self._load_all_overlays()

    def _on_annotation_modified(self, ann_id: str, start_ms: float, end_ms: float) -> None:
        """Update signals when annotation is resized/moved."""
        self._load_all_overlays()
        self.annotation_modified.emit(ann_id, start_ms, end_ms)

    def _on_annotation_selected(self, ann_id: str) -> None:
        """Handle selection."""
        self.annotation_selected.emit(ann_id)

    def _on_annotation_deleted(self, ann_id: str) -> None:
        """Handle deletion."""
        self.annotation_deleted.emit(ann_id)
        self._load_all_overlays()

    def _on_snap_point_added(self, time_ms: float) -> None:
        """Handle snap point addition."""
        self.snap_point_added.emit(time_ms)
        self.signals.update_snap_lines(self.lanes.get_snap_points())

    def _on_snap_point_removed(self, time_ms: float) -> None:
        """Handle snap point removal."""
        self.snap_point_removed.emit(time_ms)
        self.signals.update_snap_lines(self.lanes.get_snap_points())

    def _on_snap_modified(self) -> None:
        """Handle real-time snap point movement."""
        self.snap_point_modified.emit()
        self.signals.update_snap_lines(self.lanes.get_snap_points())

    def _on_hover_ann(self, ann_id: str) -> None:
        pass

    def _on_unhover_ann(self, ann_id: str) -> None:
        pass

    def _on_overlay_level_changed(self, level: int, source: str | None) -> None:
        """Handle change in active overlay target."""
        self._load_all_overlays()

    def _load_all_overlays(self) -> None:
        """Helper to load all annotations from the store as overlays."""
        store = self.lanes._store
        self.lanes._ensure_active_overlay_target()
        active_level = self.lanes._active_overlay_level
        active_source = self.lanes._active_overlay_source
        self.signals.clear_overlays()

        if not store:
            return

        for ann in store.annotations.values():
            level = self.lanes._lane_name_to_level(ann.lane)
            if level != active_level:
                continue
            if self.lanes._primary_row_source(ann.source) != active_source:
                continue

            lane_cfg = self.lanes.config.get_lane_by_name(ann.lane) or {}
            color = lane_cfg.get("color", COLOR_ACCENT_MUTED)
            self.signals.add_overlay(ann.id, ann.start_ms / 1000.0, ann.end_ms / 1000.0, color=color)

    def refresh_overlays(self) -> None:
        self._load_all_overlays()

    def refresh_annotations(self) -> None:
        """Refresh lane geometry and repaint annotations after store mutations."""
        self.lanes._recalculate_height()
        self.lanes.update()
        self._load_all_overlays()

    def set_duration(self, duration_ms: float) -> None:
        self.lanes.set_duration(duration_ms)
        self.lanes.zoom_to_fit()
        start_ms, end_ms = self.lanes.get_view_range()
        self.signals.set_x_range(start_ms / 1000.0, end_ms / 1000.0)

    def set_position(self, position_ms: float) -> None:
        self.lanes.set_position(position_ms)
        self.signals.set_position(position_ms)

    def set_snap_tolerance_ms(self, tolerance_ms: float) -> None:
        self.lanes.set_snap_tolerance_ms(tolerance_ms)

    def snap_tolerance_ms(self) -> float:
        return self.lanes.snap_tolerance_ms()

    def set_signal_panel_visible(self, visible: bool) -> None:
        """Show or hide the signal panel while preserving the last expanded splitter sizes."""
        current_sizes = self.splitter.sizes()
        if visible:
            self.signals.show()
            restore_sizes = self._signal_panel_last_sizes
            if restore_sizes and len(restore_sizes) == 2 and sum(restore_sizes) > 0:
                self.splitter.setSizes(restore_sizes)
            else:
                total = max(1, sum(current_sizes) or self.height() or 400)
                signal_size = min(120, max(90, total // 4))
                self.splitter.setSizes([total - signal_size, signal_size])
            return

        if self.signals.isVisible():
            self._signal_panel_last_sizes = current_sizes
        self.signals.hide()
        total = max(1, sum(current_sizes) or self.height() or 400)
        self.splitter.setSizes([total, 0])

    def is_signal_panel_visible(self) -> bool:
        return not self.signals.isHidden()

    def get_selected_id(self) -> str | None:
        return self.lanes.get_selected_id()

    def get_selected_snap_index(self) -> int | None:
        return self.lanes.get_selected_snap_index()

    def set_shortcuts(self, shortcuts: dict[str, str]) -> None:
        self.lanes.set_shortcuts(shortcuts)

    def select_annotation(self, ann_id: str) -> bool:
        return self.lanes.select_annotation(ann_id)

    def zoom_to_fit(self) -> None:
        self.lanes.zoom_to_fit()

    def set_view_range(self, start_ms: float, end_ms: float) -> None:
        self.lanes.set_view_range(start_ms, end_ms)
        current_start, current_end = self.lanes.get_view_range()
        self.signals.set_x_range(current_start / 1000.0, current_end / 1000.0)

    def get_view_range(self) -> tuple[float, float]:
        return self.lanes.get_view_range()

    def set_loop_region(self, start_ms: float, end_ms: float) -> tuple[float, float]:
        start, end = self.lanes.set_loop_region(start_ms, end_ms)
        self.loop_region_changed.emit(start, end)
        return start, end

    def get_loop_region(self) -> tuple[float, float] | None:
        return self.lanes.get_loop_region()

    def has_loop_region(self) -> bool:
        return self.lanes.has_loop_region()

    def clear_loop_region(self) -> None:
        self.lanes.clear_loop_region()

    def seek_to(self, time_ms: float) -> None:
        self.lanes.seek_to(time_ms)

    def add_snap_point(self, time_ms: float) -> None:
        self.lanes.add_snap_point(time_ms)

    def remove_snap_point(self, index: int) -> None:
        self.lanes.remove_snap_point(index)

    def clear_all_snap_points(self) -> None:
        self.lanes.clear_all_snap_points()
        self.signals.update_snap_lines([])

    def get_snap_points(self) -> list[float]:
        return self.lanes.get_snap_points()

    def set_snap_points(self, snap_points: list[float]) -> None:
        self.lanes.set_snap_points(snap_points)
        self.signals.update_snap_lines(self.lanes.get_snap_points())

    def clear_selection(self) -> None:
        self.lanes.clear_selection()

    def set_active_overlay_target(self, lane_name: str, source: str) -> None:
        level = self.lanes._lane_name_to_level(lane_name)
        if level is None:
            return
        self.lanes.set_active_overlay_target(level, source)

    @property
    def _selected_snap_index(self):
        return self.lanes.get_selected_snap_index()

    @property
    def _current_position_ms(self):
        return self.lanes._current_position_ms
