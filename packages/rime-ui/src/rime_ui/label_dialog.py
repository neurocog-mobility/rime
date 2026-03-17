"""Label picker dialog for annotation creation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from rime_core.schema import ProtocolSchema
from rime_core.rule_engine import Violation
from rime_ui.schema_view import SchemaView
from rime_ui.theme import label_dialog_stylesheet, set_layout_metrics
from rime_ui.violation_dialog import ViolationDialog


@dataclass(frozen=True)
class LabelDialogDecision:
    """Outcome from the label dialog when editing an existing annotation."""

    label: str | None = None
    fix_violation: Violation | None = None


class LabelDialog(QDialog):
    """Dialog for selecting an annotation label."""

    def __init__(
        self,
        level: int,
        schema: ProtocolSchema,
        current_label: str | None = None,
        violations: list[Violation] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.level = level
        self.current_label = current_label
        self.selected_label: str | None = None
        self.fix_violation: Violation | None = None
        self._violations = list(violations or [])

        # Load config
        self.config = SchemaView(schema)
        lane_config = self.config.get_lane_config(self.level) or {}
        self._is_notes_lane = lane_config.get("name", "").strip().lower() == "notes"

        self._setup_ui()
        self._apply_style()

    def _setup_ui(self) -> None:
        """Create dialog UI."""
        lane_config = self.config.get_lane_config(self.level)
        level_name = lane_config["name"] if lane_config else "Annotation"
        # Make singular for title if ends in 's'
        display_name = level_name[:-1] if level_name.endswith("s") else level_name

        self.setWindowTitle(f"Select {display_name} Label")
        self.setMinimumSize(300, 250)

        layout = QVBoxLayout(self)

        # Header
        if self._is_notes_lane:
            header = QLabel("Enter note text for this annotation:")
        else:
            header = QLabel(f"Choose a label for this {display_name.lower()}:")
        layout.addWidget(header)

        if self._violations:
            warning_frame = QFrame(self)
            warning_frame.setObjectName("warningFrame")
            warning_layout = QVBoxLayout(warning_frame)
            set_layout_metrics(warning_layout)

            warning_title = QLabel("Warnings for this annotation:")
            warning_title.setObjectName("warningTitle")
            warning_layout.addWidget(warning_title)

            self.warning_list = QListWidget(warning_frame)
            for violation in self._violations:
                self.warning_list.addItem(QListWidgetItem(violation.message))
            self.warning_list.currentRowChanged.connect(self._on_warning_selected)
            warning_layout.addWidget(self.warning_list)

            self.fix_button = QPushButton("Apply Suggested Fix")
            self.fix_button.clicked.connect(self._on_apply_fix)
            warning_layout.addWidget(self.fix_button)

            layout.addWidget(warning_frame)
            self.warning_list.setCurrentRow(0)
        else:
            self.warning_list = None
            self.fix_button = None

        # Label list
        self.label_list = QListWidget()
        labels = self.config.get_labels(self.level)
        for label in labels:
            item = QListWidgetItem(label)
            self.label_list.addItem(item)

        self.label_list.currentItemChanged.connect(self._on_item_selected)
        self.label_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.label_list)
        if self._is_notes_lane:
            self.label_list.setEnabled(False)

        text_header = QLabel("Note text:" if self._is_notes_lane else "Label text:")
        layout.addWidget(text_header)

        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText(
            "Type note details..."
            if self._is_notes_lane
            else "Enter annotation text..."
        )
        layout.addWidget(self.label_input)

        # Selection defaults
        if self.current_label:
            row = self._find_row(self.current_label)
            if row >= 0:
                self.label_list.setCurrentRow(row)
            self.label_input.setText(self.current_label)
        elif self.label_list.count() > 0 and not self._is_notes_lane:
            self.label_list.setCurrentRow(0)

        self.label_input.setFocus()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.setProperty("role", "primary")
        ok_btn.clicked.connect(self._on_accept)
        button_layout.addWidget(ok_btn)

        layout.addLayout(button_layout)

    def _apply_style(self) -> None:
        """Apply dark theme styling."""
        self.setStyleSheet(label_dialog_stylesheet())

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Handle double-click on label item."""
        if self._is_notes_lane:
            return
        self._on_accept()

    def _on_item_selected(self, current: QListWidgetItem | None, _: QListWidgetItem | None) -> None:
        """Prefill editable text when selecting from the list."""
        if self._is_notes_lane:
            return
        if current is None:
            return
        self.label_input.setText(current.text())

    def _on_accept(self) -> None:
        """Handle OK button click."""
        text = self.label_input.text().strip()
        if not text:
            current = self.label_list.currentItem()
            if current:
                text = current.text().strip()
        if not text:
            QMessageBox.warning(self, "Missing Label", "Enter label text before continuing.")
            return
        self.selected_label = text
        self.accept()

    def _on_warning_selected(self, row: int) -> None:
        if self.fix_button is None:
            return
        violation = self._violations[row] if 0 <= row < len(self._violations) else None
        if violation is None or not violation.can_auto_fix or violation.fix_annotation is None:
            self.fix_button.setEnabled(False)
            self.fix_button.setText("No Auto-Fix Available")
            return
        self.fix_button.setEnabled(True)
        self.fix_button.setText(ViolationDialog.fix_label(violation))

    def _on_apply_fix(self) -> None:
        if self.warning_list is None:
            return
        row = self.warning_list.currentRow()
        if row < 0 or row >= len(self._violations):
            return
        violation = self._violations[row]
        if not violation.can_auto_fix or violation.fix_annotation is None:
            return
        self.fix_violation = violation
        self.accept()

    def _find_row(self, text: str) -> int:
        for index in range(self.label_list.count()):
            item = self.label_list.item(index)
            if item and item.text() == text:
                return index
        return -1

    @classmethod
    def get_label(cls, level: int, schema: ProtocolSchema, parent=None) -> str | None:
        """Show dialog and return selected label, or None if cancelled."""
        dialog = cls(level, schema=schema, parent=parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_label
        return None

    @classmethod
    def edit_label(
        cls,
        level: int,
        schema: ProtocolSchema,
        current_label: str,
        violations: list[Violation] | None = None,
        parent=None,
    ) -> LabelDialogDecision | None:
        """Show dialog prefilled with existing label text for editing."""
        dialog = cls(
            level,
            schema=schema,
            current_label=current_label,
            violations=violations,
            parent=parent,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return LabelDialogDecision(
                label=dialog.selected_label,
                fix_violation=dialog.fix_violation,
            )
        return None
