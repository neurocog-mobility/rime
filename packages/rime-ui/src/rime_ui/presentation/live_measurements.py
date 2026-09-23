"""Minimal protocol measurement preview and explicit native record export."""

from copy import deepcopy
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Slot, QTimer
from PySide6.QtGui import QPalette, QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QDialog,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QWidget,
    QFormLayout,
    QDialogButtonBox,
    QScrollArea,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QGridLayout,
    QSizePolicy,
)
from rime_core.measurement_capture import settings_for, preview_measurements, capture_measurements
from rime_core.exchange import write_document
from .records import Job
from .components import ContentScrollArea


def value_text(result):
    if result["value"] is None:
        return "Undefined (empty observation)"
    if result["unit"] == "count":
        return f"{result['value']:.0f}"
    return f"{result['value']:.2f}" + ("%" if result["unit"] == "%" else " " + result["unit"])


class LiveMeasurements(QGroupBox):
    def __init__(self, editor):
        super().__init__("Measurements", editor)
        self.editor = editor
        self.duration_ms = None
        self.previews = []
        self.busy = False
        self._job = None
        self.values = QLabel()
        self.values.setWordWrap(True)
        self.values.setTextFormat(Qt.TextFormat.RichText)
        self.values.linkActivated.connect(self.inspect)
        self.scope = QLabel()
        self.scope.setWordWrap(True)
        self.scope.setProperty("role", "muted")
        self.configure_button = QPushButton("Configure…")
        self.configure_button.clicked.connect(self.configure)
        self.save_button = QPushButton("Save records…")
        self.save_button.setToolTip("Save all selected measurement records together in one .rime document.")
        self.save_button.clicked.connect(self.save)
        self.tiles = {}
        if editor.visual_pilot:
            self.setTitle("")
            self.setProperty("workspaceSection", True)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(6)
            heading = QLabel("Measurements")
            heading.setProperty("role", "section")
            layout.addWidget(heading)
            row = QHBoxLayout()
            row.setSpacing(12)
            self.metrics_widget = QWidget()
            self.metrics_widget.setObjectName("measurementTiles")
            self.metrics_layout = QGridLayout(self.metrics_widget)
            self.metrics_layout.setContentsMargins(0, 0, 0, 0)
            self.metrics_layout.setSpacing(8)
            self.metrics_scroll = QScrollArea()
            self.metrics_scroll.setWidgetResizable(True)
            self.metrics_scroll.setWidget(self.metrics_widget)
            self.metrics_scroll.viewport().setAutoFillBackground(False)
            self.metrics_widget.setAutoFillBackground(False)
            self.metrics_scroll.setMinimumHeight(68)
            self.metrics_scroll.setMaximumHeight(72)
            row.addWidget(self.metrics_scroll, 1)
            row.addWidget(self.configure_button)
            self.save_button.setProperty("role", "primaryAction")
            row.addWidget(self.save_button)
            layout.addLayout(row)
            layout.addWidget(self.values)
            self.values.hide()
            layout.addWidget(self.scope)
        else:
            layout = QHBoxLayout(self)
            text = QVBoxLayout()
            text.addWidget(self.values)
            text.addWidget(self.scope)
            layout.addLayout(text, 1)
            layout.addWidget(self.configure_button)
            layout.addWidget(self.save_button)
        self.refresh()

    def refresh(self):
        workspace = self.editor.workspace
        try:
            self.previews = preview_measurements(workspace.data, self.duration_ms)
            link_style = (
                f' style="color: {self.palette().color(QPalette.ColorRole.Link).name()}; text-decoration: none"'
                if self.editor.visual_pilot
                else ""
            )
            self.values.setText(
                "   ·   ".join(
                    f'<a href="{escape(p["id"], quote=True)}"{link_style}>{escape(p["name"])}: {escape(value_text(p["result"]))}</a>'
                    for p in self.previews
                )
                or (
                    "No measures selected"
                    if workspace.schema.measurements
                    else "No measures defined in this protocol"
                )
            )
            mode = settings_for(workspace.data)["period"]["mode"]
            spans = {tuple(tuple(s) for s in p["intervals"]) for p in self.previews}
            period = (
                "Protocol period"
                if mode == "protocol"
                else "Selected annotations"
                if mode == "annotations"
                else "Time range"
            )
            if len(spans) == 1:
                intervals = next(iter(spans))
                seconds = sum(end - start for start, end in intervals) / 1000
                period += f" · {seconds:.6g} s"
            self.scope.setText(
                ("Observation period · " + period)
                if self.previews and self.editor.visual_pilot
                else period
                if self.previews
                else ""
            )
            self.save_button.setEnabled(bool(self.previews) and not self.busy)
        except ValueError as exc:
            self.previews = []
            self.values.setText("Not calculated")
            self.scope.setText(str(exc))
            self.save_button.setEnabled(False)
        if self.editor.visual_pilot:
            self.refresh_tiles()

    def refresh_tiles(self):
        identifiers = [p["id"] for p in self.previews]
        if list(self.tiles) != identifiers:
            while self.metrics_layout.count():
                item = self.metrics_layout.takeAt(0)
                item.widget().deleteLater()
            self.tiles.clear()
            for index, identifier in enumerate(identifiers):
                tile = QPushButton()
                tile.setProperty("role", "metric")
                tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                tile.setMinimumHeight(64)
                content = QVBoxLayout(tile)
                content.setContentsMargins(12, 6, 12, 6)
                content.setSpacing(2)
                caption, value = QLabel(), QLabel()
                caption.setProperty("role", "muted")
                for label in (caption, value):
                    label.setTextFormat(Qt.TextFormat.PlainText)
                    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                    content.addWidget(label)
                font = QFont(value.font())
                font.setPointSizeF((font.pointSizeF() + 6) * 1.18)
                font.setWeight(QFont.Weight.DemiBold)
                value.setFont(font)
                tile.setMinimumHeight(max(64, caption.fontMetrics().height() + value.fontMetrics().height() + 14))
                tile.clicked.connect(
                    lambda checked=False, identifier=identifier: self.inspect(identifier)
                )
                self.tiles[identifier] = (tile, caption, value)
                self.metrics_layout.addWidget(tile, index // 3, index % 3)
                self.metrics_layout.setColumnStretch(index % 3, 1)
        friendly = {
            "covered_duration": "Covered duration",
            "percentage_coverage": "Coverage",
            "count": "Interval count",
        }
        for p in self.previews:
            tile, caption, value = self.tiles[p["id"]]
            name = friendly.get(p["name"], p["name"])
            caption.setText(name)
            result = p["result"]
            display = (
                "Undefined"
                if result["value"] is None
                else value_text(result)
            )
            value.setText(display)
            tile.setAccessibleName(f"{name}: {display}. Inspect measurement")
            tile.setToolTip(
                f"{name}: {value_text(result)}\nSelect to inspect the calculation and contributing annotations."
            )
        self.metrics_scroll.setVisible(bool(self.previews))
        if self.tiles:
            height = max(tile.minimumHeight() for tile, _, _ in self.tiles.values()) + 4
            self.metrics_scroll.setMinimumHeight(height)
            self.metrics_scroll.setMaximumHeight(height + 4)
        self.values.setVisible(not self.previews)

    def inspect(self, identifier):
        self.refresh()
        p = next((p for p in self.previews if p["id"] == identifier), None)
        if p is None:
            return
        d = p["definition"]
        r = p["result"]
        lines = [
            p["name"] + ": " + value_text(r),
            "",
            f"Events: {d['lane']} / {d['label'] or 'all labels'}",
            f"Calculation: {d['operation'].replace('_', ' ')} (version {d['version']})",
            f"Eligible time: {r['eligible_ms'] / 1000:.9g} s",
            f"Covered time: {r['covered_ms'] / 1000:.9g} s",
            "",
            "Observation intervals (s):",
        ]
        lines += [f"{start / 1000:.9g} – {end / 1000:.9g}" for start, end in p["intervals"]]
        lines += ["", "Contributing annotations:"]
        lines += [
            f"{a.lane} / {a.label}: {a.start_ms / 1000:.9g} – {a.end_ms / 1000:.9g} s"
            for a in self.editor.workspace.store.all()
            if a.id in r["contributors"]
        ]
        lines += [
            "",
            ("Measurements use saved reviewer output; unresolved inputs are not included."
             if self.editor.review else
             "No independent review or adjudication is claimed by this annotation workspace."),
        ]
        dialog = QDialog(self)
        dialog.setWindowTitle("Measurement")
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit("\n".join(lines))
        text.setReadOnly(True)
        text.setMinimumWidth(min(560, text.fontMetrics().horizontalAdvance(max(lines, key=len)) + 24))
        text.setMinimumHeight(min(14, len(lines)) * text.fontMetrics().lineSpacing() + 16)
        layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.adjustSize()
        dialog.exec()

    def configure(self):
        dialog = MeasurementConfiguration(self.editor.workspace, self.duration_ms, self)
        if dialog.exec():
            self.editor.workspace.change(
                lambda data: data.update(measurement_settings=dialog.settings())
            )
            self.refresh()
            self.editor.changed.emit()

    def save(self):
        if self.busy:
            return
        self.refresh()
        if not self.previews:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save RIME document", "measurements.rime", "RIME document (*.rime)"
        )
        if not path:
            return
        if Path(path).suffix.lower() != ".rime":
            path += ".rime"
        self.export_path(path)

    def export_path(self, path):
        if self.busy:
            return False
        snapshot = deepcopy(self.editor.workspace.data)
        duration = self.duration_ms
        self.busy = True
        self.save_button.setEnabled(False)
        self.save_button.setText("Saving…")
        self._export_path = str(path)
        self._job = Job(lambda: write_document(path, capture_measurements(snapshot, duration)))
        self._job.signals.finished.connect(self.export_finished, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self._job)
        return True

    @Slot(object, object)
    def export_finished(self, result, error):
        self.busy = False
        self._job = None
        self.save_button.setText("Save records…")
        self.refresh()
        if error:
            QMessageBox.warning(self, "Record not saved", str(error))
        else:
            self.scope.setText("Saved " + Path(self._export_path).name)
            self.scope.setToolTip(self._export_path)


