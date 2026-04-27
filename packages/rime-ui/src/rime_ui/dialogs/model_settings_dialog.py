"""Unified settings dialog for model bindings, parameters, and output mappings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rime_core.cmf import CMFPackage
from rime_core.schema import ProtocolSchema
from rime_core.sessions import ModelSettings, Session
from rime_core.signals import Signal
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
        if self._current_rect is None or self._current_rect.width() <= 0 or self._current_rect.height() <= 0:
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
        self.setMinimumSize(760, 520)
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

    def selected_bbox(self) -> list[float] | None:
        return self._canvas.selected_bbox()


class _BoundingBoxEditor(QWidget):
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
        self._label.setText(
            f"x={x:.3f}, y={y:.3f}, w={w:.3f}, h={h:.3f}"
        )


class ModelSettingsDialog(QDialog):
    """Edit persisted settings for the active model in one place."""

    def __init__(
        self,
        *,
        model: CMFPackage,
        schema: ProtocolSchema,
        session: Session,
        signals: dict[str, Signal],
        settings: ModelSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._schema = schema
        self._session = session
        self._signals = signals
        self._settings = settings

        self._input_editors: dict[str, dict[str, Any]] = {}
        self._parameter_widgets: dict[str, QWidget] = {}
        self._output_editors: list[dict[str, Any]] = []

        self.setWindowTitle(f"{model.name} Settings")
        self.setMinimumSize(560, 520)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        content = QVBoxLayout(container)
        content.setContentsMargins(8, 8, 8, 8)
        content.setSpacing(12)

        if self._model.config.inputs:
            content.addWidget(self._build_inputs_group())
        if self._model.config.parameters:
            content.addWidget(self._build_parameters_group())
        if self._model.config.output_mappings:
            content.addWidget(self._build_outputs_group())
        content.addStretch(1)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_inputs_group(self) -> QGroupBox:
        group = QGroupBox("Inputs")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        for input_config in self._model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            input_type = str(input_config.get("type", "signal")).casefold()
            binding_mode = str(input_config.get("binding_mode", "channel_map")).casefold()
            input_group = QGroupBox(input_name)
            form = QFormLayout(input_group)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

            if input_type == "video":
                source_combo = QComboBox()
                source_combo.addItem("Select video...", None)
                saved_path = self._settings.input_sources.get(input_name)
                current_index = 0
                for index, video in enumerate(self._session.videos, start=1):
                    abs_path = str(self._session.get_video_path(video))
                    label = video.name or video.label or Path(video.path).name
                    source_combo.addItem(label, abs_path)
                    if saved_path == abs_path:
                        current_index = index
                source_combo.setCurrentIndex(current_index)
                form.addRow("Source", source_combo)
                self._input_editors[input_name] = {
                    "type": "video",
                    "source_combo": source_combo,
                }
            else:
                expected_rate = input_config.get(
                    "sampling_rate_hz",
                    input_config.get("sample_rate_hz"),
                )
                source_combo = QComboBox()
                source_combo.addItem("Select signal...", None)
                saved_source = self._settings.input_sources.get(input_name)
                current_index = 0
                for index, (signal_key, signal) in enumerate(self._signals.items(), start=1):
                    label = f"{signal_key} ({signal.sampling_rate_hz:g}Hz, {len(signal.channels)}ch)"
                    if expected_rate is not None and signal.sampling_rate_hz != float(expected_rate):
                        label += f" -> resampled to {float(expected_rate):g}Hz"
                    source_combo.addItem(label, signal_key)
                    if saved_source == signal_key:
                        current_index = index
                source_combo.setCurrentIndex(current_index)
                form.addRow("Source", source_combo)

                if expected_rate is not None:
                    hint = QLabel(
                        f"Required sampling rate: {float(expected_rate):g}Hz. "
                        "Non-matching signals are resampled during inference."
                    )
                    hint.setWordWrap(True)
                    form.addRow("", hint)

                self._input_editors[input_name] = {
                    "type": "signal",
                    "binding_mode": binding_mode,
                    "source_combo": source_combo,
                }
                if binding_mode == "source_only":
                    hint = QLabel(
                        "This model handles channel interpretation internally. Only a source signal is required."
                    )
                    hint.setWordWrap(True)
                    form.addRow("", hint)
                else:
                    channel_combos: dict[str, QComboBox] = {}
                    saved_map = dict(self._settings.input_bindings.get(input_name, {}))
                    for model_channel in [str(channel) for channel in input_config.get("channels", [])]:
                        combo = QComboBox()
                        channel_combos[model_channel] = combo
                        form.addRow(model_channel, combo)
                    self._input_editors[input_name]["channel_combos"] = channel_combos
                    self._input_editors[input_name]["saved_map"] = saved_map
                    source_combo.currentIndexChanged.connect(
                        lambda _index, name=input_name: self._refresh_signal_channel_choices(name)
                    )
                    self._refresh_signal_channel_choices(input_name)

            layout.addWidget(input_group)

        return group

    def _build_parameters_group(self) -> QGroupBox:
        group = QGroupBox("Parameters")
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        for param in self._model.config.parameters:
            name = str(param.get("name", "")).strip()
            if not name:
                continue
            widget = self._create_parameter_widget(param)
            self._parameter_widgets[name] = widget
            label = str(param.get("label") or name)
            description = str(param.get("description", "")).strip()
            if description:
                widget.setToolTip(description)
            form.addRow(label, widget)

        return group

    def _build_outputs_group(self) -> QGroupBox:
        group = QGroupBox("Output Mappings")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)
        saved_mappings = {
            str(item.get("output_name", "")): item
            for item in self._settings.output_mappings
            if isinstance(item, dict)
        }

        for default in self._model.config.output_mappings:
            output_name = default["output_name"]
            output_type = self._output_type(output_name)
            mapping_group = QGroupBox(output_name)
            form = QFormLayout(mapping_group)
            lane_combo = QComboBox()
            label_combo = QComboBox()

            allowed_lanes = self._allowed_lanes(output_type)
            saved = saved_mappings.get(output_name, {})
            current_lane = str(saved.get("lane") or default.get("lane") or "")
            current_label = str(saved.get("label") or default.get("label") or "")

            lane_combo.addItem("Select lane...", None)
            lane_index = 0
            for index, lane_name in enumerate(allowed_lanes, start=1):
                lane_combo.addItem(lane_name, lane_name)
                if lane_name == current_lane:
                    lane_index = index
            lane_combo.setCurrentIndex(lane_index)
            self._populate_label_combo(label_combo, current_lane, current_label)
            lane_combo.currentIndexChanged.connect(
                lambda _index, combo=lane_combo, labels=label_combo: self._populate_label_combo(
                    labels,
                    str(combo.currentData() or ""),
                    str(labels.currentData() or ""),
                )
            )

            form.addRow("Lane", lane_combo)
            form.addRow("Label", label_combo)
            layout.addWidget(mapping_group)
            self._output_editors.append(
                {
                    "output_name": output_name,
                    "lane_combo": lane_combo,
                    "label_combo": label_combo,
                    "default_lane": default["lane"],
                    "default_label": default["label"],
                }
            )

        return group

    def _create_parameter_widget(self, param: dict[str, Any]) -> QWidget:
        name = str(param.get("name", "")).strip()
        param_type = str(param.get("type", "string")).casefold()
        saved_value = self._settings.params.get(name, param.get("default"))
        options = param.get("options")

        if param_type == "bounding_box":
            return _BoundingBoxEditor(saved_value, self._selected_video_path)

        if isinstance(options, list) and options:
            combo = QComboBox()
            for option in options:
                combo.addItem(str(option), str(option))
            current_text = str(saved_value) if saved_value is not None else str(param.get("default", ""))
            index = combo.findData(current_text)
            combo.setCurrentIndex(index if index >= 0 else 0)
            return combo

        if param_type == "bool":
            checkbox = QCheckBox()
            checkbox.setChecked(bool(saved_value))
            return checkbox
        if param_type == "int":
            spin = QSpinBox()
            spin.setRange(int(param.get("min", -1_000_000)), int(param.get("max", 1_000_000)))
            spin.setValue(int(saved_value if saved_value is not None else param.get("default", 0)))
            return spin
        if param_type == "float":
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setSingleStep(0.1)
            spin.setRange(float(param.get("min", -1_000_000.0)), float(param.get("max", 1_000_000.0)))
            spin.setValue(
                float(saved_value if saved_value is not None else param.get("default", 0.0))
            )
            return spin

        line = QLineEdit()
        line.setText("" if saved_value is None else str(saved_value))
        return line

    def _refresh_signal_channel_choices(self, input_name: str) -> None:
        editor = self._input_editors[input_name]
        signal_key = editor["source_combo"].currentData()
        signal = self._signals.get(signal_key) if signal_key else None
        saved_map = editor["saved_map"]
        for model_channel, combo in editor["channel_combos"].items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Select column...", None)
            current_index = 0
            if signal is not None:
                default_column = saved_map.get(model_channel) or self._guess_signal_channel(
                    model_channel,
                    signal.channels,
                )
                for index, channel in enumerate(signal.channels, start=1):
                    combo.addItem(channel, channel)
                    if channel == default_column:
                        current_index = index
            combo.setEnabled(signal is not None)
            combo.setCurrentIndex(current_index)
            combo.blockSignals(False)

    def _populate_label_combo(
        self,
        combo: QComboBox,
        lane_name: str,
        current_label: str,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Select label...", None)
        labels = self._schema.get_labels(lane_name)
        index = 0
        for idx, label in enumerate(labels, start=1):
            combo.addItem(label, label)
            if label == current_label:
                index = idx
        combo.setCurrentIndex(index)
        combo.setEnabled(bool(labels))
        combo.blockSignals(False)

    def _allowed_lanes(self, output_type: str) -> list[str]:
        if output_type == "point":
            lanes = [lane.name for lane in self._schema.lanes if lane.lane_type == "point"]
        else:
            lanes = [lane.name for lane in self._schema.lanes if lane.lane_type == "interval"]
        return lanes or self._schema.get_lane_names()

    def _output_type(self, output_name: str) -> str:
        for output in self._model.config.outputs:
            if str(output.get("name", "")) == output_name:
                return str(output.get("type", "interval")).casefold()
        return "interval"

    @staticmethod
    def _guess_signal_channel(model_channel: str, signal_channels: list[str]) -> str | None:
        normalized = model_channel.casefold()
        suffix_aliases = {
            "ax": ["acc_x", "accel_x", "x"],
            "ay": ["acc_y", "accel_y", "y"],
            "az": ["acc_z", "accel_z", "z"],
            "gx": ["gyr_x", "gyro_x"],
            "gy": ["gyr_y", "gyro_y"],
            "gz": ["gyr_z", "gyro_z"],
        }
        lookup = {channel.casefold(): channel for channel in signal_channels}
        for suffix, aliases in suffix_aliases.items():
            if normalized.endswith(suffix):
                for alias in aliases:
                    if alias in lookup:
                        return lookup[alias]
        if normalized in lookup:
            return lookup[normalized]
        return None

    def _on_accept(self) -> None:
        missing = self._missing_fields()
        if missing:
            QMessageBox.warning(
                self,
                "Incomplete Model Settings",
                "Fill the required settings before continuing:\n- " + "\n- ".join(missing),
            )
            return
        self._apply_to_settings()
        self.accept()

    def _missing_fields(self) -> list[str]:
        missing: list[str] = []
        for input_config in self._model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            editor = self._input_editors[input_name]
            source_value = editor["source_combo"].currentData()
            if not source_value:
                missing.append(f"{input_name}: source")
                continue
            if editor["type"] == "signal" and editor.get("binding_mode") != "source_only":
                for model_channel, combo in editor["channel_combos"].items():
                    if combo.currentData() is None:
                        missing.append(f"{input_name}: {model_channel}")
        for output in self._output_editors:
            if output["lane_combo"].currentData() is None:
                missing.append(f"{output['output_name']}: lane")
                continue
            if output["label_combo"].currentData() is None:
                missing.append(f"{output['output_name']}: label")
        for param in self._model.config.parameters:
            name = str(param.get("name", "")).strip()
            if not name:
                continue
            if str(param.get("type", "string")).casefold() == "bounding_box":
                widget = self._parameter_widgets[name]
                if isinstance(widget, _BoundingBoxEditor) and widget.is_empty():
                    missing.append(f"{name}: bounding box")
        return missing

    def _apply_to_settings(self) -> None:
        for input_config in self._model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            editor = self._input_editors[input_name]
            source_value = editor["source_combo"].currentData()
            if source_value is None:
                self._settings.input_sources.pop(input_name, None)
                self._settings.input_bindings.pop(input_name, None)
                continue
            self._settings.input_sources[input_name] = str(source_value)
            if editor["type"] == "signal" and editor.get("binding_mode") != "source_only":
                channel_map = {
                    model_channel: str(combo.currentData())
                    for model_channel, combo in editor["channel_combos"].items()
                    if combo.currentData() is not None
                }
                self._settings.input_bindings[input_name] = channel_map
            else:
                self._settings.input_bindings.pop(input_name, None)

        self._settings.params = {}
        for param in self._model.config.parameters:
            name = str(param.get("name", "")).strip()
            if not name:
                continue
            widget = self._parameter_widgets[name]
            if isinstance(widget, QCheckBox):
                value: Any = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                value = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                value = widget.value()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, _BoundingBoxEditor):
                value = widget.value()
            else:
                value = widget.text()
            self._settings.params[name] = value

        self._settings.output_mappings = [
            {
                "output_name": output["output_name"],
                "lane": str(output["lane_combo"].currentData()),
                "label": str(output["label_combo"].currentData()),
            }
            for output in self._output_editors
            if output["lane_combo"].currentData() is not None
            and output["label_combo"].currentData() is not None
        ]

    def _selected_video_path(self) -> Path | None:
        for editor in self._input_editors.values():
            if editor.get("type") != "video":
                continue
            value = editor["source_combo"].currentData()
            if value:
                return Path(str(value))
        return None
