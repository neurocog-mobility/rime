"""Model package preview dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rime_core.cmf import CMFLoader, CMFPackage, CMFValidationError
from rime_ui.theme import muted_text_stylesheet, set_layout_metrics, set_zero_margins


class ModelLoaderDialog(QDialog):
    """Preview a CMF package before loading it into the session."""

    def __init__(self, package: CMFPackage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.package = package
        self.setWindowTitle("Load Model")
        self.setMinimumSize(640, 480)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout)

        summary_box = QGroupBox("Model Summary", self)
        summary_box_layout = QVBoxLayout(summary_box)
        set_layout_metrics(summary_box_layout)

        summary_layout = QFormLayout()
        summary_layout.addRow("Name:", QLabel(self.package.config.name, summary_box))
        summary_layout.addRow("Version:", QLabel(self.package.config.version, summary_box))
        summary_layout.addRow("CMF Version:", QLabel(self.package.config.cmf_version, summary_box))
        summary_layout.addRow("Inference Mode:", QLabel(self.package.config.inference_mode, summary_box))
        summary_layout.addRow("Threshold:", QLabel(f"{self.package.config.threshold:g}", summary_box))
        path_label = QLabel(str(self.package.path), summary_box)
        path_label.setWordWrap(True)
        summary_layout.addRow("Path:", path_label)
        if self.package.config.license:
            summary_layout.addRow("License:", QLabel(self.package.config.license, summary_box))
        summary_box_layout.addLayout(summary_layout)
        if self.package.config.description:
            summary_box_layout.addWidget(QLabel("Description:", summary_box))
            description = QTextEdit(summary_box)
            description.setReadOnly(True)
            description.setPlainText(self.package.config.description)
            description.setMinimumHeight(150)
            summary_box_layout.addWidget(description)
        layout.addWidget(summary_box)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(
            self._build_table_widget(
                ["Name", "Type", "Details"],
                self._input_rows(),
                "No declared inputs",
            ),
            "Inputs",
        )
        self.tabs.addTab(
            self._build_table_widget(
                ["Name", "Type", "Description"],
                self._output_rows(),
                "No declared outputs",
            ),
            "Outputs",
        )
        self.tabs.addTab(
            self._build_table_widget(
                ["Output", "Lane", "Label"],
                self._mapping_rows(),
                "No default output mappings",
            ),
            "Mappings",
        )
        self.tabs.addTab(
            self._build_table_widget(
                ["Name", "Type", "Default", "Description"],
                self._parameter_rows(),
                "No configurable parameters",
            ),
            "Parameters",
        )
        self.tabs.addTab(
            self._build_table_widget(
                ["Package", "Import", "Install Hint", "Status"],
                self._requirement_rows(),
                "No declared Python requirements",
            ),
            "Requirements",
        )
        layout.addWidget(self.tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        self.load_button = QPushButton("Load Model", self)
        self.load_button.setDefault(True)
        self.load_button.setProperty("role", "primary")
        self.load_button.clicked.connect(self.accept)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.load_button)
        layout.addLayout(button_row)

    def _build_table_widget(
        self,
        headers: list[str],
        rows: list[list[str]],
        empty_message: str,
    ) -> QWidget:
        widget = QWidget(self)
        box_layout = QVBoxLayout(widget)
        set_zero_margins(box_layout)
        placeholder = QLabel(empty_message, widget)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(muted_text_stylesheet())
        table = QTableWidget(len(rows), len(headers), widget)
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        if rows:
            for row_index, row in enumerate(rows):
                for col_index, value in enumerate(row):
                    table.setItem(row_index, col_index, QTableWidgetItem(value))
            table.resizeColumnsToContents()
            placeholder.hide()
            box_layout.addWidget(table)
        else:
            table.hide()
            box_layout.addWidget(placeholder, 1)
        return widget

    def _input_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for item in self.package.config.inputs:
            details: list[str] = []
            if item.get("sampling_rate_hz"):
                details.append(f"{item['sampling_rate_hz']} Hz")
            channels = item.get("channels")
            if isinstance(channels, list) and channels:
                details.append(", ".join(str(channel) for channel in channels))
            description = item.get("description")
            if description:
                details.append(str(description))
            rows.append(
                [
                    str(item.get("name", "")),
                    str(item.get("type", "")),
                    " · ".join(details),
                ]
            )
        return rows

    def _output_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for item in self.package.config.outputs:
            rows.append(
                [
                    str(item.get("name", "")),
                    str(item.get("type", "")),
                    str(item.get("description", "")),
                ]
            )
        return rows

    def _mapping_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for item in self.package.config.output_mappings:
            rows.append(
                [
                    str(item.get("output_name", "")),
                    str(item.get("lane", "")),
                    str(item.get("label", "")),
                ]
            )
        return rows

    def _parameter_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for item in self.package.config.parameters:
            default = item.get("default")
            default_text = "" if default is None else str(default)
            rows.append(
                [
                    str(item.get("label") or item.get("name", "")),
                    str(item.get("type", "")),
                    default_text,
                    str(item.get("description", "")),
                ]
            )
        return rows

    def _requirement_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        missing_imports = {
            item.requirement.import_name
            for item in self.package.missing_requirements()
        }
        for item in self.package.config.requirements:
            rows.append(
                [
                    item.package,
                    item.import_name,
                    item.install_hint,
                    "Missing" if item.import_name in missing_imports else "Available",
                ]
            )
        return rows

    @classmethod
    def choose_model_path(cls, parent: QWidget | None = None) -> str | None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            parent,
            "Select Model Package (.rime folder)",
        )
        if not directory:
            return None

        try:
            package = CMFLoader.load(directory)
        except CMFValidationError as exc:
            QMessageBox.critical(parent, "Model Error", f"Failed to inspect model:\n{exc}")
            return None
        except Exception as exc:
            QMessageBox.critical(parent, "Model Error", f"Unexpected model inspection failure:\n{exc}")
            return None

        dialog = cls(package, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return directory

    @classmethod
    def choose_loaded_package(cls, parent: QWidget | None = None) -> CMFPackage | None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            parent,
            "Select Model Package (.rime folder)",
        )
        if not directory:
            return None

        try:
            package = CMFLoader.load(directory)
        except CMFValidationError as exc:
            QMessageBox.critical(parent, "Model Error", f"Failed to inspect model:\n{exc}")
            return None
        except Exception as exc:
            QMessageBox.critical(parent, "Model Error", f"Unexpected model inspection failure:\n{exc}")
            return None

        dialog = cls(package, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return package
