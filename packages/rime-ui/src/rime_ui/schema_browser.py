"""Dedicated schema browser/editor dialog."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rime_core.schema import (
    DEFAULT_SCHEMA_PATH,
    NOTES_ONLY_SCHEMA_PATH,
    LaneSchema,
    ProtocolSchema,
    SchemaValidationError,
)
from rime_ui.theme import COLOR_ACCENT_MUTED, COLOR_TEXT_SUBTLE, muted_text_stylesheet, set_layout_metrics, set_zero_margins


_LANE_TYPE_OPTIONS = ["interval", "point"]
_BOOL_OPTIONS = [("Yes", True), ("No", False)]
_TRIGGER_OPTIONS = ["create", "validate"]
_ACTION_OPTIONS = ["auto_create", "must_be_subset_of", "must_not_overlap", "coincidence"]
_RESOLUTION_OPTIONS = ["", "warn_and_clip"]


class SchemaBrowserWindow(QDialog):
    """Schema editor/viewer dialog used by session creation and read-only viewing."""

    schema_chosen = Signal(str, object)

    def __init__(
        self,
        schema: ProtocolSchema | None = None,
        schema_path: str | Path | None = None,
        *,
        read_only: bool = False,
        chooser_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_path: Path | None = Path(schema_path) if schema_path else None
        self._read_only = read_only
        self._chooser_mode = chooser_mode and not read_only
        self._edit_controls: list[QWidget] = []
        self._updating_lanes = False
        self.setWindowTitle("Schema Viewer" if self._read_only else "Schema Browser")
        self.setMinimumSize(760, 520)
        self.resize(1080, 760)
        self._setup_ui()

        if schema is not None:
            self.load_schema(schema, self._current_path)
        elif self._current_path is not None:
            self.load_schema_path(self._current_path)
        else:
            self.load_schema(ProtocolSchema.default(), DEFAULT_SCHEMA_PATH)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout)

        if not self._read_only:
            action_row = QHBoxLayout()
            self.new_button = QPushButton("New", self)
            self.new_button.clicked.connect(self._new_schema)
            action_row.addWidget(self.new_button)
            self.open_button = QPushButton("Open...", self)
            self.open_button.clicked.connect(self._open_schema)
            action_row.addWidget(self.open_button)
            self.save_as_button = QPushButton("Save As...", self)
            self.save_as_button.clicked.connect(self._save_schema_as)
            action_row.addWidget(self.save_as_button)
            action_row.addStretch(1)
            layout.addLayout(action_row)
            self._edit_controls.extend([self.new_button, self.open_button, self.save_as_button])

        self.path_label = QLabel("Path: (unsaved)", self)
        self.path_label.setStyleSheet(muted_text_stylesheet())
        layout.addWidget(self.path_label)

        metadata_layout = QFormLayout()
        metadata_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_input = QLineEdit(self)
        self.version_input = QLineEdit(self)
        self.name_input.setReadOnly(self._read_only)
        self.version_input.setReadOnly(self._read_only)
        metadata_layout.addRow("Schema name:", self.name_input)
        metadata_layout.addRow("Schema version:", self.version_input)
        layout.addLayout(metadata_layout)

        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        structured = QWidget(self)
        structured_layout = QVBoxLayout(structured)
        set_zero_margins(structured_layout, spacing=8)

        self.lanes_table = QTableWidget(0, 6, structured)
        self.lanes_table.setHorizontalHeaderLabels(
            ["Name", "Level", "Color", "Labels", "Type", "Allow Overlap"]
        )
        self.lanes_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.lanes_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.lanes_table.horizontalHeader().setStretchLastSection(True)
        self.lanes_table.itemChanged.connect(self._on_lanes_item_changed)
        if self._read_only:
            self.lanes_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        structured_layout.addWidget(QLabel("Lanes", structured))
        structured_layout.addWidget(self.lanes_table)
        structured_layout.addLayout(
            self._table_controls(
                self._add_lane_row,
                self._duplicate_lane_row,
                self._move_lane_row_up,
                self._move_lane_row_down,
                self._remove_lane_row,
            )
        )

        self.groups_table = QTableWidget(0, 3, structured)
        self.groups_table.setHorizontalHeaderLabels(["Name", "Lanes", "Collapsed"])
        self.groups_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.groups_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.groups_table.horizontalHeader().setStretchLastSection(True)
        if self._read_only:
            self.groups_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        structured_layout.addWidget(QLabel("Groups", structured))
        structured_layout.addWidget(self.groups_table)
        structured_layout.addLayout(
            self._table_controls(
                self._add_group_row,
                None,
                self._move_group_row_up,
                self._move_group_row_down,
                self._remove_group_row,
            )
        )

        structured_layout.addWidget(
            QLabel(
                "Rules guide lane automation and validation. Choose an action first, then fill the matching fields.",
                structured,
            )
        )
        rule_help = QLabel(
            "auto_create can copy bounds and create ghost annotations. "
            "must_not_overlap can use overlap resolution. "
            "coincidence can suggest or create a matching ghost annotation.",
            structured,
        )
        rule_help.setWordWrap(True)
        rule_help.setStyleSheet(muted_text_stylesheet(color=COLOR_TEXT_SUBTLE))
        structured_layout.addWidget(rule_help)
        self.rules_table = QTableWidget(0, 10, structured)
        self.rules_table.setHorizontalHeaderLabels(
            [
                "Trigger",
                "On Lane",
                "On Label",
                "Action",
                "Target Lane",
                "Target Label",
                "Copy Bounds",
                "Create as Ghost",
                "Overlap Resolution",
                "Message",
            ]
        )
        self.rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rules_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        if self._read_only:
            self.rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        structured_layout.addWidget(QLabel("Rules", structured))
        structured_layout.addWidget(self.rules_table)
        structured_layout.addLayout(
            self._table_controls(
                self._add_rule_row,
                self._duplicate_rule_row,
                self._move_rule_row_up,
                self._move_rule_row_down,
                self._remove_rule_row,
            )
        )

        self.tabs.addTab(structured, "Structured")

        raw_tab = QWidget(self)
        raw_layout = QVBoxLayout(raw_tab)
        set_zero_margins(raw_layout, spacing=8)
        raw_buttons = QHBoxLayout()
        self.apply_json_button = QPushButton("Apply JSON to Structured", raw_tab)
        self.apply_json_button.clicked.connect(self._apply_raw_json)
        raw_buttons.addWidget(self.apply_json_button)
        self.rebuild_json_button = QPushButton("Rebuild JSON from Structured", raw_tab)
        self.rebuild_json_button.clicked.connect(self._rebuild_raw_json)
        raw_buttons.addWidget(self.rebuild_json_button)
        raw_buttons.addStretch(1)
        raw_layout.addLayout(raw_buttons)
        self._edit_controls.extend([self.apply_json_button, self.rebuild_json_button])
        self.raw_json_edit = QPlainTextEdit(raw_tab)
        self.raw_json_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw_json_edit.setReadOnly(self._read_only)
        raw_layout.addWidget(self.raw_json_edit, 1)
        self.tabs.addTab(raw_tab, "Raw JSON")

        bottom_row = QHBoxLayout()
        self.status_label = QLabel("Ready", self)
        self.status_label.setStyleSheet(muted_text_stylesheet())
        bottom_row.addWidget(self.status_label, 1)
        if self._chooser_mode:
            self.choose_button = QPushButton("Use This Schema", self)
            self.choose_button.clicked.connect(self._choose_schema)
            bottom_row.addWidget(self.choose_button)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        bottom_row.addWidget(close_button)
        layout.addLayout(bottom_row)

        if self._read_only:
            for control in self._edit_controls:
                control.setVisible(False)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _table_controls(self, add_fn, duplicate_fn, move_up_fn, move_down_fn, remove_fn) -> QHBoxLayout:
        row = QHBoxLayout()
        add_button = QPushButton("Add", self)
        add_button.clicked.connect(add_fn)
        row.addWidget(add_button)
        self._edit_controls.append(add_button)

        if duplicate_fn is not None:
            duplicate_button = QPushButton("Duplicate", self)
            duplicate_button.clicked.connect(duplicate_fn)
            row.addWidget(duplicate_button)
            self._edit_controls.append(duplicate_button)

        move_up_button = QPushButton("Up", self)
        move_up_button.clicked.connect(move_up_fn)
        row.addWidget(move_up_button)
        self._edit_controls.append(move_up_button)

        move_down_button = QPushButton("Down", self)
        move_down_button.clicked.connect(move_down_fn)
        row.addWidget(move_down_button)
        self._edit_controls.append(move_down_button)

        remove_button = QPushButton("Remove Selected", self)
        remove_button.clicked.connect(remove_fn)
        row.addWidget(remove_button)
        self._edit_controls.append(remove_button)
        row.addStretch(1)
        return row

    def load_schema_path(self, path: str | Path) -> None:
        schema_path = Path(path)
        schema = ProtocolSchema.load(schema_path)
        self.load_schema(schema, schema_path)

    def load_schema(self, schema: ProtocolSchema, path: Path | None = None) -> None:
        self._current_path = path
        self.name_input.setText(schema.name)
        self.version_input.setText(schema.version)
        self._populate_lanes(schema)
        self._populate_groups(schema)
        self._populate_rules(schema)
        self.raw_json_edit.setPlainText(json.dumps(schema.to_dict(), indent=2))
        self._update_path_label()
        self._set_status("Schema loaded.")

    def _populate_lanes(self, schema: ProtocolSchema) -> None:
        self.lanes_table.setRowCount(0)
        for lane in schema.lanes:
            self._add_lane_row(
                lane.name,
                str(lane.level),
                lane.color,
                ", ".join(lane.labels),
                lane.lane_type,
                lane.allow_overlap,
            )
        self._refresh_lane_levels()
        self._refresh_rule_lane_options()

    def _populate_groups(self, schema: ProtocolSchema) -> None:
        self.groups_table.setRowCount(0)
        for group in schema.groups:
            lane_text = ", ".join(self._group_lane_display(group.get("lanes", []), schema))
            self._add_group_row(
                str(group.get("name", "")),
                lane_text,
                bool(group.get("collapsed", False)),
            )

    def _populate_rules(self, schema: ProtocolSchema) -> None:
        self.rules_table.setRowCount(0)
        for rule in schema.rules:
            self._add_rule_row(rule)
        self._refresh_rule_lane_options()

    def _group_lane_display(self, lanes: list[object], schema: ProtocolSchema) -> list[str]:
        labels: list[str] = []
        for item in lanes:
            if isinstance(item, int):
                lane = schema.get_lane_by_level(item)
                labels.append(lane.name if lane is not None else str(item))
            else:
                labels.append(str(item))
        return labels

    def _add_lane_row(
        self,
        name: str = "",
        level: str = "",
        color: str = COLOR_ACCENT_MUTED,
        labels: str = "",
        lane_type: str = "interval",
        allow_overlap: bool | str = True,
    ) -> None:
        row = self.lanes_table.rowCount()
        self.lanes_table.insertRow(row)
        self._updating_lanes = True
        try:
            self.lanes_table.setItem(row, 0, QTableWidgetItem(name))
            level_item = QTableWidgetItem(level)
            level_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            self.lanes_table.setItem(row, 1, level_item)
            self.lanes_table.setItem(row, 2, QTableWidgetItem(color))
            self.lanes_table.setItem(row, 3, QTableWidgetItem(labels))
            self.lanes_table.setCellWidget(row, 4, self._enum_combo(_LANE_TYPE_OPTIONS, lane_type))
            overlap_value = self._coerce_bool(allow_overlap, default=True)
            self.lanes_table.setCellWidget(row, 5, self._bool_combo(overlap_value))
        finally:
            self._updating_lanes = False
        self._refresh_lane_levels()
        self._refresh_rule_lane_options()

    def _duplicate_lane_row(self) -> None:
        row = self._selected_row(self.lanes_table)
        if row is None:
            return
        data = self._lane_rows_data()
        duplicated = dict(data[row])
        duplicated["name"] = self._duplicate_name(duplicated["name"])
        data.insert(row + 1, duplicated)
        self._replace_lane_rows(data)
        self.lanes_table.selectRow(row + 1)

    def _remove_lane_row(self) -> None:
        rows = self._selected_rows(self.lanes_table)
        if not rows or not self._confirm_removal("lane", len(rows)):
            return
        data = self._lane_rows_data()
        for row in reversed(rows):
            del data[row]
        self._replace_lane_rows(data)

    def _move_lane_row_up(self) -> None:
        self._move_row(self.lanes_table, self._lane_rows_data, self._replace_lane_rows, -1)

    def _move_lane_row_down(self) -> None:
        self._move_row(self.lanes_table, self._lane_rows_data, self._replace_lane_rows, 1)

    def _add_group_row(
        self,
        name: str = "",
        lanes: str = "",
        collapsed: bool | str = False,
    ) -> None:
        row = self.groups_table.rowCount()
        self.groups_table.insertRow(row)
        self.groups_table.setItem(row, 0, QTableWidgetItem(name))
        self.groups_table.setItem(row, 1, QTableWidgetItem(lanes))
        self.groups_table.setCellWidget(row, 2, self._bool_combo(self._coerce_bool(collapsed, default=False)))

    def _remove_group_row(self) -> None:
        rows = self._selected_rows(self.groups_table)
        if not rows or not self._confirm_removal("group", len(rows)):
            return
        data = self._group_rows_data()
        for row in reversed(rows):
            del data[row]
        self._replace_group_rows(data)

    def _move_group_row_up(self) -> None:
        self._move_row(self.groups_table, self._group_rows_data, self._replace_group_rows, -1)

    def _move_group_row_down(self) -> None:
        self._move_row(self.groups_table, self._group_rows_data, self._replace_group_rows, 1)

    def _add_rule_row(self, rule_json: dict[str, object] | str | None = None) -> None:
        if isinstance(rule_json, str):
            try:
                rule_data = json.loads(rule_json)
            except json.JSONDecodeError:
                rule_data = {}
        elif isinstance(rule_json, dict):
            rule_data = dict(rule_json)
        else:
            lane_names = self._lane_names_from_table()
            default_lane = lane_names[0] if lane_names else ""
            rule_data = {
                "trigger": "create",
                "on_lane": default_lane,
                "action": "auto_create",
                "target_lane": default_lane,
                "copy_boundaries": True,
                "ghost": True,
            }

        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        trigger_combo = self._enum_combo(_TRIGGER_OPTIONS, str(rule_data.get("trigger", "create")))
        on_lane_combo = self._lane_combo(str(rule_data.get("on_lane", "")))
        on_label_edit = self._line_edit(str(rule_data.get("on_label", "")))
        action_combo = self._enum_combo(_ACTION_OPTIONS, str(rule_data.get("action", "auto_create")))
        target_lane_combo = self._lane_combo(str(rule_data.get("target_lane", "")))
        target_label_edit = self._line_edit(str(rule_data.get("target_label", "")))
        copy_bounds_checkbox = self._checkbox(bool(rule_data.get("copy_boundaries", False)))
        ghost_checkbox = self._checkbox(bool(rule_data.get("ghost", False)))
        resolution_combo = self._enum_combo(_RESOLUTION_OPTIONS, str(rule_data.get("resolution", "")))
        message_edit = self._line_edit(str(rule_data.get("message", "")))

        widgets = {
            "trigger": trigger_combo,
            "on_lane": on_lane_combo,
            "on_label": on_label_edit,
            "action": action_combo,
            "target_lane": target_lane_combo,
            "target_label": target_label_edit,
            "copy_boundaries": copy_bounds_checkbox,
            "ghost": ghost_checkbox,
            "resolution": resolution_combo,
            "message": message_edit,
        }
        for column, key in enumerate(
            [
                "trigger",
                "on_lane",
                "on_label",
                "action",
                "target_lane",
                "target_label",
                "copy_boundaries",
                "ghost",
                "resolution",
                "message",
            ]
        ):
            self.rules_table.setCellWidget(row, column, widgets[key])

        action_combo.currentTextChanged.connect(lambda _text, widgets=widgets: self._configure_rule_widgets(widgets))
        self._configure_rule_widgets(widgets)

    def _duplicate_rule_row(self) -> None:
        row = self._selected_row(self.rules_table)
        if row is None:
            return
        data = self._rule_rows_data()
        data.insert(row + 1, dict(data[row]))
        self._replace_rule_rows(data)
        self.rules_table.selectRow(row + 1)

    def _remove_rule_row(self) -> None:
        rows = self._selected_rows(self.rules_table)
        if not rows or not self._confirm_removal("rule", len(rows)):
            return
        data = self._rule_rows_data()
        for row in reversed(rows):
            del data[row]
        self._replace_rule_rows(data)

    def _move_rule_row_up(self) -> None:
        self._move_row(self.rules_table, self._rule_rows_data, self._replace_rule_rows, -1)

    def _move_rule_row_down(self) -> None:
        self._move_row(self.rules_table, self._rule_rows_data, self._replace_rule_rows, 1)

    def _lane_rows_data(self) -> list[dict[str, object]]:
        data: list[dict[str, object]] = []
        for row in range(self.lanes_table.rowCount()):
            lane_type = self._combo_text(self.lanes_table, row, 4)
            allow_overlap = self._combo_bool(self.lanes_table, row, 5, default=True)
            data.append(
                {
                    "name": self._cell_text(self.lanes_table, row, 0),
                    "color": self._cell_text(self.lanes_table, row, 2) or COLOR_ACCENT_MUTED,
                    "labels": self._cell_text(self.lanes_table, row, 3),
                    "lane_type": lane_type or "interval",
                    "allow_overlap": allow_overlap,
                }
            )
        return data

    def _replace_lane_rows(self, rows: list[dict[str, object]]) -> None:
        self.lanes_table.setRowCount(0)
        for row in rows:
            self._add_lane_row(
                str(row.get("name", "")),
                "",
                str(row.get("color", COLOR_ACCENT_MUTED)),
                str(row.get("labels", "")),
                str(row.get("lane_type", "interval")),
                bool(row.get("allow_overlap", True)),
            )
        self._refresh_lane_levels()
        self._refresh_rule_lane_options()

    def _group_rows_data(self) -> list[dict[str, object]]:
        data: list[dict[str, object]] = []
        for row in range(self.groups_table.rowCount()):
            data.append(
                {
                    "name": self._cell_text(self.groups_table, row, 0),
                    "lanes": self._cell_text(self.groups_table, row, 1),
                    "collapsed": self._combo_bool(self.groups_table, row, 2, default=False),
                }
            )
        return data

    def _replace_group_rows(self, rows: list[dict[str, object]]) -> None:
        self.groups_table.setRowCount(0)
        for row in rows:
            self._add_group_row(
                str(row.get("name", "")),
                str(row.get("lanes", "")),
                bool(row.get("collapsed", False)),
            )

    def _rule_rows_data(self) -> list[dict[str, object]]:
        data: list[dict[str, object]] = []
        for row in range(self.rules_table.rowCount()):
            trigger = self._combo_text(self.rules_table, row, 0)
            on_lane = self._combo_text(self.rules_table, row, 1)
            on_label = self._line_edit_text(self.rules_table, row, 2)
            action = self._combo_text(self.rules_table, row, 3)
            target_lane = self._combo_text(self.rules_table, row, 4)
            target_label = self._line_edit_text(self.rules_table, row, 5)
            copy_boundaries = self._checkbox_checked(self.rules_table, row, 6)
            ghost = self._checkbox_checked(self.rules_table, row, 7)
            resolution = self._combo_text(self.rules_table, row, 8)
            message = self._line_edit_text(self.rules_table, row, 9)

            rule: dict[str, object] = {
                "trigger": trigger,
                "on_lane": on_lane,
                "action": action,
            }
            if on_label:
                rule["on_label"] = on_label
            if target_lane:
                rule["target_lane"] = target_lane
            if target_label:
                rule["target_label"] = target_label
            if copy_boundaries:
                rule["copy_boundaries"] = True
            if ghost:
                rule["ghost"] = True
            if resolution:
                rule["resolution"] = resolution
            if message:
                rule["message"] = message
            data.append(rule)
        return data

    def _replace_rule_rows(self, rows: list[dict[str, object]]) -> None:
        self.rules_table.setRowCount(0)
        for row in rows:
            self._add_rule_row(row)
        self._refresh_rule_lane_options()

    def _selected_row(self, table: QTableWidget) -> int | None:
        rows = self._selected_rows(table)
        return rows[0] if rows else None

    def _selected_rows(self, table: QTableWidget) -> list[int]:
        return sorted({index.row() for index in table.selectedIndexes()})

    def _move_row(self, table: QTableWidget, snapshot_fn, replace_fn, delta: int) -> None:
        row = self._selected_row(table)
        if row is None:
            return
        target = row + delta
        rows = snapshot_fn()
        if target < 0 or target >= len(rows):
            return
        rows[row], rows[target] = rows[target], rows[row]
        replace_fn(rows)
        table.selectRow(target)

    def _new_schema(self) -> None:
        schema = ProtocolSchema(
            version="1.0",
            name="New Schema",
            lanes=[],
            groups=[],
            rules=[],
        )
        self.load_schema(schema, None)

    def _open_schema(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Schema",
            str(self._current_path.parent if self._current_path is not None else Path.cwd()),
            "Schema Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.load_schema_path(path)
        except SchemaValidationError as exc:
            QMessageBox.warning(self, "Invalid Schema", str(exc))

    def _save_schema_as(self) -> tuple[Path, ProtocolSchema] | None:
        schema = self.current_schema()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Schema As",
            str(self._suggested_save_path()),
            "Schema Files (*.json);;All Files (*)",
        )
        if not path:
            return None
        self._current_path = Path(path)
        schema.save(self._current_path)
        self.raw_json_edit.setPlainText(json.dumps(schema.to_dict(), indent=2))
        self._update_path_label()
        self._set_status(f"Saved as {self._current_path.name}")
        return self._current_path, schema

    def _apply_raw_json(self) -> None:
        try:
            schema = ProtocolSchema.load(self._write_temp_raw_json())
        except SchemaValidationError as exc:
            QMessageBox.warning(self, "Invalid Schema JSON", str(exc))
            return
        finally:
            temp_path = getattr(self, "_temp_raw_json_path", None)
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
                self._temp_raw_json_path = None

        self.load_schema(schema, self._current_path)
        self._set_status("Raw JSON applied.")

    def _write_temp_raw_json(self) -> Path:
        with NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            handle.write(self.raw_json_edit.toPlainText())
            temp_path = Path(handle.name)
        self._temp_raw_json_path = temp_path
        return temp_path

    def _rebuild_raw_json(self) -> None:
        schema = self._schema_from_structured()
        self.raw_json_edit.setPlainText(json.dumps(schema.to_dict(), indent=2))
        self._set_status("Raw JSON rebuilt from structured view.")

    def current_schema(self) -> ProtocolSchema:
        if self.tabs.tabText(self.tabs.currentIndex()) == "Raw JSON":
            raw_text = self.raw_json_edit.toPlainText().strip()
            if raw_text:
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    raise SchemaValidationError(f"Invalid schema JSON: {exc}") from exc
                with NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
                    json.dump(payload, handle)
                    temp_path = Path(handle.name)
                try:
                    return ProtocolSchema.load(temp_path)
                finally:
                    temp_path.unlink(missing_ok=True)
        return self._schema_from_structured()

    def _schema_from_structured(self) -> ProtocolSchema:
        name = self.name_input.text().strip()
        version = self.version_input.text().strip() or "1.0"
        if not name:
            raise SchemaValidationError("Schema name cannot be empty.")

        lanes: list[LaneSchema] = []
        level_lookup: dict[str, int] = {}
        lane_rows = self._lane_rows_data()
        for idx, row in enumerate(lane_rows, start=1):
            lane_name = str(row.get("name", "")).strip()
            if not lane_name:
                continue
            labels = [part.strip() for part in str(row.get("labels", "")).split(",") if part.strip()]
            lane = LaneSchema(
                name=lane_name,
                level=idx,
                color=str(row.get("color", COLOR_ACCENT_MUTED)),
                labels=labels,
                allow_overlap=bool(row.get("allow_overlap", True)),
                lane_type=str(row.get("lane_type", "interval")),
            )
            lanes.append(lane)
            level_lookup[lane_name.casefold()] = idx

        groups: list[dict[str, object]] = []
        for row in self._group_rows_data():
            group_name = str(row.get("name", "")).strip()
            if not group_name:
                continue
            raw_lanes = str(row.get("lanes", ""))
            lane_items: list[int | str] = []
            for part in [item.strip() for item in raw_lanes.split(",") if item.strip()]:
                if part.isdigit():
                    lane_items.append(int(part))
                else:
                    lane_items.append(level_lookup.get(part.casefold(), part))
            groups.append(
                {
                    "name": group_name,
                    "lanes": lane_items,
                    "collapsed": bool(row.get("collapsed", False)),
                }
            )

        rules = self._rule_rows_data()

        schema = ProtocolSchema(
            version=version,
            name=name,
            lanes=lanes,
            groups=groups,
            rules=rules,
        )
        payload = schema.to_dict()
        with NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            temp_path = Path(handle.name)
        try:
            return ProtocolSchema.load(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _choose_schema(self) -> None:
        try:
            saved = self._save_schema_as()
            if saved is None:
                return
            path, schema = saved
        except SchemaValidationError as exc:
            QMessageBox.warning(self, "Invalid Schema", str(exc))
            return
        self.schema_chosen.emit(str(path), schema)
        self.accept()

    def _update_path_label(self) -> None:
        if self._current_path is None:
            self.path_label.setText("Path: (unsaved)")
        else:
            self.path_label.setText(f"Path: {self._current_path}")

    def _on_lanes_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_lanes:
            return
        if item.column() == 0:
            self._refresh_rule_lane_options()

    def _refresh_lane_levels(self) -> None:
        self._updating_lanes = True
        try:
            for row in range(self.lanes_table.rowCount()):
                level_item = self.lanes_table.item(row, 1)
                if level_item is None:
                    level_item = QTableWidgetItem("")
                    level_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    self.lanes_table.setItem(row, 1, level_item)
                level_item.setText(str(row + 1))
        finally:
            self._updating_lanes = False

    def _refresh_rule_lane_options(self) -> None:
        lane_names = self._lane_names_from_table()
        for row in range(self.rules_table.rowCount()):
            for column in (1, 4):
                combo = self.rules_table.cellWidget(row, column)
                if not isinstance(combo, QComboBox):
                    continue
                current = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("")
                combo.addItems(lane_names)
                combo.setCurrentText(current if current in lane_names else "")
                combo.blockSignals(False)

    def _configure_rule_widgets(self, widgets: dict[str, QWidget]) -> None:
        action = self._widget_combo_text(widgets["action"])
        trigger_combo = widgets["trigger"]
        if isinstance(trigger_combo, QComboBox):
            if action == "coincidence":
                trigger_combo.setCurrentText("validate")
            elif action in {"auto_create", "must_be_subset_of", "must_not_overlap"}:
                trigger_combo.setCurrentText("create")

        enabled_fields = {
            "target_lane": True,
            "target_label": action in {"auto_create", "must_not_overlap", "coincidence"},
            "copy_boundaries": action == "auto_create",
            "ghost": action in {"auto_create", "coincidence"},
            "resolution": action == "must_not_overlap",
            "message": action in {"must_be_subset_of", "must_not_overlap", "coincidence"},
        }
        for key, enabled in enabled_fields.items():
            widgets[key].setEnabled(enabled and not self._read_only)
            if not enabled:
                if isinstance(widgets[key], QComboBox):
                    widgets[key].setCurrentText("")
                elif isinstance(widgets[key], QLineEdit):
                    widgets[key].clear()
                elif isinstance(widgets[key], QCheckBox):
                    widgets[key].setChecked(False)

        tooltips = {
            "copy_boundaries": {
                True: "Only used by auto_create rules. Copies the source annotation boundaries into the created annotation.",
                False: "Disabled because this action does not create a copied annotation.",
            },
            "ghost": {
                True: "Used when the rule creates or suggests an annotation that should start as a ghost.",
                False: "Disabled because this action does not create or suggest a ghost annotation.",
            },
            "resolution": {
                True: "Only used by must_not_overlap rules. warn_and_clip can suggest a clipped fix.",
                False: "Disabled because overlap resolution only applies to must_not_overlap rules.",
            },
        }
        for key, mapping in tooltips.items():
            widgets[key].setToolTip(mapping[enabled_fields[key]])

    def _lane_names_from_table(self) -> list[str]:
        return [
            self._cell_text(self.lanes_table, row, 0)
            for row in range(self.lanes_table.rowCount())
            if self._cell_text(self.lanes_table, row, 0)
        ]

    def _confirm_removal(self, kind: str, count: int) -> bool:
        label = f"{count} {kind}" if count == 1 else f"{count} {kind}s"
        response = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Remove selected {label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _suggested_save_path(self) -> Path:
        suggested_name = self.name_input.text().strip() or "schema"
        suggested_version = self.version_input.text().strip()
        filename = suggested_name
        if suggested_version:
            filename = f"{filename}_v{suggested_version}"
        filename = filename.replace(" ", "_")
        base_dir = Path.cwd()
        if self._current_path is not None and self._current_path not in {
            DEFAULT_SCHEMA_PATH,
            NOTES_ONLY_SCHEMA_PATH,
        }:
            base_dir = self._current_path.parent
        return base_dir / f"{filename}.json"

    def _enum_combo(self, options: list[str], current: str) -> QComboBox:
        combo = QComboBox(self)
        combo.addItems(options)
        if current in options:
            combo.setCurrentText(current)
        elif current:
            combo.addItem(current)
            combo.setCurrentText(current)
        combo.setEnabled(not self._read_only)
        return combo

    def _lane_combo(self, current: str) -> QComboBox:
        combo = QComboBox(self)
        combo.addItem("")
        combo.addItems(self._lane_names_from_table())
        combo.setCurrentText(current if current in self._lane_names_from_table() else current)
        if current and combo.findText(current) == -1:
            combo.addItem(current)
            combo.setCurrentText(current)
        combo.setEnabled(not self._read_only)
        return combo

    def _bool_combo(self, value: bool) -> QComboBox:
        combo = QComboBox(self)
        for label, bool_value in _BOOL_OPTIONS:
            combo.addItem(label, bool_value)
        combo.setCurrentIndex(0 if value else 1)
        combo.setEnabled(not self._read_only)
        return combo

    def _checkbox(self, checked: bool) -> QCheckBox:
        checkbox = QCheckBox(self)
        checkbox.setChecked(checked)
        checkbox.setEnabled(not self._read_only)
        return checkbox

    def _line_edit(self, text: str) -> QLineEdit:
        edit = QLineEdit(text, self)
        edit.setReadOnly(self._read_only)
        return edit

    @staticmethod
    def _duplicate_name(name: str) -> str:
        stripped = name.strip()
        return f"{stripped} Copy" if stripped else "Copy"

    @staticmethod
    def _coerce_bool(value: bool | str, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        text = value.strip().casefold()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
        return default

    @staticmethod
    def _cell_text(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    @staticmethod
    def _combo_text(table: QTableWidget, row: int, column: int) -> str:
        widget = table.cellWidget(row, column)
        return widget.currentText().strip() if isinstance(widget, QComboBox) else ""

    @staticmethod
    def _widget_combo_text(widget: QWidget) -> str:
        return widget.currentText().strip() if isinstance(widget, QComboBox) else ""

    @staticmethod
    def _combo_bool(table: QTableWidget, row: int, column: int, *, default: bool) -> bool:
        widget = table.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            if isinstance(data, bool):
                return data
            text = widget.currentText().strip().casefold()
            if text in {"yes", "true"}:
                return True
            if text in {"no", "false"}:
                return False
        return default

    @staticmethod
    def _line_edit_text(table: QTableWidget, row: int, column: int) -> str:
        widget = table.cellWidget(row, column)
        return widget.text().strip() if isinstance(widget, QLineEdit) else ""

    @staticmethod
    def _checkbox_checked(table: QTableWidget, row: int, column: int) -> bool:
        widget = table.cellWidget(row, column)
        return widget.isChecked() if isinstance(widget, QCheckBox) else False
