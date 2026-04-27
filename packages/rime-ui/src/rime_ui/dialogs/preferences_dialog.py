"""Application preferences dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rime_core.settings import AppSettings
from rime_ui.widgets.multi_view_player import SPEED_STEPS
from rime_ui.shortcuts import (
    HARD_CODED_SHORTCUT_IDS,
    SECTION_TIMELINE,
    display_shortcut,
    resolve_shortcuts,
    shortcut_bindings_by_section,
)
from rime_ui.theme import COLOR_TEXT_SUBTLE, PATH_INPUT_MIN_WIDTH


class PreferencesDialog(QDialog):
    """Edit user-level RIME preferences."""

    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        *,
        initial_tab: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._initial_tab = initial_tab
        self._validated_settings: AppSettings | None = None
        self._shortcut_edits: dict[str, QKeySequenceEdit] = {}
        self.setWindowTitle("Preferences")
        self.setMinimumSize(720, 560)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_shortcuts_tab(), "Shortcuts")
        if self._initial_tab:
            for index in range(self.tabs.count()):
                if self.tabs.tabText(index).casefold() == self._initial_tab.casefold():
                    self.tabs.setCurrentIndex(index)
                    break
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setProperty("role", "primary")
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.rater_input = QLineEdit(self._settings.default_rater, self)
        form.addRow("Default rater for new sessions:", self.rater_input)

        self.export_dir_input = QLineEdit(self._settings.default_export_dir, self)
        self.export_dir_input.setMinimumWidth(PATH_INPUT_MIN_WIDTH)
        self.export_dir_input.setPlaceholderText("Leave blank to export inside each session folder")
        browse_button = QPushButton("Browse...", self)
        browse_button.clicked.connect(self._browse_export_dir)
        browse_button.setToolTip("Choose a default export folder.")
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_dir_input, 1)
        export_row.addWidget(browse_button)
        export_container = QWidget(self)
        export_container.setLayout(export_row)
        form.addRow("Default export root (optional):", export_container)

        self.playback_speed_combo = QComboBox(self)
        for speed in SPEED_STEPS:
            self.playback_speed_combo.addItem(f"{speed:g}x", float(speed))
        current_index = min(
            range(len(SPEED_STEPS)),
            key=lambda idx: abs(SPEED_STEPS[idx] - self._settings.default_playback_speed),
        )
        self.playback_speed_combo.setCurrentIndex(current_index)
        form.addRow("Default playback speed at launch:", self.playback_speed_combo)

        layout.addLayout(form)
        layout.addStretch(1)
        return widget

    def _build_shortcuts_tab(self) -> QWidget:
        resolved = resolve_shortcuts(self._settings.shortcut_overrides)
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        hint = QLabel(
            "Use single-key or modifier chords only. Leave a field blank to unbind it. "
            "Derived edge-nudge gestures are shown for reference."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea(tab)
        scroll.setWidgetResizable(True)
        container = QWidget(scroll)
        grid = QGridLayout(container)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)

        row = 0
        for section, bindings in shortcut_bindings_by_section():
            section_label = QLabel(f"<b>{section}</b>", container)
            grid.addWidget(section_label, row, 0, 1, 4)
            row += 1
            for binding in bindings:
                if binding.id in HARD_CODED_SHORTCUT_IDS:
                    row = self._add_derived_shortcut_row(
                        grid,
                        row,
                        binding.label,
                        display_shortcut(resolved.get(binding.id, "")),
                        "Hardcoded. Not remappable.",
                        container,
                    )
                    continue
                label = QLabel(
                    f"<b>{binding.label}</b><br><span style='color:{COLOR_TEXT_SUBTLE}'>{binding.description}</span>",
                    container,
                )
                label.setWordWrap(True)
                grid.addWidget(label, row, 0)

                edit = QKeySequenceEdit(container)
                if hasattr(edit, "setMaximumSequenceLength"):
                    edit.setMaximumSequenceLength(1)
                edit.setKeySequence(QKeySequence(resolved.get(binding.id, "")))
                self._shortcut_edits[binding.id] = edit
                grid.addWidget(edit, row, 1)

                reset_button = QPushButton("Reset", container)
                reset_button.clicked.connect(
                    lambda _checked=False, target=edit, default=binding.default: target.setKeySequence(
                        QKeySequence(default)
                    )
                )
                grid.addWidget(reset_button, row, 2)

                clear_button = QPushButton("Clear", container)
                clear_button.clicked.connect(
                    lambda _checked=False, target=edit: target.clear()
                )
                grid.addWidget(clear_button, row, 3)
                row += 1
            if section == SECTION_TIMELINE:
                row = self._add_derived_shortcut_row(
                    grid,
                    row,
                    "Move point/snap or interval start",
                    "Alt + Left / Right",
                    "Hardcoded. Not remappable.",
                    container,
                )
                row = self._add_derived_shortcut_row(
                    grid,
                    row,
                    "Move interval end",
                    "Alt + Shift + Left / Right",
                    "Hardcoded. Not remappable.",
                    container,
                )

        grid.setRowStretch(row, 1)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        return tab

    def _add_derived_shortcut_row(
        self,
        grid: QGridLayout,
        row: int,
        title: str,
        shortcut_text: str,
        note: str,
        parent: QWidget,
    ) -> int:
        label = QLabel(
            f"<b>{title}</b><br><span style='color:{COLOR_TEXT_SUBTLE}'>{note}</span>",
            parent,
        )
        label.setWordWrap(True)
        grid.addWidget(label, row, 0)

        display = QLineEdit(parent)
        display.setText(shortcut_text)
        display.setReadOnly(True)
        display.setEnabled(False)
        grid.addWidget(display, row, 1)

        derived_label = QLabel("Derived", parent)
        derived_label.setEnabled(False)
        grid.addWidget(derived_label, row, 2, 1, 2)
        return row + 1

    def _browse_export_dir(self) -> None:
        current = self.export_dir_input.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Default Export Root", current)
        if path:
            self.export_dir_input.setText(path)

    def _shortcut_overrides(self) -> dict[str, str]:
        overrides: dict[str, str] = {}
        defaults = resolve_shortcuts()
        for binding_id, edit in self._shortcut_edits.items():
            sequence = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            if sequence != defaults.get(binding_id, ""):
                overrides[binding_id] = sequence
        return overrides

    def _validate_shortcuts(self) -> str | None:
        by_shortcut: dict[str, list[str]] = {}
        for _section, bindings in shortcut_bindings_by_section():
            for binding in bindings:
                if binding.id not in self._shortcut_edits:
                    continue
                text = self._shortcut_edits[binding.id].keySequence().toString(
                    QKeySequence.SequenceFormat.PortableText
                ).strip()
                if not text:
                    continue
                by_shortcut.setdefault(text.casefold(), []).append(binding.label)

        conflicts = [
            f"{', '.join(labels)} share the same shortcut"
            for labels in by_shortcut.values()
            if len(labels) > 1
        ]
        if conflicts:
            return "\n".join(conflicts)
        return None

    def to_settings(self) -> AppSettings:
        return AppSettings(
            default_rater=self.rater_input.text().strip(),
            default_export_dir=self.export_dir_input.text().strip(),
            default_playback_speed=float(self.playback_speed_combo.currentData()),
            shortcut_overrides=self._shortcut_overrides(),
        )

    def accept(self) -> None:
        conflict_message = self._validate_shortcuts()
        if conflict_message:
            QMessageBox.warning(
                self,
                "Shortcut Conflict",
                f"Each shortcut must be unique.\n\n{conflict_message}",
            )
            return
        self._validated_settings = self.to_settings()
        super().accept()

    @classmethod
    def edit_settings(
        cls,
        settings: AppSettings,
        parent: QWidget | None = None,
        *,
        initial_tab: str | None = None,
    ) -> AppSettings | None:
        dialog = cls(settings, parent, initial_tab=initial_tab)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog._validated_settings or dialog.to_settings()
