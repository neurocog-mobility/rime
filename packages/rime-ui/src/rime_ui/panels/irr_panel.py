"""Dockable inter-rater reliability panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.io import (
    derive_matched_episode_interval,
    export_irr_report,
    export_matched_episode_parquet,
)
from rime_core.irr import IRRResult, compute_irr, format_irr_value
from rime_core.sessions import Session
from rime_ui.theme import (
    COLOR_IRR_FAIR,
    COLOR_IRR_POOR,
    COLOR_TEXT_MUTED,
    DOCK_CONTENT_MARGIN,
    DOCK_MIN_WIDTH,
    SPACE_SM,
    panel_card_stylesheet,
    set_layout_metrics,
    set_zero_margins,
)


_MODE_SYMBOLS = {
    "average": "avg",
    "intersection": "∩",
    "union": "∪",
    "rater_a": "A",
    "rater_b": "B",
}
class IRRPanel(QWidget):
    """Compute and display pairwise IRR for the current session and a comparison store."""

    filters_changed = Signal(object, object, object)
    result_changed = Signal(object)
    matched_episode_store_changed = Signal(object)
    close_requested = Signal()

    _SUMMARY_ROWS = [
        "Session A events",
        "Session B events",
        "Matched pairs",
        "Unmatched (A only)",
        "Unmatched (B only)",
        "Match rate",
        "Mean overlap",
        "Cohen's κ",
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

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.scroll_area)

        scroll_content = QWidget(self.scroll_area)
        scroll_layout = QVBoxLayout(scroll_content)
        set_zero_margins(scroll_layout, spacing=8)

        self.placeholder = QLabel(
            "Load a comparison session via Review -> Compare Session... to compute IRR.",
            scroll_content,
        )
        self.placeholder.setWordWrap(True)
        scroll_layout.addWidget(self.placeholder)

        self.content = QWidget(scroll_content)
        content_layout = QVBoxLayout(self.content)
        set_zero_margins(content_layout, spacing=8)

        source_card = QFrame(self)
        source_card.setObjectName("irrSourceCard")
        source_card.setStyleSheet(panel_card_stylesheet("irrSourceCard"))
        source_layout = QVBoxLayout(source_card)
        set_layout_metrics(source_layout, spacing=SPACE_SM)

        source_header = QLabel("Source Selection", source_card)
        source_header.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        source_layout.addWidget(source_header)

        self.session_a_label = QLabel("Session A: —", source_card)
        self.session_b_label = QLabel("Session B: —", source_card)
        source_layout.addWidget(self.session_a_label)
        source_layout.addWidget(self.session_b_label)

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

        compute_row = QVBoxLayout()
        set_zero_margins(compute_row, spacing=6)
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Average", "average")
        self.mode_combo.addItem("Intersection", "intersection")
        self.mode_combo.addItem("Union", "union")
        self.mode_combo.addItem("Rater A", "rater_a")
        self.mode_combo.addItem("Rater B", "rater_b")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.compute_button = QPushButton("Compute", self)
        self.compute_button.setProperty("role", "primary")
        self.compute_button.clicked.connect(self._compute)
        compute_row.addWidget(self.compute_button)
        compute_row.addWidget(QLabel("Matched-episode mode:", source_card))
        compute_row.addWidget(self.mode_combo)
        source_layout.addLayout(controls)
        source_layout.addLayout(compute_row)

        self.status_label = QLabel("Select a lane and press Compute.", source_card)
        self.status_label.setWordWrap(True)
        source_layout.addWidget(self.status_label)
        content_layout.addWidget(source_card)

        overview_card = QFrame(self)
        overview_card.setObjectName("irrOverviewCard")
        overview_card.setStyleSheet(panel_card_stylesheet("irrOverviewCard"))
        overview_layout = QVBoxLayout(overview_card)
        set_layout_metrics(overview_layout, spacing=SPACE_SM)

        self.summary_title = QLabel("Overview", overview_card)
        self.summary_title.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        overview_layout.addWidget(self.summary_title)
        self.summary_table = QTableWidget(len(self._SUMMARY_ROWS), 2, overview_card)
        self.summary_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.summary_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, label in enumerate(self._SUMMARY_ROWS):
            self.summary_table.setItem(row, 0, QTableWidgetItem(label))
            self.summary_table.setItem(row, 1, QTableWidgetItem("—"))
        overview_layout.addWidget(self.summary_table)
        content_layout.addWidget(overview_card)

        per_label_card = QFrame(self)
        per_label_card.setObjectName("irrPerLabelCard")
        per_label_card.setStyleSheet(panel_card_stylesheet("irrPerLabelCard"))
        per_label_layout = QVBoxLayout(per_label_card)
        set_layout_metrics(per_label_layout, spacing=SPACE_SM)

        self.per_label_title = QLabel("Per-label Comparison", per_label_card)
        self.per_label_title.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        per_label_layout.addWidget(self.per_label_title)
        self.per_label_table = QTableWidget(0, 9, per_label_card)
        self.per_label_table.setHorizontalHeaderLabels(
            ["Label", "A events", "B events", "Matched", "A only", "B only", "Match rate", "Mean overlap", "κ"]
        )
        self.per_label_table.horizontalHeaderItem(6).setToolTip("Matched / max(A events, B events)")
        self.per_label_table.horizontalHeaderItem(7).setToolTip("Temporal set IoU: intersection / union of annotation masks")
        self.per_label_table.horizontalHeaderItem(8).setToolTip("Cohen's kappa")
        self.per_label_table.verticalHeader().setVisible(False)
        self.per_label_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.per_label_table.setSortingEnabled(True)
        self.per_label_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.per_label_table.horizontalHeader().setStretchLastSection(True)
        per_label_layout.addWidget(self.per_label_table)
        content_layout.addWidget(per_label_card)

        export_row = QHBoxLayout()
        self.export_matched_button = QPushButton("Export Matched Data...", self)
        self.export_matched_button.clicked.connect(self._export_matched_episodes)
        export_row.addWidget(self.export_matched_button)
        export_row.addStretch(1)
        self.export_button = QPushButton("Export IRR Report", self)
        self.export_button.clicked.connect(self._export_report)
        export_row.addWidget(self.export_button)
        content_layout.addLayout(export_row)

        button_row = QHBoxLayout()
        self.close_button = QPushButton("Close Comparison", self)
        self.close_button.setProperty("role", "destructive")
        self.close_button.clicked.connect(self.close_requested.emit)
        button_row.addWidget(self.close_button)
        button_row.addStretch(1)
        content_layout.addLayout(button_row)

        self._size_tables()
        scroll_layout.addWidget(self.content)
        self.scroll_area.setWidget(scroll_content)

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
        self.matched_episode_store_changed.emit(None)
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
            annotation.lane for annotation in self._store_a.all()
            if not annotation.ghost and annotation.event_type != "point"
        } if self._store_a else set()
        lanes_b = {
            annotation.lane for annotation in self._store_b.all()
            if not annotation.ghost and annotation.event_type != "point"
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

    def current_mode(self) -> str:
        value = self.mode_combo.currentData()
        return value if isinstance(value, str) else "average"

    def _reset_tables(self) -> None:
        for row in range(len(self._SUMMARY_ROWS)):
            self._set_summary_value(row, "—")
        self.per_label_table.setRowCount(0)
        self.status_label.setText("Select a lane and press Compute.")
        self.export_matched_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self._size_tables()

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
        self._emit_matched_episode_store()
        self.export_matched_button.setEnabled(bool(self._result.matched_episodes))
        self.export_button.setEnabled(True)
        self.result_changed.emit(self._result)

    def _populate_summary(self) -> None:
        assert self._result is not None
        n_matched = len(self._result.matched_episodes)
        n_unmatched_a = len(self._result.unmatched_a)
        n_unmatched_b = len(self._result.unmatched_b)
        total_a = n_matched + n_unmatched_a
        total_b = n_matched + n_unmatched_b
        denom = max(total_a, total_b)
        match_rate = n_matched / denom if denom > 0 else float("nan")
        values = [
            str(total_a),
            str(total_b),
            str(n_matched),
            str(n_unmatched_a),
            str(n_unmatched_b),
            f"{format_irr_value(match_rate, percent=True)}%",
            f"{format_irr_value(self._result.set_iou, percent=True)}%",
            format_irr_value(self._result.cohens_kappa),
        ]
        for row, value in enumerate(values):
            self._set_summary_value(row, value)

    def _populate_per_label(self) -> None:
        assert self._result is not None
        self.per_label_table.setSortingEnabled(False)
        self.per_label_table.setRowCount(len(self._result.per_label))
        for row, label in enumerate(sorted(self._result.per_label)):
            item = self._result.per_label[label]
            total_a = item.matched + item.unmatched_a
            total_b = item.matched + item.unmatched_b
            denom = max(total_a, total_b)
            match_rate = item.matched / denom if denom > 0 else float("nan")
            values = [
                item.label,
                str(total_a),
                str(total_b),
                str(item.matched),
                str(item.unmatched_a),
                str(item.unmatched_b),
                f"{format_irr_value(match_rate, percent=True)}%",
                f"{format_irr_value(item.set_iou, percent=True)}%",
                format_irr_value(item.cohens_kappa),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 8 and value != "—":
                    kappa = item.cohens_kappa
                    if kappa < 0.4:
                        cell.setBackground(QColor(COLOR_IRR_POOR))
                    elif kappa < 0.6:
                        cell.setBackground(QColor(COLOR_IRR_FAIR))
                self.per_label_table.setItem(row, column, cell)
        self.per_label_table.setSortingEnabled(True)
        self.per_label_table.resizeColumnsToContents()
        self._size_tables()

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

    def _export_matched_episodes(self) -> None:
        if self._result is None or self._session_a is None or self._session_b is None:
            return
        mode = self.current_mode()
        default_name = f"{self._session_a.name}_vs_{self._session_b.name}_matched-{mode}.parquet"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Matched-Episode Dataset",
            str(Path(default_name)),
            "Parquet (*.parquet);;All Files (*)",
        )
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".parquet")
        export_matched_episode_parquet(
            self._result,
            self._session_a,
            self._session_b,
            output_path,
            lane=self.current_lane(),
            source_a=self.current_source_a(),
            source_b=self.current_source_b(),
            mode=mode,
        )

    def _on_lane_changed(self) -> None:
        self._refresh_sources()
        self._reset_tables()
        self.matched_episode_store_changed.emit(None)
        self._emit_filters_changed()
        self.result_changed.emit(None)

    def _on_source_changed(self) -> None:
        self._reset_tables()
        self.matched_episode_store_changed.emit(None)
        self._emit_filters_changed()
        self.result_changed.emit(None)

    def _on_mode_changed(self) -> None:
        if self._result is None:
            return
        self._emit_matched_episode_store()

    def _emit_matched_episode_store(self) -> None:
        if self._result is None:
            self.matched_episode_store_changed.emit(None)
            return
        store = AnnotationStore()
        mode = self.current_mode()
        for ann_a, ann_b in self._result.matched_episodes:
            interval = derive_matched_episode_interval(ann_a, ann_b, mode)
            if interval is None:
                continue
            start_ms, end_ms = interval
            store.add(
                Annotation(
                    id=f"matched:{mode}:{ann_a.id}:{ann_b.id}",
                    lane=ann_a.lane,
                    label=ann_a.label,
                    event_type=ann_a.event_type,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source=f"matched:{mode}",
                )
            )
        self.matched_episode_store_changed.emit((store, f"M ({_MODE_SYMBOLS[mode]})"))

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

    def _size_tables(self) -> None:
        self.summary_table.setFixedHeight(
            self._table_height_for_rows(self.summary_table, len(self._SUMMARY_ROWS))
        )
        visible_rows = min(6, max(1, self.per_label_table.rowCount()))
        self.per_label_table.setFixedHeight(
            self._table_height_for_rows(self.per_label_table, visible_rows)
        )

    @staticmethod
    def _table_height_for_rows(table: QTableWidget, visible_rows: int) -> int:
        header_height = table.horizontalHeader().height()
        frame_height = table.frameWidth() * 2
        row_height = table.verticalHeader().defaultSectionSize()
        scrollbar_height = table.horizontalScrollBar().sizeHint().height()
        needs_h_scroll = table.horizontalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        return header_height + frame_height + (row_height * max(1, visible_rows)) + (
            scrollbar_height if needs_h_scroll else 0
        )
