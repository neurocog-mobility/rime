"""Native read-only RIME inspector. Workspaces and media are deliberately separate."""

from dataclasses import dataclass
from functools import partial
import json
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QWidget,
    QSplitter,
    QMainWindow,
    QPlainTextEdit,
    QFileDialog,
    QMessageBox,
)
from rime_core.exchange import read_document
from rime_core.record_inspection import (
    inspection_graph,
    measurement_summaries,
    node_title,
    verify_record,
    format_result,
)
from .record_graph import RecordGraph
from .components import label, button, column, row, combo, WorkspaceSection
from .style import polish_surface, section_font


@dataclass
class OpenDocument:
    path: Path
    document: object
    summaries: list
    index: int = 0

    @property
    def selected(self):
        return self.summaries[self.index]


def load_document(path):
    path = Path(path).expanduser().resolve()
    document = read_document(path)
    return OpenDocument(path, document, measurement_summaries(document))


def build_graph(documents):
    a = documents[0]
    if len(documents) == 1:
        return inspection_graph(a.document, a.selected["root"])
    b = documents[1]
    return inspection_graph(a.document, a.selected["root"], b.document, b.selected["root"])


class JobSignals(QObject):
    finished = Signal(object, object)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            self.signals.finished.emit(None, str(exc))
        else:
            self.signals.finished.emit(result, None)


def readable(data, level=0):
    """Plain retained fields. Null remains null; missing history is never inferred."""
    lines = []
    indent = "  " * level
    if isinstance(data, dict):
        for key, value in data.items():
            title = key.replace("_", " ").capitalize()
            if (
                key == "annotations"
                and isinstance(value, list)
                and all(
                    isinstance(a, dict)
                    and {"lane", "label", "start_ms", "end_ms", "event_type", "id"} <= a.keys()
                    for a in value
                )
            ):
                lines.append(indent + f"Annotations ({len(value)}):")
                for a in value:
                    lines.append(
                        indent
                        + f"  {a['lane']} / {a['label']} · {a['start_ms'] / 1000:.12g}–{a['end_ms'] / 1000:.12g} s · {a['event_type']} · {a['id']}"
                    )
            elif isinstance(value, (list, dict)):
                lines.append(indent + title + ":")
                lines.extend(readable(value, level + 1))
            else:
                text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                lines.append(indent + title + ": " + text)
    elif isinstance(data, list):
        if not data:
            lines.append(indent + "[]")
        for value in data:
            if isinstance(value, dict):
                lines.extend(readable(value, level))
                lines.append("")
            else:
                lines.append(indent + json.dumps(value, ensure_ascii=False))
    return lines


