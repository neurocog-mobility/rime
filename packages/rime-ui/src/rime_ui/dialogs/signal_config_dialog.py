"""Signal configuration confirmation dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rime_core.sessions import SignalConfig
from rime_core.signals import detect_signal_config


class SignalConfigDialog(QDialog):
    """Confirm or override inferred signal metadata before adding a file."""

    def __init__(
        self,
        signal_path: str | Path,
        stored_path: str,
        detected: dict[str, object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._signal_path = Path(signal_path)
        self._stored_path = stored_path
        self._detected = detected
        self._detected_channels = [str(channel) for channel in detected.get("channels", [])]
        self._columns = [str(column) for column in detected.get("columns", [])]
        self._display_channel_boxes: list[QCheckBox] = []

        self.setWindowTitle(f"Add Signal: {self._signal_path.name}")
        self.setMinimumWidth(520)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"Adding: {self._signal_path.name}"))

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.time_column_combo = QComboBox()
        self.time_column_combo.setEditable(True)
        if self._columns:
            self.time_column_combo.addItems(self._columns)
        else:
            self.time_column_combo.addItem("time")
        time_column = str(self._detected.get("time_column", "time"))
        self.time_column_combo.setCurrentText(time_column)
        form.addRow("Time column:", self.time_column_combo)

        self.sampling_rate_spin = QDoubleSpinBox()
        self.sampling_rate_spin.setDecimals(2)
        self.sampling_rate_spin.setRange(0.01, 100000.0)
        self.sampling_rate_spin.setValue(float(self._detected.get("sampling_rate_hz", 100.0)))
        self.sampling_rate_spin.setSuffix(" Hz")
        form.addRow("Sampling rate:", self.sampling_rate_spin)

        self.time_reference_combo = QComboBox()
        self.time_reference_combo.addItems(["relative", "utc_epoch", "sample_index"])
        form.addRow("Time reference:", self.time_reference_combo)

        self.time_unit_combo = QComboBox()
        self.time_unit_combo.addItems(["seconds", "milliseconds", "microseconds", "nanoseconds"])
        self.time_unit_combo.setCurrentText(str(self._detected.get("time_unit", "seconds")))
        form.addRow("Time unit:", self.time_unit_combo)

        layout.addLayout(form)
        layout.addWidget(self._build_available_channels_box())
        layout.addWidget(self._build_display_channels_box())

        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self.accept)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(add_btn)
        layout.addLayout(button_row)

    def _build_available_channels_box(self) -> QGroupBox:
        box = QGroupBox("Available Channels")
        layout = QVBoxLayout(box)

        if not self._detected_channels:
            layout.addWidget(QLabel("No channels auto-detected."))
            return box

        for channel in self._detected_channels:
            checkbox = QCheckBox(channel)
            checkbox.setChecked(True)
            checkbox.setEnabled(False)
            layout.addWidget(checkbox)

        return box

    def _build_display_channels_box(self) -> QGroupBox:
        box = QGroupBox("Display Channels")
        layout = QVBoxLayout(box)

        if not self._detected_channels:
            layout.addWidget(QLabel("Select display channels after loading this signal."))
            return box

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        for channel in self._detected_channels:
            checkbox = QCheckBox(channel)
            self._display_channel_boxes.append(checkbox)
            container_layout.addWidget(checkbox)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        return box

    def to_signal_config(self) -> SignalConfig:
        """Build a signal config from the dialog state."""
        return SignalConfig(
            path=self._stored_path,
            name=self._signal_path.stem,
            type="imu",
            format="csv",
            sampling_rate_hz=self.sampling_rate_spin.value(),
            time_column=self.time_column_combo.currentText().strip() or "time",
            time_reference=self.time_reference_combo.currentText(),
            time_unit=self.time_unit_combo.currentText(),
            offset_ms=0.0,
            channels=list(self._detected_channels),
            display_channels=[
                checkbox.text() for checkbox in self._display_channel_boxes if checkbox.isChecked()
            ],
        )

    @classmethod
    def configure_signal(
        cls,
        signal_path: str | Path,
        stored_path: str,
        parent: QWidget | None = None,
    ) -> SignalConfig | None:
        """Run the dialog and return a confirmed signal config."""
        try:
            detected = detect_signal_config(signal_path)
        except Exception as exc:
            QMessageBox.critical(parent, "Signal Error", f"Failed to inspect signal file:\n{exc}")
            return None

        dialog = cls(signal_path=signal_path, stored_path=stored_path, detected=detected, parent=parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.to_signal_config()
