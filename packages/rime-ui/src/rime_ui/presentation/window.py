"""Desktop shell for native workspaces and independent record inspection."""

from pathlib import Path
import json
from rime_core.review_workspace import ReviewWorkspace

from rime_core.annotation_workspace import AnnotationWorkspace, source_entry, import_annotations
from rime_core.schema import ProtocolSchema, DEFAULT_SCHEMA_PATH, NOTES_ONLY_SCHEMA_PATH
from rime_core.records import VideoSource
from .annotation_editor import AnnotationEditor

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFrame,
    QStackedWidget,
    QScrollArea,
    QSizePolicy,
    QLineEdit,
    QPlainTextEdit,
    QDialog,
    QCheckBox,
    QListWidget,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QFormLayout,
    QDialogButtonBox,
)
from .style import polish_surface, apply_theme
from .components import (
    WorkspaceSection,
    button,
    label,
    column,
    row,
    field,
    combo,
    scroll,
)
from .records import RecordWindow
from .review_workspace import NewReviewDialog, ReviewWindow


class CurrentPageStack(QStackedWidget):
    """Hidden workspace pages must not impose their size on startup/setup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self.update_page_sizes)

    def addWidget(self, widget):
        index = super().addWidget(widget)
        self.update_page_sizes()
        return index

    def update_page_sizes(self, *_):
        for index in range(self.count()):
            policy = (QSizePolicy.Policy.Preferred if index == self.currentIndex()
                      else QSizePolicy.Policy.Ignored)
            self.widget(index).setSizePolicy(policy, policy)
        self.updateGeometry()

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page else QSize(0, 0)

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else QSize(0, 0)


class RimeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RIME")
        self.editor = None
        self.pending_sources = []
        self.pending_channels = {}
        self.pending_import = None
        self.protocols = [
            ProtocolSchema.load(DEFAULT_SCHEMA_PATH),
            ProtocolSchema.load(NOTES_ONLY_SCHEMA_PATH),
        ]
        screen = QApplication.primaryScreen().availableGeometry()
        self._workspace_size = QSize(min(1320, screen.width() - 50), min(860, screen.height() - 70))
        self.theme_mode = "system"
        self.text_scale = 1.0
        self.context = "start"
        self.workspace_name = "Walking trial"
        self.has_workspace = False
        self.review_windows = []
        self.record_windows = []
        root = QWidget()
        root.setObjectName("page")
        self.setCentralWidget(root)
        layout = column(root)
        self.header = QFrame()
        self.header.setObjectName("header")
        header_layout = column(self.header, 16)
        self.home_button = button("Start", self.go_home, "quiet")
        self.context_title = label("Walking trial", "heading")
        self.saved = label("", "muted", False)
        header_layout.addLayout(
            row(
                self.home_button,
                self.context_title,
                None,
                self.saved,
            )
        )
        layout.addWidget(self.header)
        self.pages = CurrentPageStack()
        layout.addWidget(self.pages, 1)
        self.start_page = self.create_start()
        self.prepare_page = self.create_prepare()
        self.pages.addWidget(self.start_page)
        self.pages.addWidget(self.prepare_page)
        self.create_menus()
        self.apply_style()
        self.go_home()

    def create_start(self):
        page = QWidget()
        outer = column(page, 32)

        inner = WorkspaceSection("Start a workflow")
        inner.setMinimumWidth(400)
        inner.setMaximumWidth(620)
        body = inner.body
        body.addWidget(label("RIME", "heading"))

        body.addWidget(
            label(
                "Annotate recordings, review annotations, or inspect measurement records.",
                "muted",
            )
        )

        body.addLayout(
            row(
                button("New workspace", self.prepare, "primary", "new_workspace"),
                button("New review", self.new_review),
                button("Open…", self.open_file, name="open_file"),
                None,
            )
        )

        outer.addWidget(inner, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        return page

    def new_review(self):
        dialog = NewReviewDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            review = dialog.review_window
            self.review_windows.append(review)
            review.show()
        dialog.deleteLater()

    def create_prepare(self):
        page = QWidget()
        outer = column(page, 8)
        box = QWidget()
        box.setMaximumWidth(660)
        form = column(box, 8)
        self.setup_pages = CurrentPageStack()
        self.setup_pages.currentChanged.connect(self.schedule_setup_size)
        form.addWidget(self.setup_pages)
        details = WorkspaceSection("1. Workspace")
        detail = details.body
        self.name_field = field(detail, "Name", QLineEdit("Walking trial"))
        self.location_field = QLineEdit()
        detail.addWidget(label("Location"))
        detail.addLayout(
            row(
                self.location_field,
                button("Browse…", self.browse_workspace_location),
            )
        )
        self.protocol_field = combo([p.name for p in self.protocols])
        self.protocol_field.currentIndexChanged.connect(lambda: self.remove_import())
        detail.addWidget(label("Protocol"))
        detail.addLayout(
            row(
                self.protocol_field,
                button("Load…", self.load_protocol),
            )
        )
        self.context_fields = QWidget()
        context_layout = column(self.context_fields)
        for title in ["Participant", "Visit", "Trial"]:
            field(context_layout, title, QLineEdit())
        detail.addWidget(label("Research context"))
        detail.addWidget(self.context_fields)
        self.prepare_error = label("", "error")
        detail.addWidget(self.prepare_error)
        detail.addLayout(
            row(button("Cancel", self.go_home), None, button("Next", self.prepare_next))
        )
        self.setup_pages.addWidget(details)

        inputs = WorkspaceSection("2. Recordings & annotations")
        content = inputs.body
        content.addWidget(label("Video 1 (required) · timeline reference, 0 s"))
        self.source_list = QListWidget()
        self.source_list.setMaximumHeight(130)
        content.addWidget(self.source_list)
        content.addLayout(
            row(
                button("Add video…", self.prepare_video),
                button("Add signals…", self.prepare_sources),
                button("Remove", self.remove_source),
                None,
            )
        )
        self.files_label = label("No sources selected")
        content.addWidget(self.files_label)
        content.addWidget(label("Annotations (optional)"))
        self.import_label = label("No annotation file selected")
        content.addWidget(self.import_label)
        content.addLayout(
            row(
                button("Import EAF…", self.prepare_import),
                button("Remove import", self.remove_import),
                None,
            )
        )
        self.import_mapping = QWidget()
        column(self.import_mapping)
        content.addWidget(self.import_mapping)
        self.import_mapping.hide()
        self.empty_choice = QCheckBox()
        self.empty_choice.hide()
        self.align_choice = QCheckBox("Align sources before annotating")
        self.align_choice.setChecked(True)
        self.align_choice.setEnabled(False)
        content.addWidget(self.align_choice)
        sync_help = label(
            "Synchronization notes (optional): describe how each source was aligned, "
            "including synchronization before import. You can add notes even if you "
            "skip alignment, and edit them later in Alignment."
        )
        sync_help.setWordWrap(True)
        content.addWidget(sync_help)
        self.setup_sync_notes = QWidget()
        QFormLayout(self.setup_sync_notes)
        content.addWidget(self.setup_sync_notes)
        self.create_button = button("Begin annotation", self.create_workspace)
        self.create_button.setEnabled(False)
        content.addLayout(
            row(
                button("Back", lambda: self.setup_pages.setCurrentIndex(0)),
                None,
                self.create_button,
            )
        )
        self.align_choice.toggled.connect(self.refresh_setup)
        self.setup_pages.addWidget(inputs)
        form.addStretch()
        outer.addWidget(scroll(box), 1)
        return page

    def prepare_next(self):
        if not self.name_field.text().strip():
            self.prepare_error.setText("Enter a workspace name")
            self.prepare_error.show()
            return
        self.prepare_error.hide()
        self.setup_pages.setCurrentIndex(1)

    def toggle_context(self):
        self.context_fields.setVisible(not self.context_fields.isVisible())

    def refresh_setup(self):
        count = self.source_list.count()
        self.files_label.setText(f"{count} sources" if count else "No sources selected")
        self.align_choice.setEnabled(bool(count))
        self.create_button.setEnabled(
            any(self.source_list.item(i).text().startswith("Video 1 ·") for i in range(count))
        )
        self.schedule_setup_size()
        self.create_button.setText(
            "Continue to alignment"
            if count and self.align_choice.isChecked()
            else "Begin annotation"
        )

    def prepare_video(self):
        count = sum(s["kind"] == "video" for s in self.pending_sources)
        if count >= 2:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Add video", "", "Video (*.mp4 *.mov *.avi *.mkv)"
        )
        if path:
            self.pending_sources.append(
                source_entry(
                    path,
                    VideoSource(
                        file_name=Path(path).name,
                        label=f"Video {count + 1}",
                        role="primary" if count == 0 else "secondary",
                    ),
                    "video",
                )
            )
            self.refresh_source_list()

    def prepare_sources(self):
        from rime_ui.dialogs.signal_config_dialog import SignalConfigDialog

        path, _ = QFileDialog.getOpenFileName(self, "Add signals", "", "Signals (*.csv)")
        if path:
            selection = SignalConfigDialog.configure_signal(path, path, self)
            if selection:
                self.pending_sources.append(source_entry(path, selection.source, "signal"))
                self.pending_channels[selection.source.id] = selection.display_channels
                self.refresh_source_list()

    def remove_source(self):
        index = self.source_list.currentRow()
        if index >= 0:
            self.pending_sources.pop(index)
            self.refresh_source_list()

    def prepare_import(self):
        import pympi

        path, _ = QFileDialog.getOpenFileName(self, "Import annotations", "", "ELAN (*.eaf)")
        if not path:
            return
        try:
            eaf = pympi.Elan.Eaf(path)
            schema = self.protocols[self.protocol_field.currentIndex()]
            dialog = QDialog(self)
            dialog.setWindowTitle("Import EAF · select lanes")
            form = QFormLayout(dialog)
            selectors = {}
            for tier in eaf.get_tier_names():
                choice = QComboBox()
                choice.addItems(["Do not import", *schema.get_lane_names()])
                for lane in schema.get_lane_names():
                    if lane.casefold().rstrip("s") == tier.casefold().rstrip("s"):
                        choice.setCurrentText(lane)
                selectors[tier] = choice
                form.addRow(tier, choice)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec():
                mapping = {
                    tier: choice.currentText()
                    for tier, choice in selectors.items()
                    if choice.currentIndex() > 0
                }
                if not mapping:
                    raise ValueError("Select at least one annotation tier.")
                labels = {}
                label_dialog = QDialog(self)
                label_dialog.setWindowTitle("Import EAF · map labels")
                label_form = QFormLayout(label_dialog)
                label_choices = {}
                for tier, lane in mapping.items():
                    for _, _, text in eaf.get_annotation_data_for_tier(tier):
                        text = text.strip()
                        if text not in schema.get_lane(lane).labels and text not in label_choices:
                            choice = QComboBox()
                            choice.addItems(schema.get_lane(lane).labels)
                            label_choices[text] = choice
                            label_form.addRow(f"{tier}: {text}", choice)
                if label_choices:
                    accept = QDialogButtonBox(
                        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                    )
                    accept.accepted.connect(label_dialog.accept)
                    accept.rejected.connect(label_dialog.reject)
                    label_form.addRow(accept)
                    if not label_dialog.exec():
                        return
                    labels = {text: choice.currentText() for text, choice in label_choices.items()}
                self.pending_import = (path, mapping, labels)
                self.import_label.setText(Path(path).name)
        except Exception as exc:
            QMessageBox.warning(self, "Import not selected", str(exc))

    def remove_import(self):
        self.pending_import = None
        self.import_label.setText("No annotation file selected")
        self.import_mapping.hide()

    def create_menus(self):
        file = self.menuBar().addMenu("&File")
        self.action(file, "New workspace…", self.prepare, QKeySequence.StandardKey.New)
        self.action(file, "New review…", self.new_review)
        self.action(file, "Open…", self.open_file, QKeySequence.StandardKey.Open)
        self.action(file, "Start", self.go_home)
        file.addSeparator()
        self.save_action = self.action(
            file, "Save workspace", self.save_workspace, QKeySequence.StandardKey.Save
        )
        self.action(file, "Close window", self.close, QKeySequence.StandardKey.Close)
        edit = self.menuBar().addMenu("&Edit")
        self.undo_action = self.action(edit, "Undo", self.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self.action(edit, "Redo", self.redo, QKeySequence.StandardKey.Redo)
        view = self.menuBar().addMenu("&View")
        self.annotation_action = self.action(
            view, "Annotations", lambda: self.navigate("annotations")
        )
        help_menu = self.menuBar().addMenu("&Help")
        self.action(help_menu, "About RIME", self.about)

    def action(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(shortcut)
        menu.addAction(act)
        return act

    def resizeEvent(self, event):
        if hasattr(self, "saved"):
            self.saved.setVisible(
                self.context in ["workspace", "document"]
                and self.width() >= 1200
                and self.text_scale == 1.0
            )
        super().resizeEvent(event)

    def set_theme(self, key):
        self.theme_mode = key
        self.apply_style()

    def set_scale(self, scale):
        self.text_scale = scale
        self.saved.setVisible(
            scale == 1.0 and self.context in ["workspace", "document"] and self.width() >= 1200
        )
        self.apply_style()

    def apply_style(self):
        self.colors = apply_theme(QApplication.instance(), self.theme_mode, self.text_scale)
        polish_surface(self)

    def context_header(self, kind):
        if self.context == "workspace" and kind != "workspace":
            self._workspace_size = self.size()
        self.setMinimumWidth(920 if kind == "workspace" else 0)
        self.context = kind
        self.annotation_action.setEnabled(self.editor is not None)
        self.header.hide()
        self.saved.setVisible(
            kind in ["workspace", "document"] and self.width() >= 1200 and self.text_scale == 1.0
        )
        self.saved.setText(self.workspace_name if kind == "workspace" else "")
        self.save_action.setEnabled(kind == "workspace")
        self.undo_action.setEnabled(kind == "workspace")
        self.redo_action.setEnabled(kind == "workspace")

    def go_home(self):
        if self.editor:
            self.editor.pause()
        self.context_header("start")
        self.pages.setCurrentWidget(self.start_page)
        self.fit_setup_size()

    def prepare(self):
        if self.editor:
            self.editor.pause()
        self.context_header("prepare")
        self.context_title.setText("New workspace")
        self.setup_pages.setCurrentIndex(0)
        self.pages.setCurrentWidget(self.prepare_page)
        self.fit_setup_size()

    def schedule_setup_size(self, *_):
        QTimer.singleShot(0, self, self.fit_setup_size)

    def fit_setup_size(self):
        if self.context not in ("start", "prepare"):
            return
        self.ensurePolished()
        screen = self.screen().availableGeometry()
        if self.context == "start":
            hint = self.start_page.sizeHint()
            width, height = hint.width() + 16, hint.height() + 16
        else:
            page = self.setup_pages.currentWidget()
            page.layout().activate()
            # Match the existing form width, including its scroll/container margins.
            width = 680
            height = max(page.sizeHint().height(), page.minimumSizeHint().height()) + 72
        self.pages.updateGeometry()
        self.centralWidget().layout().activate()
        self.resize(min(width, screen.width() - 50),
                    min(height + self.menuBar().sizeHint().height(), screen.height() - 70))
        if self.context == "prepare":
            QTimer.singleShot(0, self, self.fit_setup_overflow)

    def fit_setup_overflow(self):
        if self.context != "prepare":
            return
        area = self.prepare_page.findChild(QScrollArea)
        overflow = area.verticalScrollBar().maximum()
        if overflow:
            self.resize(self.width(), min(self.height() + overflow,
                                         self.screen().availableGeometry().height() - 70))

    def create_workspace(self):
        try:
            location = self.location_field.text().strip()
            if not location:
                raise ValueError("Choose a workspace folder.")
            destination = Path(location).expanduser().resolve() / "workspace.json"
            if destination.exists():
                raise ValueError("This folder already contains a workspace. Choose a new folder.")
            workspace = AnnotationWorkspace.create(
                self.name_field.text().strip(),
                self.protocols[self.protocol_field.currentIndex()],
                self.pending_sources,
                context={
                    key: field.text()
                    for key, field in zip(
                        ("participant", "visit", "trial"),
                        self.context_fields.findChildren(QLineEdit),
                    )
                },
            )
            workspace.data["view"]["channels"] = dict(self.pending_channels)
            if self.pending_import:
                import_annotations(workspace, *self.pending_import)
            editor = AnnotationEditor(workspace)
            if not self.confirm_leave():
                editor.deleteLater()
                return
            workspace.save(destination)
            self.admit_editor(editor)
            if self.align_choice.isChecked():
                editor.sources()
        except Exception as exc:
            QMessageBox.warning(self, "Workspace not created", str(exc))

    def open_document(self, *, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open RIME document", "", "RIME documents (*.rime)"
            )
        if not path:
            return None
        document = RecordWindow()
        self.record_windows.append(document)
        document.destroyed.connect(lambda: self.record_windows.remove(document))
        document.show()
        document.open_path(path)
        return document

    def navigate(self, page):
        returning = self.context != "workspace"
        self.context_header("workspace")
        if self.editor:
            self.pages.setCurrentWidget(self.editor)
            if returning:
                self.resize(self._workspace_size)

    def working_changed(self):
        if self.editor:
            self.setWindowTitle(
                f"{self.editor.workspace.data['name']}{' *' if self.editor.workspace.dirty else ''} · RIME"
            )

    def save_workspace(self):
        if self.editor:
            try:
                self.editor.save()
            except Exception as exc:
                QMessageBox.warning(self, "Workspace not saved", str(exc))

    def undo(self):
        if self.editor:
            self.editor.workspace.undo()
            self.editor.refresh()
            self.working_changed()

    def redo(self):
        if self.editor:
            self.editor.workspace.redo()
            self.editor.refresh()
            self.working_changed()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", "RIME (*.json *.rime)")
        if path:
            if Path(path).suffix.lower() == ".rime":
                self.open_document(path=path)
            else:
                self.open_workspace_path(path)

    def about(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About RIME")
        layout = column(dialog, 24)
        layout.addWidget(label("RIME", "title"))
        layout.addWidget(label("Reproducible Interval-derived Measurement Exchange"))
        layout.addWidget(
            label(
                "",
                "notice",
            )
        )
        layout.addWidget(button("Done", dialog.accept, "primary"))
        dialog.exec()
        dialog.deleteLater()

    def refresh_source_list(self):
        self.source_list.clear()
        notes_form = self.setup_sync_notes.layout()
        while notes_form.rowCount():
            notes_form.removeRow(0)
        videos = 0
        for source in self.pending_sources:
            if source["kind"] == "video":
                videos += 1
                source["config"].update(
                    label=f"Video {videos}", role="primary" if videos == 1 else "secondary"
                )
                title = f"Video {videos}"
            else:
                title = "Signal"
            self.source_list.addItem(f"{title} · {Path(source['path']).name}")
            note = QPlainTextEdit(source.get("synchronization_note", ""))
            note.setObjectName(f"setup_synchronization_note_{source['config']['id']}")
            note.setPlaceholderText("Method, tools, timing cues or alignment checks…")
            note.setMaximumHeight(75)
            note.textChanged.connect(
                lambda entry=source, field=note: entry.update(
                    synchronization_note=field.toPlainText().strip()
                )
            )
            notes_form.addRow(f"{title} · {Path(source['path']).name}", note)
        self.refresh_setup()

    def browse_workspace_location(self):
        path = QFileDialog.getExistingDirectory(self, "Workspace folder")
        if path:
            self.location_field.setText(path)

    def load_protocol(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load protocol", "", "Protocol (*.json)")
        if path:
            try:
                protocol = ProtocolSchema.load(path)
                self.protocols.append(protocol)
                self.protocol_field.addItem(protocol.name)
                self.protocol_field.setCurrentIndex(len(self.protocols) - 1)
                self.remove_import()
            except Exception as exc:
                QMessageBox.warning(self, "Protocol not loaded", str(exc))

    def confirm_leave(self):
        if self.editor is not None and self.editor.suggestions.busy:
            QMessageBox.information(
                self,
                "Model running",
                "Wait for the model run to finish before closing this workspace.",
            )
            return False
        if not self.editor or not self.editor.workspace.dirty:
            return True
        choice = QMessageBox.question(
            self,
            "Save workspace?",
            "Save changes before replacing this workspace?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            try:
                self.editor.save()
            except Exception as exc:
                QMessageBox.warning(self, "Workspace not saved", str(exc))
                return False
        return True

    def open_workspace_path(self, path):
        try:
            source = Path(path)
            if source.is_dir():
                source /= "workspace.json"
            if json.loads(source.read_text()).get("format") == ReviewWorkspace.format:
                review = ReviewWindow(ReviewWorkspace.open(source), self)
                self.review_windows.append(review)
                review.show()
                return True
            workspace = AnnotationWorkspace.open(path)
            editor = AnnotationEditor(workspace)
            if not self.confirm_leave():
                editor.deleteLater()
                return False
            self.admit_editor(editor)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Workspace not opened", str(exc))
            return False

    def admit_editor(self, editor):
        if self.editor:
            self.editor.pause()
            self.pages.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = editor
        editor.changed.connect(self.working_changed)
        self.workspace_name = editor.workspace.data["name"]
        self.has_workspace = True
        self.pages.addWidget(editor)
        self.navigate("annotations")
        self.working_changed()

    def closeEvent(self, event):
        if self.confirm_leave():
            from shiboken6 import isValid

            for review in list(self.review_windows):
                if isValid(review) and not review.close():
                    event.ignore()
                    return
            if self.editor:
                self.editor.pause()
            event.accept()
        else:
            event.ignore()