class RecordView(QWidget):
    verify_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        root = column(self, 8)
        self.value = label("", wrap=False)
        self.value.setFont(section_font(self, prominent=True))
        self.scope = label("")
        root.addLayout(row(self.value, self.scope, None))
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(self.splitter, 1)
        panel = WorkspaceSection("Derivation")
        layout = panel.body
        self.details_button = button("Details", self.toggle_details)
        self.details_button.setCheckable(True)
        self.legend = label("Green: matching · Red: different · Grey: unavailable")
        panel.header.addStretch()
        panel.header.addWidget(self.details_button)
        layout.addWidget(self.legend)
        self.graph = RecordGraph()
        layout.addWidget(self.graph, 1)
        layout.addLayout(
            row(
                button("−", lambda: self.graph.zoom(1 / 1.2)),
                button("+", lambda: self.graph.zoom(1.2)),
                button("Fit", self.graph.fit),
                None,
                button("Expand all", self.graph.expand_all),
                button("Verify calculation", self.verify_requested.emit),
            )
        )
        self.splitter.addWidget(panel)
        self.details = WorkspaceSection("Selected node details")
        self.details.setMinimumHeight(100)
        self.details.setMaximumHeight(190)
        details = self.details.body
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        details.addWidget(self.text)
        self.splitter.addWidget(self.details)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setSizes([420, 150])
        self.graph.node_selected.connect(self.node)
        self.details.hide()

    def set_model(self, model, documents):
        self.model = model
        summaries = [d.selected for d in documents]
        self.value.setText(
            "    ".join(
                (("AB"[i] + ": ") if len(summaries) == 2 else "") + s["value"]
                for i, s in enumerate(summaries)
            )
        )
        self.value.show()
        scopes = [s["observation"] for s in summaries]
        if len(scopes) == 1 or scopes[0] == scopes[1]:
            intervals = scopes[0]
            text = (
                f"{intervals[0][0] / 1000:.8g}–{intervals[0][1] / 1000:.8g} s"
                if len(intervals) == 1
                else f"{len(intervals)} observation intervals"
            )
        else:
            text = "Observation periods differ"
        self.scope.setText(text)
        self.scope.show()
        self.legend.setVisible(model["comparison"])
        self.graph.set_model(model)
        self.node(next(iter(model["roots"].values())))
        self.details.hide()
        self.details_button.setChecked(False)

    def toggle_details(self):
        self.details.setVisible(self.details_button.isChecked())
        QTimer.singleShot(0, self.graph.fit)

    def node(self, key):
        node = next(n for n in self.model["nodes"] if n["id"] == key)
        lines = [node_title(next(iter(node["originals"].values()))), ""]
        if node.get("display_equivalence"):
            lines += [
                "Equal measurement value and definition; retained calculation details may differ.",
                "",
            ]
        component = node.get("comparison")
        if component:
            lines += ["Comparison", ""]
            for attribute in component.get("attributes", []):
                if attribute["status"] != "equal":
                    lines += [attribute["path"] + " · " + attribute["status"]]
                    for side in ("a", "b"):
                        if attribute.get("present_" + side, side in attribute):
                            lines.append(
                                side.upper()
                                + ": "
                                + json.dumps(attribute.get(side), ensure_ascii=False)
                            )
                    lines.append("")
        if key in self.model["roots"].values() and self.model["comparison"]:
            numeric = self.model["numerical_comparison"]
            if numeric["status"] == "applicable":
                lines += [
                    f"Difference B − A: {numeric['signed_difference_b_minus_a']:.12g} {numeric['unit_a']}",
                    f"Absolute difference: {numeric['absolute_difference']:.12g} {numeric['unit_a']}",
                    "",
                ]
            else:
                lines += ["Numerical comparison not applicable", *readable(numeric["reasons"]), ""]
            lines += readable(
                {
                    "alignment_issues": self.model["alignment_issues"],
                    "warnings": self.model["warnings"],
                }
            )
        for side, original in node["originals"].items():
            lines += [
                ("Record " + side.upper()) if self.model["comparison"] else "Retained information",
                original["@id"],
                *readable(original["rime:data"]),
                "",
                "Relations",
            ]
            for edge in self.model["edges"]:
                if edge["source"] != key or side not in edge["sides"]:
                    continue
                target = next(n for n in self.model["nodes"] if n["id"] == edge["target"])
                raw = target["originals"][side]
                lines += [
                    edge["relation"].removeprefix("prov:") + " → " + node_title(raw),
                    "  " + raw["@id"],
                ]
                if edge["role"]:
                    lines.append("  Role: " + edge["role"].removeprefix("rime:"))
                lines += readable(edge["originals"][side]["attributes"], 1)
                if edge.get("display_omitted"):
                    lines.append("  Graph display: " + edge["display_omitted"])
            lines.append("")
        self.text.setPlainText("\n".join(lines))
        self.details.show()
        self.details_button.setChecked(True)


