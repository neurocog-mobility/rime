"""Dockable model evaluation panel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.cmf import CMFPackage
from rime_core.evaluation import EvalResult, evaluate_model
from rime_core.inference import OutputMapping
from rime_ui.theme import DOCK_CONTENT_MARGIN, DOCK_MIN_WIDTH, set_layout_metrics


@dataclass(frozen=True)
class TargetSignature:
    lane: str
    label: str
    event_type: str

    def display_text(self) -> str:
        suffix = " (point)" if self.event_type == "point" else ""
        return f"{self.lane}:{self.label}{suffix}"


class ModelEvalPanel(QWidget):
    """Display evaluation metrics for one selected target across loaded models."""

    _ROWS = [
        "Predictions",
        "TP / FP / FN",
        "Threshold",
        "IoU",
        "F1",
        "Precision",
        "Recall",
        "Onset Error",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(DOCK_MIN_WIDTH)
        self._loaded_models: dict[str, CMFPackage] = {}
        self._targets_by_model: dict[str, list[TargetSignature]] = {}
        self._store: AnnotationStore | None = None
        self._duration_ms = 0.0
        self._session_name = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout, margins=DOCK_CONTENT_MARGIN)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Target:"))
        self.target_combo = QComboBox(self)
        self.target_combo.currentIndexChanged.connect(self._refresh_table)
        selector_row.addWidget(self.target_combo, 1)
        layout.addLayout(selector_row)

        self.header_label = QLabel("No models loaded.")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)

        self.table = QTableWidget(0, 1, self)
        self.table.setHorizontalHeaderLabels(["Metric"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.export_button = QPushButton("Export Metrics...")
        self.export_button.clicked.connect(self._export_metrics)
        button_row.addWidget(self.export_button)
        layout.addLayout(button_row)

    def refresh(
        self,
        loaded_models: dict[str, CMFPackage],
        targets_by_model: dict[str, list[OutputMapping]],
        store: AnnotationStore | None,
        duration_ms: float,
        session_name: str,
    ) -> None:
        self._loaded_models = dict(loaded_models)
        self._targets_by_model = {
            model_name: [self._signature_from_mapping(model, mapping) for mapping in mappings]
            for model_name, (model, mappings) in (
                (name, (loaded_models[name], targets_by_model.get(name, [])))
                for name in loaded_models
            )
        }
        self._store = store
        self._duration_ms = duration_ms
        self._session_name = session_name
        self._refresh_targets()
        self._refresh_table()

    def _refresh_targets(self) -> None:
        current = self.current_target()
        available: list[TargetSignature] = []
        seen: set[TargetSignature] = set()
        for model_name in sorted(self._targets_by_model):
            for signature in self._targets_by_model[model_name]:
                if signature not in seen:
                    seen.add(signature)
                    available.append(signature)

        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for signature in available:
            self.target_combo.addItem(signature.display_text(), signature)

        selected = current if current in available else self._default_target(available)
        if selected is not None:
            index = available.index(selected)
            self.target_combo.setCurrentIndex(index)
        self.target_combo.blockSignals(False)

    def _default_target(self, available: list[TargetSignature]) -> TargetSignature | None:
        if not available:
            return None
        if self._store is not None:
            for signature in available:
                for model_name in self._loaded_models:
                    if self._predictions_for(model_name, signature):
                        return signature
        return available[0]

    def current_target(self) -> TargetSignature | None:
        if self.target_combo.currentIndex() < 0:
            return None
        value = self.target_combo.currentData()
        return value if isinstance(value, TargetSignature) else None

    def _refresh_table(self) -> None:
        target = self.current_target()
        model_names = sorted(self._loaded_models)
        self.table.setColumnCount(len(model_names) + 1)
        self.table.setHorizontalHeaderLabels(["Metric", *model_names])
        self.table.setRowCount(len(self._ROWS))
        for row, label in enumerate(self._ROWS):
            self.table.setItem(row, 0, QTableWidgetItem(label))

        if target is None:
            self.header_label.setText("No models loaded.")
            self._fill_empty_columns(model_names)
            self.export_button.setEnabled(False)
            return

        ground_truth = self._ground_truth_for(target)
        if ground_truth:
            self.header_label.setText(
                f"Ground truth: {len(ground_truth)} episodes (manual · {target.lane}:{target.label})"
            )
        else:
            self.header_label.setText(
                "No human annotations found on the selected target. Annotate the session first, then run inference to compare."
            )

        for column, model_name in enumerate(model_names, start=1):
            self._set_model_column(column, model_name, target, ground_truth)

        self.export_button.setEnabled(bool(model_names and target))
        self.table.resizeColumnsToContents()

    def _fill_empty_columns(self, model_names: list[str]) -> None:
        for column in range(1, len(model_names) + 1):
            for row in range(len(self._ROWS)):
                self._set_cell(row, column, "—")

    def _set_model_column(
        self,
        column: int,
        model_name: str,
        target: TargetSignature,
        ground_truth: list[Annotation],
    ) -> None:
        if target not in self._targets_by_model.get(model_name, []):
            for row in range(len(self._ROWS)):
                self._set_cell(row, column, "—")
            return

        predictions = self._predictions_for(model_name, target)
        has_any_predictions = self._has_any_predictions_for_model(model_name)
        result = (
            evaluate_model(predictions, ground_truth, self._duration_ms)
            if self._duration_ms > 0 and ground_truth
            else None
        )
        predictions_text = "Not yet run" if not predictions and not has_any_predictions else f"{len(predictions)} ep."
        self._set_cell(0, column, predictions_text)
        self._set_cell(
            1,
            column,
            "—" if result is None else f"{result.n_tp} / {result.n_fp} / {result.n_fn}",
        )
        self._set_cell(2, column, f"{self._loaded_models[model_name].config.threshold:.2f}")
        self._set_cell(3, column, self._metric_text(result, "iou"))
        self._set_cell(4, column, self._metric_text(result, "f1"))
        self._set_cell(5, column, self._metric_text(result, "precision"))
        self._set_cell(6, column, self._metric_text(result, "recall"))
        if result is None or result.onset_error_ms == float("inf"):
            self._set_cell(7, column, "—")
        else:
            sd_text = "—" if result.onset_error_sd_ms == float("inf") else f"{result.onset_error_sd_ms:.0f}"
            self._set_cell(7, column, f"{result.onset_error_ms:.0f} ± {sd_text} ms")

    def _metric_text(self, result: EvalResult | None, name: str) -> str:
        if result is None:
            return "—"
        return f"{getattr(result, name):.2f}"

    def _set_cell(self, row: int, column: int, value: str) -> None:
        item = self.table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, column, item)
        item.setText(value)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _ground_truth_for(self, target: TargetSignature) -> list[Annotation]:
        if self._store is None:
            return []
        return [
            annotation
            for annotation in self._store.all()
            if not annotation.ghost
            and annotation.source in {"manual", "elan_import"}
            and self._signature_from_annotation(annotation) == target
        ]

    def _predictions_for(self, model_name: str, target: TargetSignature) -> list[Annotation]:
        if self._store is None:
            return []
        source = f"model:{model_name}"
        return [
            annotation
            for annotation in self._store.all()
            if annotation.source == source and self._signature_from_annotation(annotation) == target
        ]

    def _has_any_predictions_for_model(self, model_name: str) -> bool:
        if self._store is None:
            return False
        source = f"model:{model_name}"
        return any(annotation.source == source for annotation in self._store.all())

    def _export_metrics(self) -> None:
        target = self.current_target()
        if target is None:
            return
        default_name = f"{self._session_name or 'session'}_model_metrics.tsv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Model Metrics",
            str(Path(default_name)),
            "TSV (*.tsv);;All Files (*)",
        )
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".tsv")

        lines = [
            "# RIME Model Evaluation",
            f"# Session:   {self._session_name or 'Unknown'}",
            f"# Target:    {target.display_text()}",
            f"# Ground truth: {len(self._ground_truth_for(target))} episodes (manual, {target.lane}:{target.label})",
            "#",
        ]
        headers = ["Metric", *sorted(self._loaded_models)]
        lines.append("\t".join(headers))
        for row, label in enumerate(self._ROWS):
            values = [self.table.item(row, column).text() if self.table.item(row, column) else "—" for column in range(1, self.table.columnCount())]
            lines.append("\t".join([label, *values]))
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _signature_from_annotation(annotation: Annotation) -> TargetSignature:
        return TargetSignature(annotation.lane, annotation.label, annotation.event_type)

    @staticmethod
    def _signature_from_mapping(model: CMFPackage, mapping: OutputMapping) -> TargetSignature:
        output_types = {
            str(output.get("name", "")): str(output.get("type", "interval")).casefold()
            for output in model.config.outputs
        }
        event_type = "point" if output_types.get(mapping.output_name, "interval") == "point" else "interval"
        return TargetSignature(mapping.lane, mapping.label, event_type)
