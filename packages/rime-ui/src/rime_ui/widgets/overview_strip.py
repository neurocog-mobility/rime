"""Canonical full-session overview strip for position and zoom control."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from rime_core.annotations import Annotation
from rime_ui.theme import (
    COLOR_BORDER,
    COLOR_OVERVIEW_BG,
    COLOR_OVERVIEW_HANDLE,
    COLOR_OVERVIEW_VIEWPORT,
    COLOR_OVERVIEW_VIEWPORT_BORDER,
    COLOR_PLAYHEAD,
    COLOR_TIME_LABEL,
    COLOR_WINDOW_BG,
    SIGNAL_PLOT_COLORS,
    COLOR_LOOP_ACCENT,
    COLOR_LOOP_BORDER,
)


class OverviewStrip(QWidget):
    """Full-session minimap that owns canonical position and view-range interaction."""

    position_selected = Signal(float)
    view_range_changed = Signal(float, float)

    _MARGIN_X = 8
    _PLAYHEAD_RADIUS = 5
    _EDGE_HIT_WIDTH = 8
    _WINDOW_HANDLE_WIDTH = 10

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration_ms = 1.0
        self._position_ms = 0.0
        self._view_start_ms = 0.0
        self._view_end_ms = 1.0
        self._loop_start_ms: float | None = None
        self._loop_end_ms: float | None = None
        self._activity_annotations: list[Annotation] = []
        self._drag_mode: str | None = None
        self._drag_anchor_x = 0.0
        self._drag_anchor_position_ms = 0.0
        self._drag_anchor_view_start_ms = 0.0
        self._drag_anchor_view_end_ms = 1.0
        self.setMinimumHeight(72)
        self.setMaximumHeight(96)
        self.setMouseTracking(True)

    def set_duration(self, duration_ms: float) -> None:
        self._duration_ms = max(1.0, float(duration_ms))
        if self._view_end_ms <= self._view_start_ms:
            self._view_start_ms = 0.0
            self._view_end_ms = self._duration_ms
        else:
            self.set_view_range(self._view_start_ms, self._view_end_ms)
        self.set_position(self._position_ms)

    def set_position(self, position_ms: float) -> None:
        self._position_ms = max(0.0, min(float(position_ms), self._duration_ms))
        self.update()

    def set_view_range(self, start_ms: float, end_ms: float) -> None:
        start, end = self._clamp_view_range(start_ms, end_ms)
        self._view_start_ms = start
        self._view_end_ms = end
        self.update()

    def get_view_range(self) -> tuple[float, float]:
        return self._view_start_ms, self._view_end_ms

    def set_loop_region(self, start_ms: float, end_ms: float) -> None:
        start = max(0.0, min(float(start_ms), self._duration_ms))
        end = max(start, min(float(end_ms), self._duration_ms))
        self._loop_start_ms = start
        self._loop_end_ms = end
        self.update()

    def clear_loop_region(self) -> None:
        self._loop_start_ms = None
        self._loop_end_ms = None
        self.update()

    def set_annotations(self, annotations: list[Annotation]) -> None:
        self._activity_annotations = [annotation for annotation in annotations if not annotation.ghost]
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor(COLOR_WINDOW_BG))

        strip_rect = self._strip_rect()
        painter.fillRect(strip_rect, QColor(COLOR_OVERVIEW_BG))

        # Subtle session ruler baseline.
        painter.setPen(QPen(QColor(COLOR_BORDER), 1))
        painter.drawRect(strip_rect)
        self._draw_annotation_minimap(painter, strip_rect)
        self._draw_loop_region(painter, strip_rect)

        # Current zoom window.
        view_left = self._time_to_x(self._view_start_ms, strip_rect)
        view_right = self._time_to_x(self._view_end_ms, strip_rect)
        window_color = QColor(COLOR_OVERVIEW_VIEWPORT)
        window_color.setAlpha(42)
        painter.fillRect(
            int(view_left),
            strip_rect.top(),
            max(1, int(view_right - view_left)),
            strip_rect.height(),
            window_color,
        )
        painter.fillRect(
            int(view_left),
            strip_rect.top(),
            self._WINDOW_HANDLE_WIDTH,
            strip_rect.height(),
            QColor(COLOR_OVERVIEW_HANDLE),
        )
        painter.fillRect(
            int(view_right) - self._WINDOW_HANDLE_WIDTH,
            strip_rect.top(),
            self._WINDOW_HANDLE_WIDTH,
            strip_rect.height(),
            QColor(COLOR_OVERVIEW_HANDLE),
        )
        painter.setPen(QPen(QColor(COLOR_OVERVIEW_VIEWPORT_BORDER), 2))
        painter.drawRoundedRect(
            int(view_left),
            strip_rect.top(),
            max(1, int(view_right - view_left)),
            strip_rect.height(),
            4,
            4,
        )

        # Playhead.
        playhead_x = self._time_to_x(self._position_ms, strip_rect)
        painter.setPen(QPen(QColor(COLOR_PLAYHEAD), 2))
        painter.drawLine(int(playhead_x), strip_rect.top() - 4, int(playhead_x), strip_rect.bottom() + 6)
        painter.setBrush(QColor(COLOR_PLAYHEAD))
        painter.drawEllipse(QPointF(playhead_x, strip_rect.top() - 4), self._PLAYHEAD_RADIUS, self._PLAYHEAD_RADIUS)
        self._draw_time_labels(painter, strip_rect)

        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        strip_rect = self._interaction_rect()
        x = event.position().x()
        playhead_x = self._time_to_x(self._position_ms, strip_rect)
        view_left = self._time_to_x(self._view_start_ms, strip_rect)
        view_right = self._time_to_x(self._view_end_ms, strip_rect)

        self._drag_anchor_x = x
        self._drag_anchor_position_ms = self._position_ms
        self._drag_anchor_view_start_ms = self._view_start_ms
        self._drag_anchor_view_end_ms = self._view_end_ms

        if abs(x - playhead_x) <= self._PLAYHEAD_RADIUS + 2:
            self._drag_mode = "playhead"
            self._emit_position(x, strip_rect)
            return
        if abs(x - view_left) <= self._EDGE_HIT_WIDTH:
            self._drag_mode = "resize_left"
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if abs(x - view_right) <= self._EDGE_HIT_WIDTH:
            self._drag_mode = "resize_right"
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if view_left < x < view_right:
            self._drag_mode = "pan"
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        self._drag_mode = "playhead"
        self._emit_position(x, strip_rect)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        strip_rect = self._interaction_rect()
        x = event.position().x()

        if self._drag_mode == "playhead":
            self._emit_position(x, strip_rect)
            return

        delta_ms = self._x_to_time(x, strip_rect) - self._x_to_time(self._drag_anchor_x, strip_rect)
        if self._drag_mode == "pan":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._emit_view_range(
                self._drag_anchor_view_start_ms + delta_ms,
                self._drag_anchor_view_end_ms + delta_ms,
            )
            return
        if self._drag_mode == "resize_left":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._emit_view_range(
                self._drag_anchor_view_start_ms + delta_ms,
                self._drag_anchor_view_end_ms,
            )
            return
        if self._drag_mode == "resize_right":
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._emit_view_range(
                self._drag_anchor_view_start_ms,
                self._drag_anchor_view_end_ms + delta_ms,
            )
            return

        view_left = self._time_to_x(self._view_start_ms, strip_rect)
        view_right = self._time_to_x(self._view_end_ms, strip_rect)
        if abs(x - view_left) <= self._EDGE_HIT_WIDTH or abs(x - view_right) <= self._EDGE_HIT_WIDTH:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif view_left < x < view_right:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_mode = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._drag_mode is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def _emit_position(self, x: float, strip_rect) -> None:
        position_ms = self._x_to_time(x, strip_rect)
        self.set_position(position_ms)
        self.position_selected.emit(position_ms)

    def _emit_view_range(self, start_ms: float, end_ms: float) -> None:
        start, end = self._clamp_view_range(start_ms, end_ms)
        self.set_view_range(start, end)
        self.view_range_changed.emit(start, end)

    def _strip_rect(self):
        label_band = self.fontMetrics().height() + self._PLAYHEAD_RADIUS + 8
        top_margin = max(label_band, min(28, int(self.height() * 0.32)))
        bottom_margin = max(8, min(14, int(self.height() * 0.16)))
        return self.rect().adjusted(
            self._MARGIN_X,
            top_margin,
            -self._MARGIN_X,
            -bottom_margin,
        )

    def _interaction_rect(self):
        strip_rect = self._strip_rect()
        return strip_rect.adjusted(0, -4, 0, 4)

    def _clamp_view_range(self, start_ms: float, end_ms: float) -> tuple[float, float]:
        duration = max(1.0, self._duration_ms)
        min_span = min(500.0, duration)
        span = max(min_span, float(end_ms) - float(start_ms))
        span = min(span, duration)
        start = max(0.0, min(float(start_ms), duration - span))
        end = start + span
        return start, end

    def _time_to_x(self, time_ms: float, strip_rect) -> float:
        width = max(1.0, float(strip_rect.width()))
        return float(strip_rect.left()) + (max(0.0, min(time_ms, self._duration_ms)) / self._duration_ms) * width

    def _x_to_time(self, x: float, strip_rect) -> float:
        width = max(1.0, float(strip_rect.width()))
        ratio = (x - float(strip_rect.left())) / width
        return max(0.0, min(ratio, 1.0)) * self._duration_ms

    def _draw_time_labels(self, painter: QPainter, strip_rect) -> None:
        painter.setPen(QPen(QColor(COLOR_TIME_LABEL), 1))
        metrics = painter.fontMetrics()
        labels = [
            (strip_rect.left(), self._format_time(0.0), Qt.AlignmentFlag.AlignLeft),
            (
                strip_rect.center().x(),
                self._format_time(self._duration_ms / 2.0),
                Qt.AlignmentFlag.AlignHCenter,
            ),
            (strip_rect.right(), self._format_time(self._duration_ms), Qt.AlignmentFlag.AlignRight),
        ]
        for x, text, alignment in labels:
            width = metrics.horizontalAdvance(text) + 8
            height = metrics.height() + 2
            if alignment == Qt.AlignmentFlag.AlignLeft:
                left = int(x)
            elif alignment == Qt.AlignmentFlag.AlignRight:
                left = int(x) - width
            else:
                left = int(x) - width // 2
            label_top = max(2, strip_rect.top() - height - 6)
            painter.drawText(
                left,
                label_top,
                width,
                height,
                int(alignment | Qt.AlignmentFlag.AlignVCenter),
                text,
            )

    def _draw_annotation_minimap(self, painter: QPainter, strip_rect) -> None:
        if not self._activity_annotations:
            return
        annotation_alpha = self._annotation_alpha(len(self._activity_annotations))
        top = strip_rect.top() + 4
        height = max(4, strip_rect.height() - 8)
        for annotation in self._activity_annotations:
            start_x = self._time_to_x(annotation.start_ms, strip_rect)
            end_x = self._time_to_x(annotation.end_ms, strip_rect)
            width = max(2 if annotation.event_type == "point" else 1, int(end_x - start_x))
            if annotation.event_type == "point":
                start_x -= 1
            color = QColor(SIGNAL_PLOT_COLORS[5])
            color.setAlpha(annotation_alpha)
            painter.fillRect(int(start_x), int(top), width, height, color)

    def _draw_loop_region(self, painter: QPainter, strip_rect) -> None:
        if self._loop_start_ms is None or self._loop_end_ms is None or self._loop_end_ms <= self._loop_start_ms:
            return
        left = self._time_to_x(self._loop_start_ms, strip_rect)
        right = self._time_to_x(self._loop_end_ms, strip_rect)
        loop_fill = QColor(COLOR_LOOP_BORDER)
        loop_fill.setAlpha(54)
        painter.fillRect(
            int(left),
            strip_rect.top() + 2,
            max(1, int(right - left)),
            strip_rect.height() - 4,
            loop_fill,
        )
        painter.setPen(QPen(QColor(COLOR_LOOP_ACCENT), 1))
        painter.drawLine(int(left), strip_rect.top() + 1, int(left), strip_rect.bottom() - 1)
        painter.drawLine(int(right), strip_rect.top() + 1, int(right), strip_rect.bottom() - 1)

    @staticmethod
    def _annotation_alpha(annotation_count: int) -> int:
        if annotation_count <= 0:
            return 0
        return max(36, min(185, int(320 / annotation_count)))

    @staticmethod
    def _format_time(ms: float) -> str:
        total_seconds = int(ms // 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"