class RecordsView(QWidget):
    open_requested = Signal()
    documents_changed = Signal(int)
    message = Signal(str)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.documents = []
        self.busy = False
        self.closed = False
        self._job = None
        root = column(self, 8)
        self.open_button = button("Open…", self.open_requested.emit)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)
        root.addLayout(row(label("Measurement records", "heading", wrap=False), None, self.open_button))
        root.addWidget(label("Inspect a result and its derivation; open a second document to compare.", "muted"))
        self.rows = WorkspaceSection("Documents & measurements")
        self.document_rows = self.rows.body
        root.addWidget(self.rows)
        self.empty = label("Open a .rime document.")
        root.addWidget(self.empty)
        self.record = RecordView()
        root.addWidget(self.record, 1)
        self.record.hide()
        self.record.verify_requested.connect(self.verify)
        polish_surface(self)

    def submit(self, function, finished, message):
        if self.busy or self.closed:
            return False
        self.busy = True
        self._finished = finished
        self.open_button.setEnabled(False)
        self.rows.setEnabled(False)
        self.record.setEnabled(False)
        self.message.emit(message)
        self.documents_changed.emit(len(self.documents))
        self._job = Job(function)
        self._job.signals.finished.connect(self.job_finished, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self._job)
        return True

    @Slot(object, object)
    def job_finished(self, result, error):
        self.busy = False
        self._job = None
        if self.closed:
            return
        self.open_button.setEnabled(len(self.documents) < 2)
        self.rows.setEnabled(True)
        self.record.setEnabled(True)
        self.documents_changed.emit(len(self.documents))
        if error:
            self.message.emit("Operation failed; opened records unchanged.")
            self.error.emit(error)
            return
        self._finished(result)

    def open_path(self, path):
        if len(self.documents) >= 2 or self.busy:
            return False
        existing = list(self.documents)

        def load():
            loaded = load_document(path)
            if existing:
                title = existing[0].selected["title"]
                loaded.index = next(
                    (i for i, s in enumerate(loaded.summaries) if s["title"] == title), 0
                )
            documents = existing + [loaded]
            return documents, build_graph(documents)

        def complete(result):
            self.documents, model = result
            self.refresh_rows()
            self.display(model)

        return self.submit(load, complete, "Opening and validating record…")

    def refresh_rows(self):
        while self.document_rows.count():
            item = self.document_rows.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.selectors, self.remove_buttons = [], []
        for i, document in enumerate(self.documents):
            widget = QWidget()
            layout = row()
            layout.setContentsMargins(0, 0, 0, 0)
            widget.setLayout(layout)
            name = label(f"{'AB'[i]} · {document.path.name}", wrap=False)
            name.setMaximumWidth(210)
            name.setToolTip(str(document.path))
            layout.addWidget(name)
            selector = combo([s["title"] for s in document.summaries])
            selector.setCurrentIndex(document.index)
            selector.currentIndexChanged.connect(partial(self.select, i))
            layout.addWidget(selector, 1)
            remove = button("×", partial(self.remove_document, i))
            remove.setFixedWidth(26)
            remove.setToolTip("Remove document")
            remove.setAccessibleName("Remove " + document.path.name)
            layout.addWidget(remove)
            self.selectors.append(selector)
            self.remove_buttons.append(remove)
            self.document_rows.addWidget(widget)
        self.open_button.setEnabled(len(self.documents) < 2)
        self.open_button.setToolTip(
            "Two documents maximum" if len(self.documents) == 2 else "Open a RIME document"
        )
        polish_surface(self)
        self.documents_changed.emit(len(self.documents))

    def display(self, model):
        self.empty.hide()
        self.record.show()
        self.record.set_model(model, self.documents)
        numerical = model.get("numerical_comparison")
        message = "Validated · read-only"
        if numerical and numerical["status"] != "applicable":
            message += " · Numerical comparison not applicable (see result details)"
        if model["alignment_issues"] or model["warnings"]:
            message += " · Comparison notes in result details"
        self.message.emit(message)
        QTimer.singleShot(0, self.record.graph.fit)

    def select(self, index, measurement):
        if self.busy or measurement < 0:
            return
        previous = self.documents[index].index
        self.documents[index].index = measurement
        documents = list(self.documents)

        def build():
            try:
                return build_graph(documents), None
            except Exception as exc:
                return None, str(exc)

        def complete(result):
            model, error = result
            if error:
                self.documents[index].index = previous
                self.refresh_rows()
                self.error.emit(error)
                self.message.emit("Comparison failed; previous selection retained.")
            else:
                self.display(model)

        self.submit(
            build, complete, "Comparing records…" if len(documents) == 2 else "Reading measurement…"
        )

    def remove_document(self, index):
        if self.busy:
            return
        remaining = [d for i, d in enumerate(self.documents) if i != index]
        if not remaining:
            self.documents = []
            self.refresh_rows()
            self.record.hide()
            self.empty.show()
            self.message.emit("Open a .rime document.")
            return

        def complete(model):
            self.documents = remaining
            self.refresh_rows()
            self.display(model)

        self.submit(lambda: build_graph(remaining), complete, "Reading measurement…")

    def verify(self):
        documents = list(self.documents)

        def work():
            return [verify_record(d.document, d.selected["root"]) for d in documents]

        def complete(results):
            lines = []
            for i, result in enumerate(results):
                status = "matches" if result["matches"] else "does not match"
                lines.append(
                    f"{'AB'[i]}: recalculated {format_result(result['recalculated'])} {status} saved result"
                )
            self.message.emit(" · ".join(lines))

        self.submit(work, complete, "Recalculating from retained intervals…")


class RecordWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(860, 740)
        self.setMinimumSize(580, 520)
        self.records = RecordsView()
        self.setCentralWidget(self.records)
        menu = self.menuBar().addMenu("File")
        self.open_action = menu.addAction("Open…", self.open_file, QKeySequence.StandardKey.Open)
        menu.addAction("Close", self.close, QKeySequence.StandardKey.Close)
        self.records.open_requested.connect(self.open_file)
        self.records.documents_changed.connect(self.update_documents)
        self.records.message.connect(self.statusBar().showMessage)
        self.records.error.connect(self.show_error)
        self.error_dialog = None
        self.update_documents(0)
        self.statusBar().showMessage("Open a .rime document.")

    def update_documents(self, count):
        self.open_action.setEnabled(count < 2 and not self.records.busy)
        title = (
            self.records.documents[0].path.name
            if count == 1
            else "Record overlay"
            if count == 2
            else "Records"
        )
        self.setWindowTitle(title + " · RIME")

    def open_file(self):
        if self.records.busy or len(self.records.documents) >= 2:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open RIME document", "", "RIME documents (*.rime)"
        )
        if path:
            self.open_path(path)

    def open_path(self, path):
        return self.records.open_path(path)

    @Slot(str)
    def show_error(self, detail):
        self.error_dialog = QMessageBox(
            QMessageBox.Icon.Warning, "RIME document", detail, QMessageBox.StandardButton.Ok, self
        )
        self.error_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.error_dialog.open()

    def closeEvent(self, event):
        self.records.closed = True
        super().closeEvent(event)
