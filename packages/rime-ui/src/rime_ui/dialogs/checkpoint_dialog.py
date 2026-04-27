"""Dialogs for checkpoint creation and restore."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rime_core.checkpoints import CheckpointEntry, KIND_MANUAL
from rime_ui.theme import COLOR_WARNING_ACCENT, set_layout_metrics


class RestoreCheckpointDialog(QDialog):
    """Select one checkpoint to restore."""

    def __init__(
        self,
        checkpoints: list[CheckpointEntry],
        checkpoint_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._checkpoints = checkpoints
        self._checkpoint_dir = Path(checkpoint_dir)
        self.setWindowTitle("Restore Checkpoint")
        self.setMinimumWidth(520)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout)

        intro = QLabel("Select a checkpoint to restore.", self)
        layout.addWidget(intro)

        manual_count = sum(1 for entry in self._checkpoints if entry.kind == KIND_MANUAL)
        self.warning_label = QLabel(
            "Manual checkpoints exceed 20. Consider pruning old manual checkpoints.",
            self,
        )
        self.warning_label.setStyleSheet(f"color: {COLOR_WARNING_ACCENT};")
        self.warning_label.setVisible(manual_count > 20)
        layout.addWidget(self.warning_label)

        self.list_widget = QListWidget(self)
        for entry in self._checkpoints:
            label = f"{entry.label}    {self._format_timestamp(entry.created)}"
            item = QListWidgetItem(label, self.list_widget)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            kind_suffix = self._kind_suffix(entry.kind)
            if kind_suffix:
                item.setToolTip(f"{entry.label} ({kind_suffix})")
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.open_folder_button = buttons.addButton("Open Folder", QDialogButtonBox.ButtonRole.ActionRole)
        self.open_folder_button.clicked.connect(self._open_checkpoint_folder)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setProperty("role", "primary")
        layout.addWidget(buttons)

    def selected_checkpoint_id(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def _open_checkpoint_folder(self) -> None:
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(self._checkpoint_dir)])
                return
            if os.name == "nt":
                subprocess.Popen(["explorer", str(self._checkpoint_dir)])
                return
            subprocess.Popen(["xdg-open", str(self._checkpoint_dir)])
            return
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._checkpoint_dir)))

    @staticmethod
    def _kind_suffix(kind: str) -> str:
        mapping = {
            "session_open": "session opened",
            "pre_destructive": "pre-destructive",
            "manual": "manual",
            "restore_guard": "restore guard",
        }
        return mapping.get(kind, kind)

    @staticmethod
    def _format_timestamp(value: str) -> str:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return dt.strftime("%Y-%m-%d  %H:%M")
