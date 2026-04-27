"""Session metadata editor dialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from rime_core.sessions import Session


class SessionMetadataDialog(QDialog):
    """Edit a subset of persisted session metadata fields."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self.setWindowTitle("Edit Metadata")
        self.setMinimumWidth(460)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit(self._session.name, self)
        form.addRow("Session name:", self.name_input)

        self.rater_input = QLineEdit(self._session.rater, self)
        form.addRow("Rater ID:", self.rater_input)

        subject = self._session.subject
        self.subject_input = QLineEdit(subject.id if subject is not None else "", self)
        form.addRow("Subject ID:", self.subject_input)

        self.condition_input = QLineEdit(subject.condition if subject is not None else "", self)
        form.addRow("Condition:", self.condition_input)

        self.med_state_input = QLineEdit(subject.medication_state if subject is not None else "", self)
        form.addRow("Medication state:", self.med_state_input)

        self.session_start_input = QLineEdit(self._session.session_start_utc, self)
        self.session_start_input.setPlaceholderText("2024-03-01T09:31:22Z")
        form.addRow("Session start UTC:", self.session_start_input)

        self.timing_verified_checkbox = QCheckBox(
            "Annotation times are verified to be relative to recording start (required for BIDS export).",
            self,
        )
        self.timing_verified_checkbox.setChecked(
            self._session.provenance.recording_relative_timing_verified
        )
        form.addRow("BIDS timing:", self.timing_verified_checkbox)
        tooltip = (
            "Enable this only if annotation timestamps are already measured from recording start "
            "(t=0 at recording onset). Leave it unchecked if times may instead be relative to the "
            "first labeled event, an imported tier offset, or any other non-recording origin."
        )
        self.timing_verified_checkbox.setToolTip(tooltip)

        self.timing_help_label = QLabel(
            "Check this only after confirming annotation times are truly recording-relative. "
            "This controls whether BIDS export is allowed.",
            self,
        )
        self.timing_help_label.setWordWrap(True)
        self.timing_help_label.setToolTip(tooltip)
        form.addRow("", self.timing_help_label)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str | bool]:
        return {
            "name": self.name_input.text().strip(),
            "rater": self.rater_input.text().strip(),
            "subject_id": self.subject_input.text().strip(),
            "condition": self.condition_input.text().strip(),
            "medication_state": self.med_state_input.text().strip(),
            "session_start_utc": self.session_start_input.text().strip(),
            "recording_relative_timing_verified": self.timing_verified_checkbox.isChecked(),
        }

    def accept(self) -> None:
        values = self.values()
        if not values["name"]:
            QMessageBox.warning(self, "Missing Name", "Session name cannot be blank.")
            return
        if values["session_start_utc"]:
            try:
                datetime.fromisoformat(values["session_start_utc"].replace("Z", "+00:00"))
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid UTC Timestamp",
                    "Session start UTC must be empty or use ISO 8601 format, for example 2024-03-01T09:31:22Z.",
                )
                return
        super().accept()

    @classmethod
    def edit_session(
        cls,
        session: Session,
        parent: QWidget | None = None,
    ) -> dict[str, str | bool] | None:
        dialog = cls(session, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.values()
