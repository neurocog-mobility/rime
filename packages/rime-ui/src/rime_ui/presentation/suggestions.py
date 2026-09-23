"""Scoped CMF execution and review on the annotation evidence timeline."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QWidget,
    QHBoxLayout,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
)
from rime_core.annotations import Annotation
from rime_core.cmf import CMFLoader
from rime_core.suggestions import pending, execute, admit, decide, revise
from rime_ui.dialogs.model_loader_dialog import ModelLoaderDialog
from .records import Job
from .components import ContentScrollArea


def package_summary(editor, package):
    """Check protocol output compatibility before admitting a package to the runner."""
    dialog = ModelLoaderDialog(package, editor)
    dialog.load_button.setText("Accept")
    reasons = []
    for output in package.config.outputs:
        kind = "point" if output.get("type") == "point" else "interval"
        if not any(lane.lane_type == kind for lane in editor.workspace.schema.lanes):
            reasons.append(
                f"Output '{output['name']}' requires a {kind} lane, "
                "but this workspace's protocol defines none."
            )
    if reasons:
        message = QLabel("Model incompatible with this workspace.\n" + "\n".join(reasons))
        message.setWordWrap(True)
        dialog.layout().insertWidget(0, message)
        dialog.load_button.setEnabled(False)
        dialog.load_button.setToolTip("\n".join(reasons))
    return dialog


class PackagePicker(QFileDialog):
    """One picker accepts both unpacked CMF folders and CMF archives."""

    def __init__(self, parent):
        super().__init__(parent, "Open CMF package")
        self.setOption(QFileDialog.Option.DontUseNativeDialog)
        self.setFileMode(QFileDialog.FileMode.AnyFile)
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        self.setNameFilter("CMF packages (*.cmf)")

    def accept(self):
        paths = self.selectedFiles()
        if paths and Path(paths[0]).suffix.lower() == ".cmf" and Path(paths[0]).exists():
            self.done(QDialog.DialogCode.Accepted)
        else:
            super().accept()


def choose_package(parent):
    dialog = PackagePicker(parent)
    return dialog.selectedFiles()[0] if dialog.exec() == QDialog.DialogCode.Accepted else ""


class RunConfiguration(QDialog):
    def __init__(self, editor, package):
        super().__init__(editor)
        self.setWindowTitle("Run model")
        self.editor, self.package = editor, package
        root = QVBoxLayout(self)
        area = ContentScrollArea()
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        area.setWidget(body)
        root.addWidget(area)
        self.bindings, self.outputs, self.parameters, self.execution = [], [], [], {}
        for spec in package.config.inputs:
            source = QComboBox()
            kind = spec.get("type", "signal")
            for item in editor.workspace.data["sources"]:
                if item["kind"] == kind:
                    source.addItem(Path(item["path"]).name, item["config"]["id"])
            form.addRow(spec["name"], source)
            channels = {}
            for channel in spec.get("channels", []):
                field = QComboBox()
                channels[channel] = field
                form.addRow("  " + channel, field)

            def update_channels(_=None, source=source, channels=channels):
                signal = editor.loaded_signals.get(source.currentData())
                for name, field in channels.items():
                    field.clear()
                    field.addItem("Select channel…", None)
                    field.addItems(signal.channels if signal else [])
                    if field.findText(name) >= 0:
                        field.setCurrentText(name)

            source.currentIndexChanged.connect(update_channels)
            update_channels()
            self.bindings.append((spec["name"], source, channels))
        for spec in package.config.outputs:
            lane = QComboBox()
            label = QComboBox()
            expected = "point" if spec.get("type") == "point" else "interval"
            lane.addItems(
                [item.name for item in editor.workspace.schema.lanes if item.lane_type == expected]
            )

            def update_labels(_=None, lane=lane, label=label):
                label.clear()
                config = editor.workspace.schema.get_lane(lane.currentText())
                if config:
                    label.addItems(config.labels)

            lane.currentIndexChanged.connect(update_labels)
            update_labels()
            for mapping in package.config.output_mappings:
                if mapping["output_name"] == spec["name"]:
                    lane.setCurrentText(mapping["lane"])
                    label.setCurrentText(mapping["label"])
            form.addRow(spec["name"] + " → lane", lane)
            form.addRow("Label", label)
            self.outputs.append((spec["name"], lane, label))
            if lane.count() == 0:
                detail = (
                    f"Model incompatible with this workspace: output '{spec['name']}' "
                    f"requires a {expected} lane, but the protocol defines none."
                )
                lane.setPlaceholderText(f"No compatible {expected} lane")
                lane.setEnabled(False)
                label.setEnabled(False)
                lane.setToolTip(detail)
                label.setToolTip(detail)
                message = QLabel(detail)
                message.setWordWrap(True)
                form.addRow(message)

        for name, caption, value in [
            ("start", "Start (s)", 0),
            ("end", "End (s)", editor.duration / 1000),
        ]:
            field = QDoubleSpinBox()
            field.setDecimals(3)
            field.setRange(0, editor.duration / 1000)
            field.setSingleStep(0.05)
            field.setValue(value)
            setattr(self, name, field)
            form.addRow(caption, field)
        fields = [
            ("threshold", "Threshold", 0, 1),
            ("merge_gap_ms", "Bridge gaps (ms)", 0, 1e6),
            ("min_duration_ms", "Minimum duration (ms)", 0, 1e6),
        ]
        if package.config.inference_mode == "windowed":
            fields = [
                ("window_size_ms", "Window (ms)", 1, 1e6),
                ("stride_ms", "Update interval (ms)", 1, 1e6),
            ] + fields
        for name, caption, low, high in fields:
            field = QDoubleSpinBox()
            field.setDecimals(3)
            field.setRange(low, high)
            field.setValue(getattr(package.config, name))
            form.addRow(caption, field)
            self.execution[name] = field
        for spec in package.config.parameters:
            value = spec.get("default")
            kind = spec.get("type", "string")
            if kind == "bounding_box":
                from rime_ui.dialogs.bounding_box_editor import BoundingBoxEditor

                field = BoundingBoxEditor(value, self.selected_video)
            elif spec.get("options"):
                field = QComboBox()
                for option in spec["options"]:
                    field.addItem(str(option), option)
                field.setCurrentIndex(max(0, field.findData(value)))
            elif kind == "bool":
                field = QCheckBox()
                field.setChecked(bool(value))
            elif kind in ("int", "float"):
                field = QSpinBox() if kind == "int" else QDoubleSpinBox()
                if kind == "float":
                    field.setDecimals(6)
                    field.setSingleStep(0.1)
                field.setRange(spec.get("min", -1000000), spec.get("max", 1000000))
                field.setValue(value or 0)
            else:
                field = QLineEdit(str(value or ""))
            field.setToolTip(spec.get("description", ""))
            form.addRow(spec.get("label", spec["name"]), field)
            self.parameters.append((spec, field))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        run = buttons.addButton("Run", QDialogButtonBox.ButtonRole.AcceptRole)
        run.setEnabled(all(lane.count() > 0 for _, lane, _ in self.outputs))
        if not run.isEnabled():
            run.setToolTip(
                "The workspace protocol has no compatible lane for one or more model outputs."
            )
        run.clicked.connect(self.submit)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.adjustSize()

    def selected_video(self):
        for _, combo, _ in self.bindings:
            for source in self.editor.workspace.data["sources"]:
                if source["kind"] == "video" and source["config"]["id"] == combo.currentData():
                    return Path(source["path"])
        return None

    def submit(self):
        try:
            if self.start.value() >= self.end.value():
                raise ValueError("End must be after start.")
            bindings = [
                dict(
                    name=name,
                    source=source.currentData(),
                    channels={
                        k: v.currentText() if v.currentIndex() > 0 else ""
                        for k, v in channels.items()
                    },
                )
                for name, source, channels in self.bindings
            ]
            if any(not b["source"] for b in bindings):
                raise ValueError("Choose a source for every input.")
            if any(not channel for b in bindings for channel in b["channels"].values()):
                raise ValueError("Choose every required signal channel explicitly.")
            mappings = [
                dict(output_name=name, lane=lane.currentText(), label=label.currentText())
                for name, lane, label in self.outputs
            ]
            if any(not m["label"] for m in mappings):
                raise ValueError("Choose an output lane and label.")
            params = {}
            for spec, field in self.parameters:
                if isinstance(field, QComboBox):
                    value = field.currentData()
                elif isinstance(field, QCheckBox):
                    value = field.isChecked()
                elif isinstance(field, QLineEdit):
                    value = field.text()
                else:
                    value = field.value()
                if spec.get("type") == "bounding_box" and value is None:
                    raise ValueError("Select the subject bounding box.")
                if spec.get("type") in ("int", "float"):
                    if isinstance(value, bool) or not isinstance(value, (float, int)):
                        raise ValueError(f"{spec['name']} must be numeric.")
                    if spec["type"] == "int" and int(value) != value:
                        raise ValueError("Integer required.")
                    if not spec.get("min", float("-inf")) <= value <= spec.get("max", float("inf")):
                        raise ValueError(f"{spec['name']} is outside its allowed range.")
                params[spec["name"]] = value
            self.arguments = (
                bindings,
                mappings,
                params,
                [self.start.value() * 1000, self.end.value() * 1000],
            )
            self.package.config = replace(
                self.package.config, **{k: v.value() for k, v in self.execution.items()}
            )
        except Exception as exc:
            QMessageBox.warning(self, "Model settings", str(exc))
            return
        self.accept()


class SuggestionFlow(QObject):
    def __init__(self, editor, button, root):
        super().__init__(editor)
        self.editor, self.button = editor, button
        self.busy = False
        self.selected = None
        self.strip = QWidget()
        row = QHBoxLayout(self.strip)
        row.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        row.addWidget(self.status)
        row.addStretch()
        for title, slot in [
            ("Previous", lambda: self.move(-1)),
            ("Next", lambda: self.move(1)),
            ("Accept", lambda: self.decision("accept")),
            ("Modify", self.modify),
            ("Reject", lambda: self.decision("reject")),
            ("Finish review", self.finish),
        ]:
            b = QPushButton(title)
            b.clicked.connect(slot)
            row.addWidget(b)
        root.insertWidget(2, self.strip)
        button.clicked.connect(self.start)
        editor.lanes.annotation_selected.connect(self.select)
        self.refresh()

    def refresh(self):
        items = pending(self.editor.workspace.data)
        ids = [i["annotation"]["id"] for _, i in items]
        if self.selected not in ids:
            self.selected = ids[0] if ids else None
        self.strip.setVisible(bool(items))
        if items:
            index = ids.index(self.selected)
            self.status.setText(f"{items[index][0]['name']} · {index + 1} of {len(items)}")
        self.button.setEnabled(not self.busy and not items)
        self.button.setText("Running…" if self.busy else "Run model…")

    def select(self, identifier):
        if any(i["annotation"]["id"] == identifier for _, i in pending(self.editor.workspace.data)):
            self.selected = identifier
            self.refresh()

    def move(self, direction):
        ids = [i["annotation"]["id"] for _, i in pending(self.editor.workspace.data)]
        if ids:
            self.selected = ids[(ids.index(self.selected) + direction) % len(ids)]
            self.editor.lanes.select_annotation(self.selected)
            self.editor.seek(self.current().start_ms)
            self.refresh()

    def current(self):
        return Annotation(
            **next(
                i.get("draft", i["annotation"])
                for _, i in pending(self.editor.workspace.data)
                if i["annotation"]["id"] == self.selected
            )
        )

    def decision(self, action, annotation=None):
        if self.selected:
            self.editor.mutate(
                lambda: decide(self.editor.workspace, self.selected, action, annotation)
            )

    def modify(self):
        if self.selected:
            self.editor.annotation_dialog(
                self.current(), lambda a: revise(self.editor.workspace, self.selected, a)
            )

    def finish(self):
        box = QMessageBox(self.editor)
        box.setWindowTitle("Finish review")
        box.setText("Finish reviewing the remaining suggestions?")
        resume = box.addButton("Continue review", QMessageBox.ButtonRole.RejectRole)
        accept = box.addButton("Accept remaining", QMessageBox.ButtonRole.AcceptRole)
        reject = box.addButton("Reject remaining", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(resume)
        box.setEscapeButton(resume)
        box.exec()
        clicked = box.clickedButton()
        if clicked is accept or clicked is reject:
            action = "accept" if clicked is accept else "reject_remaining"
            for _, item in list(pending(self.editor.workspace.data)):
                decide(self.editor.workspace, item["annotation"]["id"], action)
            self.editor.refresh()
            self.editor.changed.emit()

    def start(self):
        path = choose_package(self.editor)
        while path:
            try:
                package = CMFLoader.load(Path(path))
            except Exception as exc:
                self.editor.error(exc)
                return
            summary = package_summary(self.editor, package)
            reopen = QPushButton("Open…")
            summary.layout().itemAt(summary.layout().count() - 1).layout().insertWidget(0, reopen)
            reopen.clicked.connect(lambda: summary.done(2))
            result = summary.exec()
            if result == 2:
                path = choose_package(self.editor)
                continue
            if result != QDialog.DialogCode.Accepted:
                return
            config = RunConfiguration(self.editor, package)
            if config.exec() != QDialog.DialogCode.Accepted:
                return
            self.run(package, *config.arguments)
            return

    def run(self, package, bindings, mappings, params, time_range):
        data = deepcopy(self.editor.workspace.data)
        self.busy = True
        self.refresh()
        self.job = Job(lambda: execute(package, data, bindings, mappings, params, time_range))
        self.job.signals.finished.connect(self.completed)
        QThreadPool.globalInstance().start(self.job)

    @Slot(object, object)
    def completed(self, result, error):
        self.busy = False
        if error:
            self.editor.error(error)
        else:
            try:
                admit(self.editor.workspace, result)
            except Exception as exc:
                self.editor.error(exc)
            else:
                if not result["suggestions"]:
                    QMessageBox.information(
                        self.editor, "Model", "No suggestions in the selected period."
                    )
                self.editor.changed.emit()
        self.editor.refresh()
