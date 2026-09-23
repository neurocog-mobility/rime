"""Native verification/adjudication workspace on shared evidence controls."""

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (
    QDialog,
    QMessageBox,
    QMainWindow,
    QWidget,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
)
from rime_core.review_workspace import ReviewWorkspace, load_input, compatible
from rime_core.annotations import Annotation, AnnotationStore
from rime_core.schema import ProtocolSchema
from rime_ui.timeline import AnnotationLanes
from .annotation_editor import AnnotationEditor
from .boundary_editor import BoundarySpinBox
from .components import WorkspaceSection
from .style import polish_surface


def button(text, slot):
    widget = QPushButton(text)
    widget.clicked.connect(slot)
    return widget


class NewReviewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New review")
        self.inputs = []
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.name = QLineEdit("Review")
        self.location = QLineEdit()
        self.reviewer = QLineEdit()
        form.addRow("Review name", self.name)
        path = QHBoxLayout()
        path.addWidget(self.location)
        path.addWidget(button("Browse…", self.browse))
        form.addRow("Save folder", path)
        form.addRow("Reviewer", self.reviewer)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Workspace", "Participant", "Visit", "Trial", "Protocol", "Video 1"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        headers = ["Workspace", "Participant", "Visit", "Trial", "Protocol", "Video 1"]
        self.table.setMinimumWidth(sum(self.fontMetrics().horizontalAdvance(h) + 36 for h in headers))
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        actions.addWidget(button("Add workspace…", self.add_input))
        actions.addWidget(button("Remove", self.remove_input))
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel("Add annotation workspaces of the same observation.")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addWidget(button("Cancel", self.reject))
        actions.addStretch()
        actions.addWidget(button("Create review", self.create_review))
        layout.addLayout(actions)
        self.workspace = None
        polish_surface(self)
        self.fit_contents()

    def fit_contents(self):
        rows = max(1, min(6, self.table.rowCount()))
        self.table.setFixedHeight(
            self.table.horizontalHeader().height()
            + rows * self.table.verticalHeader().defaultSectionSize()
            + 2 * self.table.frameWidth()
        )
        self.adjustSize()

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Save review folder")
        if path:
            self.location.setText(path)

    def add_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add annotation workspace", "", "Workspace (*.json)"
        )
        if path:
            self.try_add_path(path)

    def try_add_path(self, path):
        try:
            candidate = load_input(path)
            compatible(candidate, self.inputs)
        except Exception as exc:
            QMessageBox.warning(self, "New review", f"Workspace not added: {exc}")
            return False
        self.inputs.append(candidate)
        self.refresh()
        return True

    def remove_input(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.inputs):
            self.inputs.pop(row)
            self.refresh()

    def refresh(self):
        self.table.setRowCount(len(self.inputs))
        for row, item in enumerate(self.inputs):
            data = item["data"]
            context = data["research_context"]
            video = next(s for s in data["sources"] if s["kind"] == "video")
            values = [
                data["name"],
                context.get("participant", ""),
                context.get("visit", context.get("bids_session", "")),
                context.get("trial", ""),
                data["protocol"]["name"],
                Path(video["path"]).name,
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self.fit_contents()

    def create_review(self):
        try:
            if not self.location.text().strip():
                raise ValueError("Choose a save folder.")
            destination = Path(self.location.text()).expanduser() / "review.json"
            if destination.exists():
                raise ValueError("review.json already exists; choose another folder.")
            self.workspace = ReviewWorkspace.create_review(
                self.name.text(), self.reviewer.text(), self.inputs
            )
            # Construct evidence before persisting, so unavailable sources fail cleanly.
            self.review_window = ReviewWindow(self.workspace, self.parent())
            self.workspace.save(destination)
            self.review_window.update_title()
        except Exception as exc:
            QMessageBox.warning(self, "Review not created", str(exc))
            return
        self.accept()


class ReviewTimeline(AnnotationLanes):
    def __init__(self, *args, **kwargs):
        self.review_sources = ["reviewer"]
        super().__init__(*args, **kwargs)
        self.show_lane_titles = False

    def _update_label_width(self):
        super()._update_label_width()
        self._label_width = max(
            self._label_width,
            min(
                240,
                max(
                    self.fontMetrics().horizontalAdvance(self._source_short_label(source)) + 24
                    for source in self.review_sources
                ),
            ),
        )

    def _lane_sources(self, level):
        return self.review_sources

    def _primary_row_source(self, source):
        return source or "reviewer"

    def _primary_track_editable(self):
        return False

    def _show_source_label(self, index):
        return True

    def _source_short_label(self, source):
        return "Reviewer output" if source == "reviewer" else source


class ReviewEvidence(AnnotationEditor):
    def __init__(self, workspace, parent=None):
        self.scope_lane = workspace.schema.lanes[0].name
        self.scope_label = workspace.schema.lanes[0].labels[0]
        self.preview = None
        self.preview_case = None
        self.draft_region = None
        self.id_cases = {}
        super().__init__(workspace, parent, timeline_class=ReviewTimeline, review=True)
        self.run_model_button.hide()
        self.annotations_panel.heading.setText("Review annotations")
        self.refresh()

    def refresh(self):
        super().refresh()
        schema = deepcopy(self.workspace.data["protocol"])
        schema.update(
            lanes=[lane for lane in schema["lanes"] if lane["name"] == self.scope_lane],
            groups=[],
            rules=[],
            measurements=[],
        )
        self.lanes.set_schema(ProtocolSchema.from_dict(schema))
        self.lanes.review_sources = [
            f"{i + 1}. {item['name']}"
            for i, item in enumerate(self.workspace.data["review_inputs"])
        ] + ["reviewer"]
        self.lanes._update_label_width()
        store = AnnotationStore()
        self.id_cases = {}
        cases = self.workspace.cases(self.scope_lane, self.scope_label)
        if self.draft_region is not None and not any(
            c["id"] == self.draft_region["id"] for c in cases
        ):
            cases.append(self.draft_region)
        for ref in self.workspace.input_refs(self.scope_lane, self.scope_label):
            value = self.workspace.input_annotation(ref)
            identifier = f"input:{ref['index']}:{value['id']}"
            store.add(
                Annotation(
                    **{**value, "id": identifier, "source": self.lanes.review_sources[ref["index"]]}
                )
            )
        for case in cases:
            if self.preview is not None and self.preview_case == case["id"]:
                values = [
                    dict(
                        id=f"preview:{case['id']}:{i}",
                        lane=case["lane"],
                        label=case["label"],
                        start_ms=a,
                        end_ms=b,
                        event_type=case["event_type"],
                        ghost=True,
                    )
                    for i, (a, b) in enumerate(self.preview)
                ]
            else:
                values = (
                    self.workspace.data["review_decisions"]
                    .get(case["id"], {})
                    .get("annotations", [])
                )
            for value in values:
                store.add(Annotation(**{**value, "source": "reviewer"}))
                self.id_cases[value["id"]] = case["id"]
        self.lanes.set_store(store)
        warnings = self.workspace.shared_input_warnings()
        self.lanes.annotation_warnings = {
            a["id"]: warnings[identifier]
            for identifier, decision in self.workspace.data["review_decisions"].items()
            if identifier in warnings
            for a in decision["annotations"]
        }
        self.lanes.set_violation_ids(set(self.lanes.annotation_warnings))
        self.lanes.update()

    def seek_annotation(self, identifier):
        annotation = self.lanes._store.get(identifier)
        if annotation:
            self.seek(annotation.start_ms)

    def set_loop(self, enabled):
        selected = self.lanes._store.get(self.lanes.get_selected_id())
        if enabled and selected and selected.end_ms > selected.start_ms:
            self.lanes.set_loop_region(selected.start_ms, selected.end_ms)
        super().set_loop(enabled)

    def create(self, *args):
        pass

    def edit(self, *args):
        pass

    def modify(self, *args):
        pass

    def delete_id(self, *args):
        pass

    def cut(self, *args):
        pass

    def sources(self):
        details = "\n".join(
            f"{Path(s['path']).name}: offset {s['config']['offset_ms'] / 1000:g} s"
            for s in self.workspace.data["sources"]
        )
        QMessageBox.information(
            self,
            "Review evidence",
            details + "\n\nEvidence settings are retained from the first input workspace.",
        )


class ReviewWindow(QMainWindow):
    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.workspace = workspace
        workspace.verify_evidence()
        self.editor = ReviewEvidence(workspace)
        self.current = None
        self.creating = False
        self._loading = False
        self._baseline = None
        self.editing_id = None
        self.focus_ref = None
        self.resize(1320, 860)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        split.addWidget(self.editor)
        panel = QWidget()
        form = QVBoxLayout(panel)
        form.setContentsMargins(0, 8, 12, 8)
        form.setSpacing(8)
        scope = WorkspaceSection("Review scope")
        form.addWidget(scope)
        history = WorkspaceSection("Saved decisions")
        form.addWidget(history)
        decision = WorkspaceSection("Current decision")
        form.addWidget(decision)
        form.addStretch()
        scope.body.addWidget(QLabel("Choose the lane and label to review."))
        self.lane = QComboBox()
        self.lane.addItems([lane.name for lane in workspace.schema.lanes])
        self.label = QComboBox()
        scope.body.addWidget(self.lane)
        scope.body.addWidget(self.label)
        actions = QHBoxLayout()
        self.new_decision_button = button("New decision", self.new_decision)
        self.new_button = button("New annotation", self.new_region)
        actions.addWidget(self.new_decision_button)
        actions.addWidget(self.new_button)
        scope.body.addLayout(actions)
        self.saved_decisions = QListWidget()
        self.saved_decisions.setFixedHeight(84)
        history.body.addWidget(self.saved_decisions)
        actions = QHBoxLayout()
        self.edit_button = button("Edit", self.edit_decision)
        self.remove_button = button("Remove", self.remove_decision)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.remove_button)
        history.body.addLayout(actions)
        form = decision.body
        form.addWidget(QLabel("Inputs for this decision"))
        self.inputs_list = QListWidget()
        self.inputs_list.setMinimumHeight(100)
        self.inputs_list.setMaximumHeight(140)
        self.inputs_list.setToolTip("Check the input annotations to resolve together.")
        form.addWidget(self.inputs_list)
        self.status = QLabel()
        self.status.setWordWrap(True)
        form.addWidget(self.status)
        self.choice = QComboBox()
        form.addWidget(self.choice)
        self.bounds = QTableWidget(0, 2)
        self.bounds.setHorizontalHeaderLabels(["Start (s)", "End (s)"])
        self.bounds.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bounds.setMaximumHeight(180)
        form.addWidget(self.bounds)
        self.custom_controls = QWidget()
        row = QHBoxLayout(self.custom_controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(button("Add interval", self.add_bound))
        row.addWidget(button("Remove", self.remove_bound))
        form.addWidget(self.custom_controls)
        self.message = QLabel()
        self.message.setWordWrap(True)
        form.addWidget(self.message)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Decision rationale or discussion notes")
        form.addWidget(self.note)
        self.save_decision_button = button("Save decision", self.save_decision)
        self.save_decision_button.setProperty("role", "primaryAction")
        self.cancel_button = button("Cancel", self.cancel_draft)
        form.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(max(340, panel.minimumSizeHint().width() + 24))
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 8)
        sidebar_layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_decision_button)
        sidebar_layout.addLayout(footer)
        split.addWidget(sidebar)
        split.setSizes([940, 380])
        self.setCentralWidget(split)
        polish_surface(sidebar)
        menu = self.menuBar().addMenu("File")
        menu.addAction("Open…", self.open_file)
        menu.addAction("Save review", self.save).setShortcut("Ctrl+S")
        menu.addAction("Close", self.close)
        edit = self.menuBar().addMenu("Edit")
        edit.addAction("Undo", lambda: self.history(False)).setShortcut("Ctrl+Z")
        edit.addAction("Redo", lambda: self.history(True)).setShortcut("Ctrl+Shift+Z")
        self.lane.currentTextChanged.connect(self.change_lane)
        self.label.currentTextChanged.connect(self.change_scope)
        self.choice.currentIndexChanged.connect(self.choice_changed)
        self.note.textEdited.connect(self.draft_changed)
        self.inputs_list.itemChanged.connect(self.selection_changed)
        self.inputs_list.itemClicked.connect(self.focus_item)
        self.saved_decisions.currentItemChanged.connect(self.choose_saved)
        self.editor.lanes.annotation_selected.connect(self.evidence_clicked)
        self.editor.changed.connect(self.update_title)
        self.change_lane()
        self.update_title()

    def update_title(self):
        self.setWindowTitle(
            self.workspace.data["name"] + " · Review" + (" *" if self.workspace.dirty else "")
        )

    def draft_signature(self):
        return (
            self.selected_refs(),
            self.choice.currentData(),
            self.custom() if self.choice.currentData() == "custom" else [],
            self.note.text(),
        )

    def has_draft(self):
        return self.creating or (
            self._baseline is not None and self.draft_signature() != self._baseline
        )

    def draft_changed(self, *args):
        if self._loading:
            return
        dirty = self.has_draft()
        self.cancel_button.setVisible(dirty)
        if dirty:
            self.status.setText(
                "New annotation — not saved" if self.creating else "Decision not saved"
            )

    def resolve_draft(self):
        if not self.has_draft():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved decision",
            "Save this decision before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_decision()
        self.cancel_draft()
        return True

    def cancel_draft(self):
        self.creating = False
        self.editor.draft_region = None
        self.load_decision(self.editing_id)

    def change_lane(self, *args):
        if not self.resolve_draft():
            with QSignalBlocker(self.lane):
                self.lane.setCurrentText(self.editor.scope_lane)
            return
        with QSignalBlocker(self.label):
            self.label.clear()
            self.label.addItems(self.workspace.schema.get_lane(self.lane.currentText()).labels)
        self.load_scope()

    def change_scope(self, *args):
        if not self.resolve_draft():
            with QSignalBlocker(self.label):
                self.label.setCurrentText(self.editor.scope_label)
            return
        self.load_scope()

    def load_scope(self):
        self.editor.scope_lane = self.lane.currentText()
        self.editor.scope_label = self.label.currentText()
        self.focus_ref = None
        self.load_decision(None)

    def selected_refs(self):
        return [
            self.inputs_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.inputs_list.count())
            if self.inputs_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def focus_item(self, item):
        ref = item.data(Qt.ItemDataRole.UserRole)
        self.focus_ref = ref
        identifier = f"input:{ref['index']}:{ref['annotation']}"
        with QSignalBlocker(self.editor.lanes):
            self.editor.lanes.select_annotation(identifier)
        self.editor.seek(self.workspace.input_annotation(ref)["start_ms"])

    def evidence_clicked(self, identifier):
        # Evidence clicks seek/highlight only; checkboxes establish decision membership.
        for i in range(self.inputs_list.count()):
            item = self.inputs_list.item(i)
            ref = item.data(Qt.ItemDataRole.UserRole)
            if identifier == f"input:{ref['index']}:{ref['annotation']}":
                self.focus_ref = ref
                self.inputs_list.setCurrentItem(item)
                return

    def new_decision(self):
        if self.resolve_draft():
            self.load_decision(None, editing=True)

    def edit_decision(self):
        if self.editing_id and self.resolve_draft():
            self.load_decision(self.editing_id, editing=True)

    def remove_decision(self):
        identifier = self.editing_id
        if identifier and self.resolve_draft():
            self.workspace.unresolved(identifier)
            self.load_decision(None)
            self.update_title()

    def choose_saved(self, item, previous=None):
        if self._loading or item is None:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        if self.resolve_draft():
            self.load_decision(identifier)
        else:
            with QSignalBlocker(self.saved_decisions):
                self.saved_decisions.setCurrentItem(previous)

    def load_decision(self, identifier, editing=False):
        self._loading = True
        self.creating = False
        self.editing_id = identifier
        self.current = next(
            (deepcopy(c) for c in self.workspace.data["review_cases"] if c["id"] == identifier),
            None,
        )
        self.editor.preview = None
        self.editor.preview_case = None
        self.editor.draft_region = None
        lane, label = self.editor.scope_lane, self.editor.scope_label
        unresolved = self.workspace.input_refs(lane, label, unresolved=True)
        selected = self.current["inputs"] if self.current else []
        self.inputs_list.clear()
        for ref in self.workspace.input_refs(lane, label):
            a = self.workspace.input_annotation(ref)
            name = self.workspace.data["review_inputs"][ref["index"]]["name"]
            resolved = ref not in unresolved
            item = QListWidgetItem(
                f"{ref['index'] + 1}. {name} · {a['start_ms'] / 1000:.3f}–{a['end_ms'] / 1000:.3f} s"
                + (" · saved" if resolved else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, ref)
            item.setToolTip(item.text())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if ref in selected else Qt.CheckState.Unchecked
            )
            self.inputs_list.addItem(item)
        self.saved_decisions.clear()
        warnings = self.workspace.shared_input_warnings()
        for i, case in enumerate(self.workspace.data["review_cases"]):
            if case["lane"] != lane or case["label"] != label:
                continue
            item = QListWidgetItem(
                ("⚠ " if case["id"] in warnings else "")
                + f"Decision {i + 1} · {case['start_ms'] / 1000:.3f}–{case['end_ms'] / 1000:.3f} s"
            )
            item.setData(Qt.ItemDataRole.UserRole, case["id"])
            item.setToolTip(warnings.get(case["id"], ""))
            self.saved_decisions.addItem(item)
            if case["id"] == identifier:
                self.saved_decisions.setCurrentItem(item)
        self.choice.clear()
        self.choice.addItem("Choose…", "")
        for i, item in enumerate(self.workspace.data["review_inputs"]):
            self.choice.addItem(f"Use {i + 1}. {item['name']}", f"input:{i}")
        for text, value in [
            ("Average", "mean"),
            ("Union", "union"),
            ("Intersection", "intersection"),
            ("Custom boundaries", "custom"),
            ("No event", "no_event"),
        ]:
            self.choice.addItem(text, value)
        saved = self.workspace.data["review_decisions"].get(identifier)
        if saved:
            self.choice.setCurrentIndex(self.choice.findData(saved["choice"]))
        self.note.setText(saved.get("note", "") if saved else "")
        self.status.setText(
            "Decision saved" if saved else "Select input annotations to review together."
        )
        self.bounds.setRowCount(0)
        if saved and saved["choice"] == "custom":
            for a in saved["annotations"]:
                self.add_bound(a["start_ms"], a["end_ms"])
        self.bounds.setVisible(bool(saved and saved["choice"] == "custom"))
        self.custom_controls.setVisible(not self.bounds.isHidden())
        self.message.clear()
        self.save_decision_button.setEnabled(bool(saved))
        self.choice.setEnabled(bool(self.current))
        for control in (
            self.lane,
            self.label,
            self.new_decision_button,
            self.new_button,
            self.inputs_list,
            self.saved_decisions,
        ):
            control.setEnabled(True)
        self.edit_button.setEnabled(bool(identifier))
        self.remove_button.setEnabled(bool(identifier))
        self.inputs_list.setEnabled(editing)
        self.choice.setEnabled(editing and bool(self.current))
        self.bounds.setEnabled(editing)
        self.custom_controls.setEnabled(editing)
        self.note.setEnabled(editing)
        self.save_decision_button.setVisible(editing)
        self.cancel_button.setVisible(editing)
        self._baseline = deepcopy(self.draft_signature())
        self._loading = False
        self.cancel_button.setVisible(editing)
        self.editor.refresh()
        self.highlight_selection()

    def highlight_selection(self):
        self.editor.lanes.review_selected_ids = {
            f"input:{r['index']}:{r['annotation']}" for r in self.selected_refs()
        }
        if self.editing_id:
            self.editor.lanes.review_selected_ids.update(
                a["id"]
                for a in self.workspace.data["review_decisions"]
                .get(self.editing_id, {})
                .get("annotations", [])
            )
        self.editor.lanes.update()

    def selection_changed(self, *args):
        if self._loading or self.creating:
            return
        refs = self.selected_refs()
        self.current = (
            self.workspace.selection(refs, self.editing_id or "selection-preview") if refs else None
        )
        self.editor.draft_region = self.current
        self.choice.setEnabled(bool(refs))
        self.editor.preview = None
        self.editor.preview_case = None
        if refs and self.choice.currentData():
            self.preview()
        else:
            self.save_decision_button.setEnabled(False)
            self.editor.refresh()
        self.highlight_selection()
        self.draft_changed()

    def choice_changed(self, *args):
        if self._loading:
            return
        custom = self.choice.currentData() == "custom"
        previous = self.editor.preview
        self.bounds.setVisible(custom)
        self.custom_controls.setVisible(custom)
        if custom and self.bounds.rowCount() == 0 and self.current:
            spans = previous or [[self.current["start_ms"], self.current["end_ms"]]]
            for a, b in spans:
                self.add_bound(a, b)
        self.preview()

    def add_bound(self, start=None, end=None):
        if not self.current:
            return
        if start is None or isinstance(start, bool):
            start, end = self.current["start_ms"], self.current["end_ms"]
        row = self.bounds.rowCount()
        self.bounds.insertRow(row)
        self.fit_bounds()
        for col, value in enumerate([start, end]):
            field = BoundarySpinBox()
            field.setRange(0, self.workspace.data["duration_ms"] / 1000)
            field.setDecimals(3)
            field.setSingleStep(0.05)
            field.setValue(value / 1000)
            field.setEnabled(col == 0 or self.current["event_type"] != "point")
            self.bounds.setCellWidget(row, col, field)
            field.focused.connect(lambda value: self.editor.seek(value * 1000))
            field.valueChanged.connect(self.boundary_changed)
        self.preview()

    def boundary_changed(self, value):
        self.editor.seek(value * 1000)
        self.preview()

    def fit_bounds(self):
        self.bounds.setFixedHeight(
            self.bounds.horizontalHeader().height()
            + max(1, min(4, self.bounds.rowCount())) * self.bounds.verticalHeader().defaultSectionSize()
            + 2 * self.bounds.frameWidth()
        )

    def remove_bound(self):
        self.bounds.removeRow(self.bounds.currentRow())
        self.fit_bounds()
        self.preview()

    def custom(self):
        result = []
        for row in range(self.bounds.rowCount()):
            a, b = [self.bounds.cellWidget(row, col) for col in (0, 1)]
            if a is None or b is None:
                continue
            result.append(
                [
                    a.value() * 1000,
                    (
                        a if self.workspace.schema.is_point_lane(self.editor.scope_lane) else b
                    ).value()
                    * 1000,
                ]
            )
        return result

    def preview(self):
        if self._loading or not self.current:
            return
        try:
            spans = self.workspace.spans(self.current, self.choice.currentData(), self.custom())
            if any(
                b < a or (self.current["event_type"] == "interval" and b == a) for a, b in spans
            ):
                raise ValueError("End must be after start.")
            self.editor.preview = spans
            self.editor.preview_case = self.current["id"]
            self.message.clear()
            self.save_decision_button.setEnabled(True)
        except ValueError as exc:
            self.message.setText(str(exc))
            self.editor.preview = None
            self.save_decision_button.setEnabled(False)
        self.editor.refresh()
        self.highlight_selection()
        self.draft_changed()

    def save_decision(self):
        if not self.current or not self.save_decision_button.isEnabled():
            return False
        try:
            case = deepcopy(self.current)
            if not self.editing_id:
                import uuid

                case["id"] = uuid.uuid4().hex
            if not case["inputs"]:
                spans = self.custom()
                case["start_ms"] = min(a for a, b in spans)
                case["end_ms"] = max(b for a, b in spans)
            self.workspace.save_decision(
                case, self.choice.currentData(), self.custom(), self.note.text()
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Decision not saved", str(exc))
            return False
        self.creating = False
        self.editor.draft_region = None
        self.load_decision(case["id"])
        self.update_title()
        return True

    def new_region(self):
        if self.creating or not self.resolve_draft():
            return
        self.load_decision(None, editing=True)
        self.creating = True
        self._loading = True
        duration = self.workspace.data["duration_ms"]
        point = self.workspace.schema.is_point_lane(self.lane.currentText())
        start = min(
            self.editor.player.get_position_ms(), duration if point else max(0, duration - 50)
        )
        end = start if point else min(duration, start + 1000)
        self.current = dict(
            id="new-region-preview",
            lane=self.lane.currentText(),
            label=self.label.currentText(),
            event_type="point" if point else "interval",
            start_ms=start,
            end_ms=end,
            inputs=[],
        )
        self.editor.draft_region = self.current
        with QSignalBlocker(self.choice):
            self.choice.setCurrentIndex(self.choice.findData("custom"))
        self.choice.setEnabled(False)
        self.bounds.setRowCount(0)
        self.add_bound(start, end)
        self.bounds.show()
        self.custom_controls.hide()
        self.note.clear()
        for control in (
            self.lane,
            self.label,
            self.new_decision_button,
            self.new_button,
            self.edit_button,
            self.remove_button,
            self.inputs_list,
            self.saved_decisions,
        ):
            control.setEnabled(False)
        self._loading = False
        self.preview()

    def history(self, redo):
        if not self.resolve_draft():
            return
        (self.workspace.redo if redo else self.workspace.undo)()
        self.change_scope()
        self.update_title()

    def save(self):
        if not self.resolve_draft():
            return False
        try:
            if self.workspace.path is None:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save review", "review.json", "Review (*.json)"
                )
                if not path:
                    return False
            else:
                path = self.workspace.path
            self.workspace.data["view"]["position_ms"] = self.editor.player.get_position_ms()
            self.workspace.save(path)
            self.update_title()
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Review not saved", str(exc))
            return False

    def open_file(self):
        if self.parent():
            self.parent().open_file()

    def closeEvent(self, event):
        if not self.resolve_draft():
            event.ignore()
            return
        if self.workspace.dirty:
            choice = QMessageBox.question(
                self,
                "Save review?",
                "Save changes before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel or (
                choice == QMessageBox.StandardButton.Save and not self.save()
            ):
                event.ignore()
                return
        self.editor.pause()
        event.accept()
