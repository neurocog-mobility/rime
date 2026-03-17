"""Dockable inter-rater reliability panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from rime_core.annotations import AnnotationStore
from rime_core.export import export_irr_report
from rime_core.irr import IRRResult, compute_irr, format_irr_value
from rime_core.session import Session
from rime_ui.theme import COLOR_IRR_FAIR, COLOR_IRR_POOR, DOCK_CONTENT_MARGIN, DOCK_MIN_WIDTH, set_layout_metrics, set_zero_margins


class IRRPanel(QWidget):
    """Compute and display pairwise IRR for the current session and a comparison store."""

    filters_changed = Signal(object, object, object)
    result_changed = Signal(object)
    close_requested = Signal()

    _SUMMARY_ROWS = [
        "Cohen's κ",
        "% Agreement",
        "Episode IoU (mean)",
        "Matched episodes",
        "Unmatched (Session A only)",
        "Unmatched (Session B only)",
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(DOCK_MIN_WIDTH)
        self._session_a: Session | None = None
        self._session_b: Session | None = None
        self._store_a: AnnotationStore | None = None
        self._store_b: AnnotationStore | None = None
        self._duration_ms = 0.0
        self._result: IRRResult | None = None
        self._setup_ui()
        self.refresh(None, None, None, None, 0.0)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout, margins=DOCK_CONTENT_MARGIN)

        self.placeholder = QLabel(
            "Load a comparison session via Review -> Compare Session... to compute IRR.",
            self,
        )
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)

        self.content = QWidget(self)
        content_layout = QVBoxLayout(self.content)
        set_zero_margins(content_layout, spacing=8)

        self.session_a_label = QLabel("Session A: —", self)
        self.session_b_label = QLabel("Session B: —", self)
        content_layout.addWidget(self.session_a_label)
        content_layout.addWidget(self.session_b_label)

        controls = QFormLayout()
        controls.setContentsMargins(4, 4, 4, 4)
        self.lane_combo = QComboBox(self)
        self.lane_combo.currentIndexChanged.connect(self._on_lane_changed)
        controls.addRow("Lane:", self.lane_combo)
        self.source_a_combo = QComboBox(self)
        self.source_a_combo.currentIndexChanged.connect(self._on_source_changed)
        controls.addRow("Session A source:", self.source_a_combo)
        self.source_b_combo = QComboBox(self)
        self.source_b_combo.currentIndexChanged.connect(self._on_source_changed)
        controls.addRow("Session B source:", self.source_b_combo)
        content_layout.addLayout(controls)

        compute_row = QVBoxLayout()
        self.compute_button = QPushButton("Compute", self)
        self.compute_button.setProperty("role", "primary")
        self.compute_button.clicked.connect(self._compute)
        compute_row.addWidget(self.compute_button)
        content_layout.addLayout(compute_row)

        self.status_label = QLabel("Select a lane and press Compute.", self)
        self.status_label.setWordWrap(True)
        content_layout.addWidget(self.status_label)

        self.summary_table = QTableWidget(len(self._SUMMARY_ROWS), 2, self)
        self.summary_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.summary_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for row, label in enumerate(self._SUMMARY_ROWS):
            self.summary_table.setItem(row, 0, QTableWidgetItem(label))
            self.summary_table.setItem(row, 1, QTableWidgetItem("—"))
        content_layout.addWidget(self.summary_table)

        self.per_label_table = QTableWidget(0, 7, self)
        self.per_label_table.setHorizontalHeaderLabels(
            ["Label", "κ", "% Agr.", "Episode IoU", "Matched", "A-only", "B-only"]
        )
        self.per_label_table.horizontalHeaderItem(1).setToolTip("Cohen's kappa")
        self.per_label_table.horizontalHeaderItem(2).setToolTip("Percent agreement")
        self.per_label_table.horizontalHeaderItem(3).setToolTip("Mean episode intersection-over-union")
        self.per_label_table.horizontalHeaderItem(5).setToolTip("Unmatched annotations in Session A only")
        self.per_label_table.horizontalHeaderItem(6).setToolTip("Unmatched annotations in Session B only")
        self.per_label_table.verticalHeader().setVisible(False)
        self.per_label_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.per_label_table.setSortingEnabled(True)
        content_layout.addWidget(self.per_label_table, 1)

        button_row = QHBoxLayout()
        self.close_button = QPushButton("Close Comparison", self)
        self.close_button.setProperty("role", "destructive")
        self.close_button.clicked.connect(self.close_requested.emit)
        button_row.addWidget(self.close_button)
        button_row.addStretch(1)
        self.export_button = QPushButton("Export IRR Report...", self)
        self.export_button.clicked.connect(self._export_report)
        button_row.addWidget(self.export_button)
        content_layout.addLayout(button_row)

        layout.addWidget(self.content)

    def refresh(
        self,
        session_a: Session | None,
        store_a: AnnotationStore | None,
        session_b: Session | None,
        store_b: AnnotationStore | None,
        duration_ms: float,
    ) -> None:
        self._session_a = session_a
        self._store_a = store_a
        self._session_b = session_b
        self._store_b = store_b
        self._duration_ms = duration_ms
        has_comparison = (
            session_a is not None and store_a is not None and session_b is not None and store_b is not None
        )
        self.placeholder.setVisible(not has_comparison)
        self.content.setVisible(has_comparison)
        self.close_button.setEnabled(has_comparison)
        self._result = None
        self.result_changed.emit(None)
        if not has_comparison:
            return

        self.session_a_label.setText(f"Session A: {session_a.name}  (Rater: {session_a.rater or '(no rater)'})")
        self.session_b_label.setText(f"Session B: {session_b.name}  (Rater: {session_b.rater or '(no rater)'})")
        self._refresh_lanes()
        self._refresh_sources()
        self._reset_tables()
        self._emit_filters_changed()

    def _refresh_lanes(self) -> None:
        current = self.current_lane()
        lanes_a = {
            annotation.lane for annotation in self._store_a.all() if not annotation.ghost
        } if self._store_a else set()
        lanes_b = {
            annotation.lane for annotation in self._store_b.all() if not annotation.ghost
        } if self._store_b else set()
        available = sorted(lanes_a & lanes_b)
        self.lane_combo.blockSignals(True)
        self.lane_combo.clear()
        for lane in available:
            self.lane_combo.addItem(lane, lane)
        if current in available:
            self.lane_combo.setCurrentIndex(available.index(current))
        elif available:
            self.lane_combo.setCurrentIndex(0)
        self.lane_combo.blockSignals(False)
        self.compute_button.setEnabled(self.lane_combo.count() > 0)

    def _refresh_sources(self) -> None:
        lane = self.current_lane()
        self._populate_source_combo(
            self.source_a_combo,
            self._available_sources(self._store_a, lane),
            self.current_source_a(),
        )
        self._populate_source_combo(
            self.source_b_combo,
            self._available_sources(self._store_b, lane),
            self.current_source_b(),
        )
        self.compute_button.setEnabled(
            self.lane_combo.count() > 0
            and self.source_a_combo.count() > 0
            and self.source_b_combo.count() > 0
        )

    def current_lane(self) -> str | None:
        if self.lane_combo.currentIndex() < 0:
            return None
        value = self.lane_combo.currentData()
        return value if isinstance(value, str) else None

    def current_source_a(self) -> str | None:
        return self._current_source_from_combo(self.source_a_combo)

    def current_source_b(self) -> str | None:
        return self._current_source_from_combo(self.source_b_combo)

    def _reset_tables(self) -> None:
        for row in range(len(self._SUMMARY_ROWS)):
            self._set_summary_value(row, "—")
        self.per_label_table.setRowCount(0)
        self.status_label.setText("Select a lane and press Compute.")
        self.export_button.setEnabled(False)

    def _compute(self) -> None:
        if self._store_a is None or self._store_b is None:
            return
        self._result = compute_irr(
            self._store_a,
            self._store_b,
            self._duration_ms,
            lane=self.current_lane(),
            source_a=self.current_source_a(),
            source_b=self.current_source_b(),
        )
        self._populate_summary()
        self._populate_per_label()
        if not self._result.matched_episodes and not self._result.unmatched_a and not self._result.unmatched_b:
            self.status_label.setText("No annotations found on this lane.")
        else:
            self.status_label.setText("IRR computed.")
        self.export_button.setEnabled(True)
        self.result_changed.emit(self._result)

    def _populate_summary(self) -> None:
        assert self._result is not None
        values = [
            format_irr_value(self._result.cohens_kappa),
            f"{format_irr_value(self._result.percent_agreement, percent=True)}%",
            format_irr_value(self._result.frame_iou),
            str(len(self._result.matched_episodes)),
            str(len(self._result.unmatched_a)),
            str(len(self._result.unmatched_b)),
        ]
        for row, value in enumerate(values):
            self._set_summary_value(row, value)

    def _populate_per_label(self) -> None:
        assert self._result is not None
        self.per_label_table.setSortingEnabled(False)
        self.per_label_table.setRowCount(len(self._result.per_label))
        for row, label in enumerate(sorted(self._result.per_label)):
            item = self._result.per_label[label]
            values = [
                item.label,
                format_irr_value(item.cohens_kappa),
                f"{format_irr_value(item.percent_agreement, percent=True)}%",
                format_irr_value(item.episode_iou),
                str(item.matched),
                str(item.unmatched_a),
                str(item.unmatched_b),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 1 and value != "—":
                    kappa = item.cohens_kappa
                    if kappa < 0.4:
                        cell.setBackground(QColor(COLOR_IRR_POOR))
                    elif kappa < 0.6:
                        cell.setBackground(QColor(COLOR_IRR_FAIR))
                self.per_label_table.setItem(row, column, cell)
        self.per_label_table.setSortingEnabled(True)
        self.per_label_table.resizeColumnsToContents()

    def _set_summary_value(self, row: int, value: str) -> None:
        item = self.summary_table.item(row, 1)
        if item is None:
            item = QTableWidgetItem()
            self.summary_table.setItem(row, 1, item)
        item.setText(value)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _export_report(self) -> None:
        if self._result is None or self._session_a is None or self._session_b is None:
            return
        default_name = f"{self._session_a.name}_vs_{self._session_b.name}_irr.tsv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export IRR Report",
            str(Path(default_name)),
            "TSV (*.tsv);;All Files (*)",
        )
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".tsv")
        export_irr_report(
            self._result,
            self._session_a,
            self._session_b,
            output_path,
            lane=self.current_lane(),
            source_a=self.current_source_a(),
            source_b=self.current_source_b(),
        )

    def _on_lane_changed(self) -> None:
        self._refresh_sources()
        self._reset_tables()
        self._emit_filters_changed()
        self.result_changed.emit(None)

    def _on_source_changed(self) -> None:
        self._reset_tables()
        self._emit_filters_changed()
        self.result_changed.emit(None)

    def _emit_filters_changed(self) -> None:
        self.filters_changed.emit(
            self.current_lane(),
            self.current_source_a(),
            self.current_source_b(),
        )

    def _available_sources(
        self,
        store: AnnotationStore | None,
        lane: str | None,
    ) -> list[str]:
        if store is None:
            return []
        sources = sorted(
            {
                annotation.source or "manual"
                for annotation in store.all()
                if not annotation.ghost and (lane is None or annotation.lane == lane)
            }
        )
        if "manual" in sources:
            sources.remove("manual")
            sources.insert(0, "manual")
        return sources

    def _populate_source_combo(
        self,
        combo: QComboBox,
        sources: list[str],
        current: str | None,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for source in sources:
            combo.addItem(self._display_source(source), source)
        if sources:
            selected = current if current in sources else sources[0]
            combo.setCurrentIndex(sources.index(selected))
        combo.blockSignals(False)

    @staticmethod
    def _current_source_from_combo(combo: QComboBox) -> str | None:
        if combo.currentIndex() < 0:
            return None
        value = combo.currentData()
        return value if isinstance(value, str) else None

    @staticmethod
    def _display_source(source: str) -> str:
        if source == "manual":
            return "manual"
        if source.startswith("model:"):
            return source[len("model:") :]
        if source.startswith("rater:"):
            return source[len("rater:") :]
        return source
