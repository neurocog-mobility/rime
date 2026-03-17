"""Dockable clinical outcomes panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from rime_core.context import WorkingContext
from rime_core.coverage import CoverageSpec, compute_coverage
from rime_core.export import export_session_report
from rime_core.session import ClinicalMetricSpec
from rime_ui.theme import (
    COLOR_PANEL_BG,
    COLOR_LOOP_BORDER,
    COLOR_LOOP_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SOFT,
    DOCK_CONTENT_MARGIN,
    DOCK_MIN_WIDTH,
    RADIUS_LG,
    SPACE_SM,
    panel_card_stylesheet,
    set_layout_metrics,
    set_zero_margins,
)


class _SpecRow(QWidget):
    changed = Signal()
    remove_requested = Signal(QWidget)

    def __init__(self, lanes: list[tuple[str, list[str]]], parent=None) -> None:
        super().__init__(parent)
        self._lanes = list(lanes)
        layout = QHBoxLayout(self)
        set_zero_margins(layout, spacing=6)

        self.lane_combo = QComboBox(self)
        for lane_name, _labels in self._lanes:
            self.lane_combo.addItem(lane_name, lane_name)
        self.lane_combo.currentIndexChanged.connect(self._populate_labels)
        self.lane_combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        layout.addWidget(self.lane_combo, 1)

        self.label_combo = QComboBox(self)
        self.label_combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        layout.addWidget(self.label_combo, 1)

        remove_button = QPushButton("Remove")
        remove_button.setProperty("role", "remove")
        remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove_button)

        self._populate_labels()

    def set_spec(self, spec: CoverageSpec) -> None:
        index = self.lane_combo.findData(spec.lane)
        if index >= 0:
            self.lane_combo.setCurrentIndex(index)
        label_index = self.label_combo.findData(spec.label)
        if label_index >= 0:
            self.label_combo.setCurrentIndex(label_index)

    def spec(self) -> CoverageSpec:
        return CoverageSpec(
            lane=str(self.lane_combo.currentData()),
            label=self.label_combo.currentData(),
        )

    def _populate_labels(self) -> None:
        lane_name = str(self.lane_combo.currentData())
        labels = next((labels for lane, labels in self._lanes if lane == lane_name), [])
        current = self.label_combo.currentData()
        self.label_combo.blockSignals(True)
        self.label_combo.clear()
        self.label_combo.addItem("All", None)
        for label in labels:
            self.label_combo.addItem(label, label)
        index = self.label_combo.findData(current)
        self.label_combo.setCurrentIndex(index if index >= 0 else 0)
        self.label_combo.blockSignals(False)


class ClinicalPanel(QWidget):
    """Configure and display live coverage metrics."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(DOCK_MIN_WIDTH)
        self._context: WorkingContext | None = None
        self._duration_ms = 0.0
        self._session_id = ""
        self._active_metric_name: str | None = None
        self._numerator_rows: list[_SpecRow] = []
        self._denominator_rows: list[_SpecRow] = []
        self._setup_ui()
        self.refresh(None, 0.0)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout, margins=DOCK_CONTENT_MARGIN)

        self.placeholder = QLabel("Open a session to compute clinical outcomes.")
        self.placeholder.setWordWrap(True)
        layout.addWidget(self.placeholder)

        self.content = QWidget(self)
        content_layout = QVBoxLayout(self.content)
        set_zero_margins(content_layout, spacing=8)

        # ── Card 1: Metric value (primary focal point) ─────────────────────
        self.value_frame = QFrame(self)
        self.value_frame.setObjectName("metricValueCard")
        self.value_frame.setStyleSheet(
            f"#metricValueCard {{ background-color: {COLOR_PANEL_BG};"
            f" border: 2px solid {COLOR_LOOP_BORDER};"
            f" border-radius: {RADIUS_LG}px; }}"
        )
        value_layout = QVBoxLayout(self.value_frame)
        set_layout_metrics(value_layout, spacing=SPACE_SM)

        self._card_name_label = QLabel("—")
        self._card_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_name_label.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        value_layout.addWidget(self._card_name_label)

        self.value_label = QLabel("—")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pct_font = QFont()
        pct_font.setPointSize(28)
        pct_font.setBold(True)
        self.value_label.setFont(pct_font)
        self.value_label.setStyleSheet(
            f"color: {COLOR_LOOP_TEXT}; border: none; background: transparent;"
        )
        value_layout.addWidget(self.value_label)

        inner_div = QFrame(self.value_frame)
        inner_div.setFrameShape(QFrame.Shape.HLine)
        inner_div.setFrameShadow(QFrame.Shadow.Plain)
        inner_div.setStyleSheet(f"background-color: {COLOR_LOOP_BORDER}; border: none;")
        value_layout.addWidget(inner_div)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)

        num_head = QLabel("Numerator")
        num_head.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        self._num_episodes_label = QLabel("—")
        self._num_episodes_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._num_episodes_label.setStyleSheet("border: none; background: transparent;")
        self._num_time_label = QLabel("—")
        self._num_time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._num_time_label.setStyleSheet(
            f"color: {COLOR_TEXT_SOFT}; border: none; background: transparent;"
        )
        grid.addWidget(num_head, 0, 0)
        grid.addWidget(self._num_episodes_label, 0, 1)
        grid.addWidget(self._num_time_label, 0, 2)

        denom_head = QLabel("Denominator")
        denom_head.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        self._denom_episodes_label = QLabel("—")
        self._denom_episodes_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._denom_episodes_label.setStyleSheet(
            "border: none; background: transparent;"
        )
        self._denom_time_label = QLabel("—")
        self._denom_time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._denom_time_label.setStyleSheet(
            f"color: {COLOR_TEXT_SOFT}; border: none; background: transparent;"
        )
        grid.addWidget(denom_head, 1, 0)
        grid.addWidget(self._denom_episodes_label, 1, 1)
        grid.addWidget(self._denom_time_label, 1, 2)

        value_layout.addLayout(grid)
        content_layout.addWidget(self.value_frame)

        # ── Card 2: Saved metrics ──────────────────────────────────────────
        saved_card = QFrame(self)
        saved_card.setObjectName("savedMetricsCard")
        saved_card.setStyleSheet(panel_card_stylesheet("savedMetricsCard"))
        saved_layout = QVBoxLayout(saved_card)
        set_layout_metrics(saved_layout, spacing=SPACE_SM)

        saved_header = QLabel("Saved Metrics")
        saved_header.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        saved_layout.addWidget(saved_header)

        self.saved_metrics = QListWidget(saved_card)
        self.saved_metrics.currentRowChanged.connect(self._load_saved_metric_from_row)
        saved_layout.addWidget(self.saved_metrics)
        content_layout.addWidget(saved_card, 1)

        # ── Card 3: Metric builder ─────────────────────────────────────────
        builder_card = QFrame(self)
        builder_card.setObjectName("metricBuilderCard")
        builder_card.setStyleSheet(panel_card_stylesheet("metricBuilderCard"))
        builder_layout = QVBoxLayout(builder_card)
        set_layout_metrics(builder_layout, spacing=SPACE_SM)

        builder_header = QLabel("Configure Metric")
        builder_header.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;"
        )
        builder_layout.addWidget(builder_header)

        header_row = QHBoxLayout()
        self.metric_name_input = QLineEdit(builder_card)
        self.metric_name_input.setPlaceholderText("Metric name")
        self.metric_name_input.textChanged.connect(self._update_active_metric_display)
        header_row.addWidget(self.metric_name_input, 1)
        save_button = QPushButton("Save")
        save_button.setProperty("role", "positive")
        save_button.clicked.connect(self._save_metric)
        header_row.addWidget(save_button)
        delete_button = QPushButton("Delete")
        delete_button.setProperty("role", "destructive")
        delete_button.clicked.connect(self._delete_metric)
        header_row.addWidget(delete_button)
        builder_layout.addLayout(header_row)

        self.numerator_box = QGroupBox("Numerator", builder_card)
        self.numerator_layout = QVBoxLayout(self.numerator_box)
        set_layout_metrics(self.numerator_layout)
        builder_layout.addWidget(self.numerator_box)
        add_numerator_button = QPushButton("Add Numerator Row")
        # add_numerator_button.setProperty("role", "positive")
        add_numerator_button.clicked.connect(lambda: self._add_spec_row("numerator"))
        add_numerator_button.setToolTip(
            "Add another lane or label rule to the numerator."
        )
        builder_layout.addWidget(add_numerator_button)

        self.denominator_box = QGroupBox("Denominator", builder_card)
        denominator_layout = QVBoxLayout(self.denominator_box)
        set_layout_metrics(denominator_layout)
        radio_row = QHBoxLayout()
        self.session_radio = QRadioButton("Session duration", builder_card)
        self.lane_radio = QRadioButton("Lane/label", builder_card)
        self.session_radio.toggled.connect(self._on_denominator_mode_changed)
        radio_row.addWidget(self.session_radio)
        radio_row.addWidget(self.lane_radio)
        radio_row.addStretch(1)
        denominator_layout.addLayout(radio_row)
        self.denominator_rows_widget = QWidget(self.denominator_box)
        self.denominator_rows_layout = QVBoxLayout(self.denominator_rows_widget)
        set_zero_margins(self.denominator_rows_layout)
        denominator_layout.addWidget(self.denominator_rows_widget)
        builder_layout.addWidget(self.denominator_box)
        add_denominator_button = QPushButton("Add Denominator Row")
        # add_denominator_button.setProperty("role", "positive")
        add_denominator_button.clicked.connect(
            lambda: self._add_spec_row("denominator")
        )
        add_denominator_button.setToolTip(
            "Add another lane or label rule to the denominator."
        )
        builder_layout.addWidget(add_denominator_button)

        content_layout.addWidget(builder_card)

        export_button = QPushButton("Export Session Report...")
        export_button.clicked.connect(self._export_report)
        content_layout.addWidget(export_button)

        layout.addWidget(self.content)

    def refresh(self, context: WorkingContext | None, duration_ms: float) -> None:
        self._context = context
        self._duration_ms = duration_ms
        has_context = context is not None
        self.placeholder.setVisible(not has_context)
        self.content.setVisible(has_context)
        if not has_context or context is None:
            return

        if self._session_id != context.session.id:
            self._session_id = context.session.id
            self._reset_editor()
            if context.session.clinical_metrics:
                self._load_metric(context.session.clinical_metrics[0])
            else:
                self.metric_name_input.clear()
                self._add_spec_row("numerator")
                self.session_radio.setChecked(True)
        self._refresh_saved_metric_list()
        self._update_active_metric_display()

    def _reset_editor(self) -> None:
        self._active_metric_name = None
        self._clear_rows("numerator")
        self._clear_rows("denominator")

    def _clear_rows(self, kind: str) -> None:
        rows = self._numerator_rows if kind == "numerator" else self._denominator_rows
        layout = (
            self.numerator_layout
            if kind == "numerator"
            else self.denominator_rows_layout
        )
        for row in rows:
            layout.removeWidget(row)
            row.deleteLater()
        rows.clear()

    def _lane_choices(self) -> list[tuple[str, list[str]]]:
        if self._context is None:
            return []
        return [
            (lane.name, list(lane.labels))
            for lane in self._context.schema.lanes
            if lane.lane_type == "interval" and lane.name.casefold() != "notes"
        ]

    def _add_spec_row(self, kind: str, spec: CoverageSpec | None = None) -> None:
        if self._context is None:
            return
        row = _SpecRow(self._lane_choices(), self)
        if spec is not None:
            row.set_spec(spec)
        row.changed.connect(self._update_active_metric_display)
        row.remove_requested.connect(lambda widget: self._remove_spec_row(kind, widget))
        if kind == "numerator":
            self._numerator_rows.append(row)
            self.numerator_layout.addWidget(row)
        else:
            self._denominator_rows.append(row)
            self.denominator_rows_layout.addWidget(row)
        self._update_active_metric_display()

    def _remove_spec_row(self, kind: str, widget: QWidget) -> None:
        rows = self._numerator_rows if kind == "numerator" else self._denominator_rows
        layout = (
            self.numerator_layout
            if kind == "numerator"
            else self.denominator_rows_layout
        )
        if len(rows) <= 1:
            return
        rows.remove(widget)  # type: ignore[arg-type]
        layout.removeWidget(widget)
        widget.deleteLater()
        self._update_active_metric_display()

    def _on_denominator_mode_changed(self) -> None:
        use_rows = self.lane_radio.isChecked()
        self.denominator_rows_widget.setVisible(use_rows)
        if use_rows and not self._denominator_rows:
            self._add_spec_row("denominator")
        self._update_active_metric_display()

    def _current_metric_spec(self) -> ClinicalMetricSpec | None:
        if self._context is None or not self._numerator_rows:
            return None
        name = self.metric_name_input.text().strip()
        numerator = [self._spec_to_dict(row.spec()) for row in self._numerator_rows]
        denominator_type = "lane" if self.lane_radio.isChecked() else "session"
        denominator = (
            [self._spec_to_dict(row.spec()) for row in self._denominator_rows]
            if denominator_type == "lane"
            else []
        )
        return ClinicalMetricSpec(
            name=name,
            numerator=numerator,
            denominator_type=denominator_type,
            denominator=denominator,
        )

    def _update_active_metric_display(self) -> None:
        if self._context is None:
            return
        metric = self._current_metric_spec()
        if metric is None:
            self._card_name_label.setText("—")
            self.value_label.setText("—")
            for lbl in (
                self._num_episodes_label,
                self._num_time_label,
                self._denom_episodes_label,
                self._denom_time_label,
            ):
                lbl.setText("—")
            return
        self._card_name_label.setText(metric.name or "Unsaved metric")

        numerator_specs = [CoverageSpec(**spec) for spec in metric.numerator]
        denominator_specs = (
            None
            if metric.denominator_type == "session"
            else [CoverageSpec(**spec) for spec in metric.denominator]
        )
        result = compute_coverage(
            self._context.store,
            numerator_specs,
            denominator=denominator_specs,
            session_duration_ms=self._duration_ms,
        )
        self.value_label.setText(
            "—" if result.denominator_ms <= 0 else f"{result.percent:.1f} %"
        )
        denom_ep = (
            "—"
            if result.denominator_episodes < 0
            else f"{result.denominator_episodes} ep"
        )
        self._num_episodes_label.setText(f"{result.numerator_episodes} ep")
        self._num_time_label.setText(self._format_duration(result.numerator_ms))
        self._denom_episodes_label.setText(denom_ep)
        self._denom_time_label.setText(self._format_duration(result.denominator_ms))
        self._refresh_saved_metric_list()

    def _refresh_saved_metric_list(self) -> None:
        if self._context is None:
            return
        current_name = self._active_metric_name
        self.saved_metrics.blockSignals(True)
        self.saved_metrics.clear()
        selected_row = -1
        for index, metric in enumerate(self._context.session.clinical_metrics):
            numerator_specs = [CoverageSpec(**spec) for spec in metric.numerator]
            denominator_specs = (
                None
                if metric.denominator_type == "session"
                else [CoverageSpec(**spec) for spec in metric.denominator]
            )
            result = compute_coverage(
                self._context.store,
                numerator_specs,
                denominator=denominator_specs,
                session_duration_ms=self._duration_ms,
            )
            value_text = "—" if result.denominator_ms <= 0 else f"{result.percent:.1f}%"
            self.saved_metrics.addItem(f"{metric.name}    {value_text}")
            if metric.name == current_name:
                selected_row = index
        if selected_row >= 0:
            self.saved_metrics.setCurrentRow(selected_row)
        self.saved_metrics.blockSignals(False)

    def _load_saved_metric_from_row(self, row: int) -> None:
        if (
            self._context is None
            or row < 0
            or row >= len(self._context.session.clinical_metrics)
        ):
            return
        self._load_metric(self._context.session.clinical_metrics[row])

    def _load_metric(self, metric: ClinicalMetricSpec) -> None:
        self._reset_editor()
        self._active_metric_name = metric.name
        self.metric_name_input.setText(metric.name)
        for spec in metric.numerator:
            self._add_spec_row("numerator", CoverageSpec(**spec))

        self.session_radio.blockSignals(True)
        self.lane_radio.blockSignals(True)
        if metric.denominator_type == "lane":
            self.lane_radio.setChecked(True)
            for spec in metric.denominator:
                self._add_spec_row("denominator", CoverageSpec(**spec))
            if not metric.denominator:
                self._add_spec_row("denominator")
        else:
            self.session_radio.setChecked(True)
        self.session_radio.blockSignals(False)
        self.lane_radio.blockSignals(False)
        self.denominator_rows_widget.setVisible(metric.denominator_type == "lane")
        self._update_active_metric_display()

    def _save_metric(self) -> None:
        if self._context is None:
            return
        metric = self._current_metric_spec()
        if metric is None or not metric.name:
            QMessageBox.warning(
                self, "Missing Name", "Enter a metric name before saving."
            )
            return
        metrics = [
            saved
            for saved in self._context.session.clinical_metrics
            if saved.name != metric.name
        ]
        metrics.append(metric)
        self._context.update_clinical_metrics(metrics)
        self._active_metric_name = metric.name
        self._refresh_saved_metric_list()

    def _delete_metric(self) -> None:
        if self._context is None:
            return
        name = self.metric_name_input.text().strip()
        if not name:
            return
        metrics = [
            saved
            for saved in self._context.session.clinical_metrics
            if saved.name != name
        ]
        self._context.update_clinical_metrics(metrics)
        self._active_metric_name = None
        self._reset_editor()
        self.metric_name_input.clear()
        self._add_spec_row("numerator")
        self.session_radio.setChecked(True)
        self._refresh_saved_metric_list()

    def _export_report(self) -> None:
        if self._context is None:
            return
        default_name = f"{self._context.session.name}_report.tsv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Session Report",
            str(Path(default_name)),
            "TSV (*.tsv);;All Files (*)",
        )
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix == "":
            output_path = output_path.with_suffix(".tsv")
        export_session_report(
            self._context.store,
            self._context.session,
            output_path,
            duration_ms=self._duration_ms,
        )

    @staticmethod
    def _format_duration(ms: float) -> str:
        total_s = ms / 1000.0
        if total_s < 60:
            return f"{total_s:.1f} s"
        minutes = int(total_s) // 60
        seconds = total_s - minutes * 60
        return f"{minutes}:{seconds:04.1f}"

    @staticmethod
    def _spec_to_dict(spec: CoverageSpec) -> dict[str, str | None]:
        return {"lane": spec.lane, "label": spec.label}
