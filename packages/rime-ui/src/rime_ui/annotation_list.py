"""Dockable annotation list panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rime_core.annotations import AnnotationStore
from rime_core.schema import ProtocolSchema
from rime_ui.schema_view import SchemaView
from rime_ui.theme import DOCK_CONTENT_MARGIN, DOCK_MIN_WIDTH, set_layout_metrics


class AnnotationListPanel(QWidget):
    """Table view of all annotations with lane filtering."""

    annotation_activated = Signal(str)
    annotation_edit_requested = Signal(str)
    confidence_changed = Signal(str, float)

    _COLUMNS = ["Lane", "Label", "Start", "End", "Duration", "Source", "Ghost", "Confidence"]
    _CONFIDENCE_ROLE = Qt.ItemDataRole.UserRole + 1

    class _ConfidenceDelegate(QStyledItemDelegate):
        def displayText(self, value, locale) -> str:
            del locale
            try:
                percent = float(value)
            except (TypeError, ValueError):
                return "—"
            return f"{percent:.0f}%"

        def createEditor(self, parent, option, index):  # noqa: ANN001
            del option, index
            editor = QDoubleSpinBox(parent)
            editor.setRange(0.0, 100.0)
            editor.setDecimals(0)
            editor.setSuffix("%")
            return editor

        def setEditorData(self, editor, index) -> None:  # noqa: ANN001
            value = index.data(Qt.ItemDataRole.EditRole)
            editor.setValue(float(value) if value is not None else 100.0)

        def setModelData(self, editor, model, index) -> None:  # noqa: ANN001
            model.setData(index, float(editor.value()), Qt.ItemDataRole.EditRole)

    def __init__(self, schema: ProtocolSchema, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(DOCK_MIN_WIDTH)
        self.config = SchemaView(schema)
        self._store: AnnotationStore | None = None
        self._updating_table = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout, margins=DOCK_CONTENT_MARGIN)

        header = QHBoxLayout()
        header.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All")
        for lane in self.config.get_lane_names():
            self.filter_combo.addItem(lane)
        self.filter_combo.currentTextChanged.connect(lambda _: self.refresh())
        header.addWidget(self.filter_combo, stretch=1)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(self._COLUMNS))
        self.table.setHorizontalHeaderLabels(self._COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.EditKeyPressed
        )
        self.table.setSortingEnabled(True)
        self.table.itemClicked.connect(self._on_item_clicked)
        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setItemDelegateForColumn(7, self._ConfidenceDelegate(self.table))
        layout.addWidget(self.table)

    def set_store(self, store: AnnotationStore | None) -> None:
        self._store = store
        self.refresh()

    def set_schema(self, schema: ProtocolSchema) -> None:
        self.config.set_schema(schema)
        current = self.filter_combo.currentText()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem("All")
        for lane in self.config.get_lane_names():
            self.filter_combo.addItem(lane)
        index = self.filter_combo.findText(current)
        self.filter_combo.setCurrentIndex(index if index >= 0 else 0)
        self.filter_combo.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        self._updating_table = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        if self._store is None:
            self.table.setSortingEnabled(True)
            self._updating_table = False
            return

        filter_lane = self.filter_combo.currentText()
        annotations = sorted(
            self._store.annotations.values(),
            key=lambda ann: (ann.start_ms, ann.end_ms, ann.id),
        )
        for ann in annotations:
            if filter_lane != "All" and ann.lane != filter_lane:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            lane_item = QTableWidgetItem(ann.lane)
            lane_item.setData(Qt.ItemDataRole.UserRole, ann.id)
            lane_item.setFlags(lane_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, lane_item)
            self.table.setItem(row, 1, self._readonly_item(ann.label))
            self.table.setItem(row, 2, self._readonly_item(self._format_time(ann.start_ms)))
            self.table.setItem(row, 3, self._readonly_item(self._format_time(ann.end_ms)))
            self.table.setItem(row, 4, self._readonly_item(self._format_time(ann.duration_ms)))
            self.table.setItem(row, 5, self._readonly_item(ann.source))
            self.table.setItem(row, 6, self._readonly_item("Yes" if ann.ghost else "No"))

            confidence_item = QTableWidgetItem()
            confidence_item.setData(Qt.ItemDataRole.UserRole, ann.id)
            confidence_item.setData(Qt.ItemDataRole.EditRole, float(ann.confidence * 100.0))
            confidence_item.setData(self._CONFIDENCE_ROLE, float(ann.confidence))
            confidence_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            confidence_item.setForeground(self._confidence_color(ann.confidence))
            confidence_item.setFlags(
                Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            self.table.setItem(row, 7, confidence_item)

        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self._updating_table = False

    def select_annotation(self, ann_id: str | None) -> None:
        self.table.blockSignals(True)
        try:
            if not ann_id:
                self.table.clearSelection()
                return
            for row in range(self.table.rowCount()):
                if self._annotation_id_for_row(row) == ann_id:
                    self.table.setCurrentCell(row, 0)
                    self.table.selectRow(row)
                    return
            self.table.clearSelection()
        finally:
            self.table.blockSignals(False)

    def _on_item_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() == 7:
            return
        ann_id = self._annotation_id_for_row(item.row())
        if ann_id:
            self.annotation_activated.emit(ann_id)

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() == 7:
            self.table.editItem(item)
            return
        ann_id = self._annotation_id_for_row(item.row())
        if ann_id:
            self.annotation_edit_requested.emit(ann_id)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() != 7:
            return
        ann_id = item.data(Qt.ItemDataRole.UserRole)
        if not ann_id:
            return
        try:
            percent = float(item.data(Qt.ItemDataRole.EditRole))
        except (TypeError, ValueError):
            return
        confidence = max(0.0, min(1.0, percent / 100.0))
        self.confidence_changed.emit(str(ann_id), confidence)

    def _annotation_id_for_row(self, row: int) -> str | None:
        lane_item = self.table.item(row, 0)
        if lane_item is None:
            return None
        value = lane_item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    @staticmethod
    def _readonly_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    @staticmethod
    def _confidence_color(confidence: float):
        if confidence >= 0.8:
            return Qt.GlobalColor.darkGreen
        if confidence >= 0.5:
            return Qt.GlobalColor.darkYellow
        return Qt.GlobalColor.darkRed

    @staticmethod
    def _format_time(ms: float) -> str:
        total_ms = int(max(0, ms))
        total_seconds = total_ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        millis = total_ms % 1000
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
