"""Dockable model status and evaluation panel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.cmf import CMFPackage
from rime_core.evaluation import EvalResult, evaluate_model
from rime_ui.theme import DOCK_CONTENT_MARGIN, DOCK_MIN_WIDTH, set_layout_metrics


@dataclass(frozen=True)
class _Signature:
    lane: str
    label: str
    event_type: str


class ModelPanel(QWidget):
    """Displays model status and live evaluation metrics for the active session."""

    run_requested = Signal()
    settings_requested = Signal()
    review_requested = Signal()

    _ROWS: list[tuple[str, Callable[[EvalResult], float]]] = [
        ("IoU", lambda result: result.iou),
        ("F1", lambda result: result.f1),
        ("Precision", lambda result: result.precision),
        ("Recall", lambda result: result.recall),
        ("Onset Error", lambda result: result.onset_error_ms),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(DOCK_MIN_WIDTH)
        self._setup_ui()
        self.refresh(None, None, 0.0, "—")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout, margins=DOCK_CONTENT_MARGIN)

        status_layout = QGridLayout()
        status_layout.setHorizontalSpacing(8)
        status_layout.setVerticalSpacing(6)

        self.model_value = QLabel("—")
        self.inputs_value = QLabel("—")
        self.status_value = QLabel("No model annotations")
        self.model_value.setWordWrap(True)
        self.inputs_value.setWordWrap(True)
        self.status_value.setWordWrap(True)
        for label in (self.model_value, self.inputs_value, self.status_value):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.review_button = QPushButton("Review")
        self.review_button.clicked.connect(self.review_requested.emit)

        self.run_button = QPushButton("Run")
        self.run_button.setProperty("role", "positive")
        self.run_button.clicked.connect(self.run_requested.emit)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.settings_requested.emit)

        model_row = QHBoxLayout()
        model_row.addWidget(self.model_value, stretch=1)
        model_row.addWidget(self.settings_button)
        model_row.addWidget(self.run_button)

        status_layout.addWidget(QLabel("Model:"), 0, 0)
        status_layout.addLayout(model_row, 0, 1)
        status_layout.addWidget(QLabel("Inputs:"), 1, 0)
        status_layout.addWidget(self.inputs_value, 1, 1)
        status_layout.addWidget(QLabel("Status:"), 2, 0)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_value, stretch=1)
        status_row.addWidget(self.review_button)
        status_layout.addLayout(status_row, 2, 1)
        layout.addLayout(status_layout)

        self.metrics_table = QTableWidget(len(self._ROWS), 3)
        self.metrics_table.setHorizontalHeaderLabels(["Metric", "Model", "Accepted"])
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.metrics_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.metrics_table.setAlternatingRowColors(True)
        self.metrics_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.metrics_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metrics_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.metrics_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for row, (label, _getter) in enumerate(self._ROWS):
            metric_item = QTableWidgetItem(label)
            self.metrics_table.setItem(row, 0, metric_item)
        layout.addWidget(self.metrics_table)

    def refresh(
        self,
        model: CMFPackage | None,
        store: AnnotationStore | None,
        duration_ms: float,
        input_desc: str,
    ) -> None:
        enabled = model is not None
        self.run_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
        self.review_button.setEnabled(False)
        self.model_value.setText(self._model_text(model))
        self.inputs_value.setText(input_desc or "—")

        if model is None:
            self.status_value.setText("No model loaded")
            self._clear_metrics()
            return

        model_annotations = self._model_annotations(model, store)
        pending = sum(1 for ann in model_annotations if ann.ghost)
        accepted = sum(1 for ann in model_annotations if not ann.ghost)
        if model_annotations:
            self.status_value.setText(
                f"{pending} ghost annotations pending ({accepted} accepted)"
            )
            self.review_button.setEnabled(pending > 0)
        else:
            self.status_value.setText("No model annotations in this session")

        metrics_model, metrics_accepted = self._metrics(model, store, duration_ms)
        self._populate_metrics(metrics_model, metrics_accepted)

    def _populate_metrics(
        self,
        model_metrics: EvalResult | None,
        accepted_metrics: EvalResult | None,
    ) -> None:
        for row, (_label, getter) in enumerate(self._ROWS):
            self._set_metric_value(row, 1, self._format_metric(row, getter, model_metrics))
            self._set_metric_value(row, 2, self._format_metric(row, getter, accepted_metrics))

    def _clear_metrics(self) -> None:
        for row in range(len(self._ROWS)):
            self._set_metric_value(row, 1, "—")
            self._set_metric_value(row, 2, "—")

    def _set_metric_value(self, row: int, column: int, value: str) -> None:
        item = self.metrics_table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            self.metrics_table.setItem(row, column, item)
        item.setText(value)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _metrics(
        self,
        model: CMFPackage,
        store: AnnotationStore | None,
        duration_ms: float,
    ) -> tuple[EvalResult | None, EvalResult | None]:
        if store is None or duration_ms <= 0:
            return None, None

        model_annotations = self._model_annotations(model, store)
        accepted_annotations = [ann for ann in model_annotations if not ann.ghost]
        signatures = self._target_signatures(model)
        ground_truth = [
            ann
            for ann in store.all()
            if not ann.ghost
            and ann.source in {"manual", "elan_import"}
            and self._annotation_signature(ann) in signatures
        ]

        if not ground_truth:
            return None, None

        if self._has_mixed_event_types(model_annotations, ground_truth):
            return None, None

        return (
            evaluate_model(model_annotations, ground_truth, duration_ms),
            evaluate_model(accepted_annotations, ground_truth, duration_ms),
        )

    def _model_annotations(self, model: CMFPackage, store: AnnotationStore | None) -> list[Annotation]:
        if store is None:
            return []
        source = self._model_source(model)
        return [ann for ann in store.all() if ann.source == source]

    @staticmethod
    def _model_source(model: CMFPackage) -> str:
        return f"model:{model.name}"

    def _target_signatures(self, model: CMFPackage) -> set[_Signature]:
        output_types = {
            str(output.get("name", "")): str(output.get("type", "interval")).casefold()
            for output in model.config.outputs
        }
        signatures: set[_Signature] = set()
        for mapping in model.config.output_mappings:
            output_type = output_types.get(mapping["output_name"], "interval")
            event_type = "point" if output_type == "point" else "interval"
            signatures.add(
                _Signature(
                    lane=mapping["lane"],
                    label=mapping["label"],
                    event_type=event_type,
                )
            )
        return signatures

    @staticmethod
    def _annotation_signature(annotation: Annotation) -> _Signature:
        return _Signature(annotation.lane, annotation.label, annotation.event_type)

    @staticmethod
    def _has_mixed_event_types(*annotation_groups: list[Annotation]) -> bool:
        event_types = {
            annotation.event_type
            for annotations in annotation_groups
            for annotation in annotations
        }
        return len(event_types) > 1

    @staticmethod
    def _model_text(model: CMFPackage | None) -> str:
        if model is None:
            return "—"
        return f"{model.name} v{model.config.version}"

    @staticmethod
    def _format_metric(
        row: int,
        getter: Callable[[EvalResult], float],
        result: EvalResult | None,
    ) -> str:
        if result is None:
            return "—"

        value = getter(result)
        if row in {0, 1, 2, 3}:
            return f"{value:.2f}"
        if row == 4:
            if value == float("inf"):
                return "—"
            return f"{value:.0f}ms"
        return f"{value:.1f}%"
