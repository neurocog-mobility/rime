"""Video bounding-box selector for native model configuration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rime_ui.theme import COLOR_WARNING_ICON, COLOR_WINDOW_BG


def _load_first_video_frame(video_path: Path) -> QImage:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - runtime environment dependent
        raise RuntimeError(
            "opencv-contrib-python is required to select a video bounding box."
        ) from exc

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read first frame from video: {video_path}")
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = frame_rgb.shape
    bytes_per_line = channels * width
    return QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()


class _BoundingBoxCanvas(QWidget):
    def __init__(self, image: QImage, initial_bbox: list[float] | None, parent=None) -> None:
        super().__init__(parent)
        self._image = image
        self._pixmap = QPixmap.fromImage(image)
        self._start_pos: QPoint | None = None
        self._current_rect = self._bbox_to_image_rect(initial_bbox)
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)

    def selected_bbox(self) -> list[float] | None:
        if (
            self._current_rect is None
            or self._current_rect.width() <= 0
            or self._current_rect.height() <= 0
        ):
            return None
        return [
            self._current_rect.left() / self._image.width(),
            self._current_rect.top() / self._image.height(),
            self._current_rect.width() / self._image.width(),
            self._current_rect.height() / self._image.height(),
        ]

    def clear_selection(self) -> None:
        self._current_rect = None
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLOR_WINDOW_BG))
        target_rect = self._target_rect()
        painter.drawPixmap(target_rect, self._pixmap)
        if self._current_rect is not None:
            draw_rect = self._image_rect_to_widget_rect(self._current_rect)
            pen = QPen(QColor(COLOR_WARNING_ICON))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(draw_rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        image_point = self._widget_to_image_point(event.position().toPoint())
        if image_point is None:
            return
        self._start_pos = image_point
        self._current_rect = QRect(image_point, image_point)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._start_pos is None:
            return
        image_point = self._widget_to_image_point(event.position().toPoint())
        if image_point is None:
            return
        self._current_rect = QRect(self._start_pos, image_point).normalized()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._start_pos is None:
            return
        image_point = self._widget_to_image_point(event.position().toPoint())
        if image_point is not None:
            self._current_rect = QRect(self._start_pos, image_point).normalized()
        self._start_pos = None
        self.update()

    def _target_rect(self) -> QRect:
        scaled = self._pixmap.size()
        scaled.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        return QRect(x, y, scaled.width(), scaled.height())

    def _widget_to_image_point(self, point: QPoint) -> QPoint | None:
        target = self._target_rect()
        if not target.contains(point):
            return None
        x_ratio = (point.x() - target.left()) / max(1, target.width())
        y_ratio = (point.y() - target.top()) / max(1, target.height())
        x = int(round(x_ratio * self._image.width()))
        y = int(round(y_ratio * self._image.height()))
        x = max(0, min(x, self._image.width() - 1))
        y = max(0, min(y, self._image.height() - 1))
        return QPoint(x, y)

    def _image_rect_to_widget_rect(self, image_rect: QRect) -> QRect:
        target = self._target_rect()
        left = target.left() + round(image_rect.left() / self._image.width() * target.width())
        top = target.top() + round(image_rect.top() / self._image.height() * target.height())
        width = round(image_rect.width() / self._image.width() * target.width())
        height = round(image_rect.height() / self._image.height() * target.height())
        return QRect(left, top, width, height)

    def _bbox_to_image_rect(self, bbox: list[float] | None) -> QRect | None:
        if not bbox or len(bbox) != 4:
            return None
        x, y, w, h = [float(value) for value in bbox]
        return QRect(
            round(x * self._image.width()),
            round(y * self._image.height()),
            round(w * self._image.width()),
            round(h * self._image.height()),
        ).normalized()


class _BoundingBoxDialog(QDialog):
    def __init__(self, video_path: Path, current_bbox: list[float] | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Subject Bounding Box")
        layout = QVBoxLayout(self)
        image = _load_first_video_frame(video_path)
        self._canvas = _BoundingBoxCanvas(image, current_bbox, self)
        layout.addWidget(self._canvas)
        buttons_row = QHBoxLayout()
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._canvas.clear_selection)
        buttons_row.addWidget(clear_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        from rime_ui.presentation.style import polish_surface

        polish_surface(self)
        self.adjustSize()

    def selected_bbox(self) -> list[float] | None:
        return self._canvas.selected_bbox()


class BoundingBoxEditor(QWidget):
    def __init__(
        self,
        value: list[float] | None,
        video_path_getter,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._value = list(value) if value is not None else None
        self._video_path_getter = video_path_getter

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        select_button = QPushButton("Select...")
        select_button.clicked.connect(self._select_bbox)
        layout.addWidget(select_button)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self._clear_bbox)
        layout.addWidget(clear_button)

        self._refresh_label()

    def value(self) -> list[float] | None:
        return list(self._value) if self._value is not None else None

    def is_empty(self) -> bool:
        return self._value is None

    def _select_bbox(self) -> None:
        video_path = self._video_path_getter()
        if video_path is None:
            QMessageBox.warning(
                self,
                "Select Video First",
                "Choose the model's video source before selecting a bounding box.",
            )
            return
        try:
            dialog = _BoundingBoxDialog(video_path, self._value, self)
        except Exception as exc:
            QMessageBox.critical(self, "Bounding Box Error", str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._value = dialog.selected_bbox()
        self._refresh_label()

    def _clear_bbox(self) -> None:
        self._value = None
        self._refresh_label()

    def _refresh_label(self) -> None:
        if self._value is None:
            self._label.setText("No bounding box selected")
            return
        x, y, w, h = self._value
        self._label.setText(f"x={x:.3f}, y={y:.3f}, w={w:.3f}, h={h:.3f}")