class MeasurementConfiguration(QDialog):
    def __init__(self, workspace, duration_ms, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.duration_ms = duration_ms
        self.setWindowTitle("Measurements")
        state = settings_for(workspace.data)
        root = QVBoxLayout(self)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        self.content = ContentScrollArea(self)
        self.content.setWidget(body)
        root.addWidget(self.content)
        layout.addWidget(QLabel("Protocol measures"))
        self.measures = {}
        for outcome in workspace.schema.measurements:
            box = QCheckBox(outcome.name)
            box.setChecked(outcome.id in state["selected"])
            box.setToolTip(outcome.description)
            self.measures[outcome.id] = box
            layout.addWidget(box)
        layout.addWidget(QLabel("Observation period"))
        self.mode = QComboBox()
        self.mode.addItems(["Protocol period", "Time range", "From annotations"])
        modes = ["protocol", "time", "annotations"]
        self.mode.setCurrentIndex(modes.index(state["period"]["mode"]))
        layout.addWidget(self.mode)
        self.times = QWidget()
        form = QFormLayout(self.times)
        form.setContentsMargins(0, 0, 0, 0)
        self.start, self.end = QDoubleSpinBox(), QDoubleSpinBox()
        for name, spin, value in [
            ("Start", self.start, state["period"].get("start_ms", 0)),
            ("End", self.end, state["period"].get("end_ms", duration_ms or 0)),
        ]:
            spin.setRange(0, (duration_ms or 86400000) / 1000)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setSuffix(" s")
            spin.setValue(value / 1000)
            form.addRow(name, spin)
        layout.addWidget(self.times)
        self.annotation_panel = QWidget()
        panel = QVBoxLayout(self.annotation_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        self.lanes = {}
        for lane in workspace.schema.lanes:
            if lane.lane_type != "interval":
                continue
            box = QCheckBox(lane.name)
            box.setChecked(lane.name in state["period"].get("lanes", []))
            self.lanes[lane.name] = box
            panel.addWidget(box)
        self.all = QCheckBox("All annotations in selected lanes")
        self.all.setChecked(state["period"].get("all", True))
        panel.addWidget(self.all)
        scroll = ContentScrollArea()
        self.item_scroll = scroll
        items = QWidget()
        self.item_layout = QVBoxLayout(items)
        self.item_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(items)
        panel.addWidget(scroll)
        self.items = {}
        for a in workspace.store.all():
            if a.event_type != "interval":
                continue
            box = QCheckBox(f"{a.lane} / {a.label} · {a.start_ms / 1000:g}–{a.end_ms / 1000:g} s")
            box.setChecked(a.id in state["period"].get("ids", []))
            self.items[a.id] = (a.lane, box)
            self.item_layout.addWidget(box)
        layout.addWidget(self.annotation_panel)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.hide()
        root.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self.visibility)
        self.all.toggled.connect(self.visibility)
        for box in self.lanes.values():
            box.toggled.connect(self.visibility)
        self.visibility()

    def visibility(self, *_):
        self.times.setVisible(self.mode.currentIndex() == 1)
        self.annotation_panel.setVisible(self.mode.currentIndex() == 2)
        for lane, box in self.items.values():
            box.setVisible(self.lanes[lane].isChecked() and not self.all.isChecked())
        self.item_scroll.setVisible(
            not self.all.isChecked() and any(not box.isHidden() for _, box in self.items.values())
        )
        self.item_layout.invalidate()
        self.item_scroll.updateGeometry()
        self.content.widget().layout().activate()
        self.content.updateGeometry()
        self.layout().activate()
        QTimer.singleShot(0, self, self.adjustSize)

    def settings(self):
        period = {"mode": ["protocol", "time", "annotations"][self.mode.currentIndex()]}
        if period["mode"] == "time":
            period.update(start_ms=self.start.value() * 1000, end_ms=self.end.value() * 1000)
        elif period["mode"] == "annotations":
            period.update(
                lanes=[lane for lane, box in self.lanes.items() if box.isChecked()],
                all=self.all.isChecked(),
                ids=[
                    key
                    for key, (lane, box) in self.items.items()
                    if box.isChecked() and self.lanes[lane].isChecked()
                ],
            )
        return {
            "selected": [key for key, box in self.measures.items() if box.isChecked()],
            "period": period,
        }

    def apply(self):
        try:
            preview_measurements(self.workspace.data, self.duration_ms, self.settings())
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            self.adjustSize()
            return
        self.accept()
