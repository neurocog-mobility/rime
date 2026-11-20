"""Shared dataset export dialog for annotation and review workspaces."""

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFormLayout, QLineEdit, QVBoxLayout,
)

from rime_core.dataset_export import export_workspace_dataset, validate_export
from rime_core.review_workspace import ReviewWorkspace
from .components import WorkspaceSection, button, label, row
from .records import Job
from .style import polish_surface


class DatasetExportDialog(QDialog):
    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export dataset")
        self.setMinimumWidth(520)
        self.snapshot = deepcopy(workspace.data)
        self.busy = False
        self._job = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        review = isinstance(workspace, ReviewWorkspace)
        layout.addWidget(label(
            "Export annotations retained through saved reviewer decisions."
            if review else "Export the retained annotations in this workspace.",
            "muted",
        ))
        self.destination_section = WorkspaceSection("Destination")
        layout.addWidget(self.destination_section)
        form = QFormLayout()
        form.setSpacing(8)
        self.destination_section.body.addLayout(form)
        self.location = QLineEdit()
        self.location.setPlaceholderText("New or empty folder")
        if workspace.path:
            self.location.setText(str(workspace.path.parent / (workspace.path.stem + "-dataset")))
        form.addRow("Export folder", row(self.location, button("Browse…", self.browse)))
        context = workspace.data["research_context"]
        self.participant = QLineEdit(str(context.get("participant", "")).removeprefix("sub-"))
        session_id = context.get("bids_session", context.get("visit", ""))
        self.session = QLineEdit(str(session_id).removeprefix("ses-"))
        self.participant.setPlaceholderText("e.g. 01")
        self.session.setPlaceholderText("e.g. 01")
        form.addRow("Participant ID", self.participant)
        form.addRow("Session ID", self.session)
        self.destination_section.body.addWidget(label(
            "Use letters and numbers, without sub- or ses- prefixes.", "muted",
        ))
        self.contents_section = WorkspaceSection("Contents")
        layout.addWidget(self.contents_section)
        self.contents_section.body.addWidget(label(
            "Annotations and dataset metadata are always included.", "muted",
        ))
        self.motion = QCheckBox("Include full sensor recordings")
        self.clips = QCheckBox("Include annotation-based signal clips")
        has_signals = any(s["kind"] == "signal" for s in workspace.data["sources"])
        for option in (self.motion, self.clips):
            option.setEnabled(has_signals)
            self.contents_section.body.addWidget(option)
        self.contents_section.body.addWidget(label(
            "BIDS / Motion-BIDS conventions · events and recordings as TSV; clips as Parquet.",
            "muted",
        ))
        self.timing = QCheckBox("Timing is aligned to Video 1")
        self.timing.setToolTip(
            "Confirm that annotations and any exported signals use the primary video's timeline."
        )
        self.contents_section.body.addWidget(self.timing)
        self.status = label("", "muted")
        layout.addWidget(self.status)
        self.cancel = button("Cancel", self.reject)
        self.export_button = button("Export dataset", self.start_export, "primaryAction")
        layout.addLayout(row(self.cancel, None, self.export_button))
        polish_surface(self)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, "Choose a new or empty export folder")
        if path:
            self.location.setText(path)

    def show_status(self, text):
        self.status.setText(text)
        self.status.show()

    def start_export(self):
        if self.busy:
            return
        destination = self.location.text().strip()
        participant, session = self.participant.text().strip(), self.session.text().strip()
        timing_verified = self.timing.isChecked()
        try:
            validate_export(destination, participant, session, timing_verified)
        except (ValueError, OSError) as exc:
            self.show_status(str(exc))
            return
        options = dict(
            timing_verified=timing_verified,
            export_motion=self.motion.isChecked(), export_clips=self.clips.isChecked(),
        )
        self.busy = True
        for widget in (
            self.destination_section, self.contents_section, self.export_button, self.cancel,
        ):
            widget.setEnabled(False)
        self.show_status("Exporting dataset…")
        self._job = Job(lambda: export_workspace_dataset(
            self.snapshot, destination, participant, session, **options,
        ))
        self._job.signals.finished.connect(self.export_finished, Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(self._job)

    @Slot(object, object)
    def export_finished(self, result, error):
        self.busy = False
        self._job = None
        self.cancel.setEnabled(True)
        if error:
            for widget in (self.destination_section, self.contents_section, self.export_button):
                widget.setEnabled(True)
            self.show_status(str(error))
        else:
            self.cancel.setText("Close")
            destination = Path(self.location.text().strip()).expanduser()
            self.show_status(f"Exported {result} files to {destination}.")

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)
