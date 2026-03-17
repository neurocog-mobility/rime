"""Keyboard shortcut reference dialog."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rime_ui.shortcuts import build_shortcut_sections


class ShortcutHelpDialog(QDialog):
    """Grouped, read-only shortcut reference."""

    def __init__(self, shortcuts: dict[str, str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setMinimumSize(640, 480)
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        note = QLabel(
            "Shortcuts are grouped by task. Timeline nudging applies when the timeline "
            "has focus and a selection is active."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        sections = build_shortcut_sections(shortcuts)
        row_count = sum(len(section.entries) + 1 for section in sections)
        table = QTableWidget(row_count, 2)
        table.setHorizontalHeaderLabels(["Shortcut", "Action"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        header_font = QFont(table.font())
        header_font.setBold(True)

        row = 0
        for section in sections:
            section_item = QTableWidgetItem(section.title)
            section_item.setFont(header_font)
            table.setItem(row, 0, section_item)
            table.setSpan(row, 0, 1, 2)
            row += 1
            for entry in section.entries:
                table.setItem(row, 0, QTableWidgetItem(entry.shortcut))
                table.setItem(row, 1, QTableWidgetItem(entry.action))
                row += 1

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
