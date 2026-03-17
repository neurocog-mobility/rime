from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.schema import DEFAULT_SCHEMA_PATH, NOTES_ONLY_SCHEMA_PATH, ProtocolSchema
from rime_core.session import SignalConfig
from rime_ui.main_window import RimeMainWindow
from rime_ui.schema_browser import SchemaBrowserWindow
from rime_ui.session_wizard import SessionWizard


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_schema_browser_builds_schema_from_structured_fields() -> None:
    _app()
    window = SchemaBrowserWindow(schema=ProtocolSchema.default())

    window.name_input.setText("Custom Schema")
    window.version_input.setText("1.2")
    window.lanes_table.setRowCount(0)
    window._add_lane_row("Events", "1", "#123456", "Start, Stop", "interval", "false")
    window.groups_table.setRowCount(0)
    window._add_group_row("Primary", "Events", "true")
    window.rules_table.setRowCount(0)
    window._add_rule_row('{"trigger":"create","on_lane":"Events","action":"noop"}')

    schema = window._schema_from_structured()

    assert schema.name == "Custom Schema"
    assert schema.version == "1.2"
    assert schema.lanes[0].name == "Events"
    assert schema.lanes[0].allow_overlap is False
    assert schema.groups[0]["lanes"] == [1]
    assert schema.rules[0]["action"] == "noop"

    window.close()


def test_schema_browser_autonumbers_and_duplicates_lanes() -> None:
    _app()
    window = SchemaBrowserWindow(schema=ProtocolSchema.default())
    window.lanes_table.setRowCount(0)

    window._add_lane_row("Tasks", "7", "#123456", "Walk", "interval", True)
    window._add_lane_row("Steps", "42", "#ffaa00", "step", "point", False)

    assert window.lanes_table.item(0, 1).text() == "1"
    assert window.lanes_table.item(1, 1).text() == "2"

    window.lanes_table.selectRow(0)
    window._duplicate_lane_row()

    assert window.lanes_table.rowCount() == 3
    assert window.lanes_table.item(1, 0).text() == "Tasks Copy"
    assert window.lanes_table.item(2, 1).text() == "3"

    window.close()


def test_schema_browser_applies_raw_json_to_structured_view(tmp_path: Path) -> None:
    _app()
    window = SchemaBrowserWindow(schema=ProtocolSchema.default())
    payload = {
        "version": "2.0",
        "name": "Raw Schema",
        "lanes": [
            {
                "name": "Steps",
                "level": 1,
                "color": "#ffaa00",
                "labels": ["step"],
                "lane_type": "point",
            }
        ],
        "groups": [{"name": "Motion", "lanes": [1], "collapsed": False}],
        "rules": [{"trigger": "create", "on_lane": "Steps", "action": "noop"}],
    }
    window.raw_json_edit.setPlainText(json.dumps(payload, indent=2))

    window._apply_raw_json()

    assert window.name_input.text() == "Raw Schema"
    assert window.version_input.text() == "2.0"
    assert window.lanes_table.rowCount() == 1
    assert window.lanes_table.item(0, 0).text() == "Steps"
    assert window.rules_table.rowCount() == 1
    assert window.current_schema().rules[0]["action"] == "noop"

    window.close()


def test_schema_browser_builds_guided_rule_rows() -> None:
    _app()
    window = SchemaBrowserWindow(schema=ProtocolSchema.default())
    window.rules_table.setRowCount(0)

    window._add_rule_row()
    trigger = window.rules_table.cellWidget(0, 0)
    on_lane = window.rules_table.cellWidget(0, 1)
    action = window.rules_table.cellWidget(0, 3)
    target_lane = window.rules_table.cellWidget(0, 4)
    ghost = window.rules_table.cellWidget(0, 7)

    assert trigger is not None
    assert on_lane is not None
    assert action is not None
    assert target_lane is not None
    assert ghost is not None

    trigger.setCurrentText("validate")
    on_lane.setCurrentText("Manifestations")
    action.setCurrentText("coincidence")
    target_lane.setCurrentText("Core")
    window.rules_table.cellWidget(0, 5).setText("Core")
    window.rules_table.cellWidget(0, 7).setChecked(True)
    window.rules_table.cellWidget(0, 9).setText("Must coincide")

    schema = window._schema_from_structured()

    assert schema.rules == [
        {
            "trigger": "validate",
            "on_lane": "Manifestations",
            "action": "coincidence",
            "target_lane": "Core",
            "target_label": "Core",
            "ghost": True,
            "message": "Must coincide",
        }
    ]

    window.close()


def test_main_window_opens_schema_browser() -> None:
    app = _app()
    window = RimeMainWindow()
    window.show()
    app.processEvents()

    observed: dict[str, object] = {}
    original_exec = SchemaBrowserWindow.exec

    def _fake_exec(self: SchemaBrowserWindow) -> int:
        observed["title"] = self.windowTitle()
        observed["read_only"] = self.name_input.isReadOnly()
        observed["schema_name"] = self.name_input.text()
        return 0

    SchemaBrowserWindow.exec = _fake_exec
    try:
        window._on_view_schema()
        app.processEvents()
    finally:
        SchemaBrowserWindow.exec = original_exec

    assert window.schema_builder_action.text() == "View Schema..."
    assert observed["title"] == "Schema Viewer"
    assert observed["read_only"] is True
    assert observed["schema_name"] == "FOG-COA"

    window.close()


def test_schema_browser_chooser_mode_emits_selected_schema(tmp_path: Path) -> None:
    _app()
    window = SchemaBrowserWindow(schema=ProtocolSchema.default(), chooser_mode=True)
    output_path = tmp_path / "custom_schema.json"

    chosen: list[tuple[str, str]] = []
    window.schema_chosen.connect(lambda path, schema: chosen.append((path, schema.name)))
    from rime_ui import schema_browser as schema_browser_module

    original_dialog = schema_browser_module.QFileDialog.getSaveFileName
    schema_browser_module.QFileDialog.getSaveFileName = staticmethod(
        lambda *args, **kwargs: (str(output_path), "Schema Files (*.json)")
    )
    try:
        window.choose_button.click()
    finally:
        schema_browser_module.QFileDialog.getSaveFileName = original_dialog

    assert chosen == [(str(output_path), "FOG-COA")]
    assert output_path.exists()
    window.close()


def test_session_wizard_uses_builtin_schema_selection() -> None:
    _app()
    wizard = SessionWizard()

    assert wizard._selected_schema_path == DEFAULT_SCHEMA_PATH
    assert wizard._selected_schema is not None
    assert wizard._selected_schema.name == "FOG-COA"

    notes_index = next(
        idx for idx in range(wizard.schema_combo.count()) if wizard.schema_combo.itemData(idx)[0] == "notes_only"
    )
    wizard.schema_combo.setCurrentIndex(notes_index)

    assert wizard._selected_schema_path == NOTES_ONLY_SCHEMA_PATH
    assert wizard._selected_schema is not None
    assert wizard._selected_schema.name == "Notes Only"

    wizard.close()


def test_session_wizard_includes_selected_signals_in_created_session(tmp_path: Path) -> None:
    _app()
    wizard = SessionWizard()
    wizard.dir_input.setText(str(tmp_path / "session"))
    wizard.name_input.setText("With Signals")
    wizard._add_signal_item(
        SignalConfig(
            path="signals/imu.csv",
            name="imu",
            type="imu",
            format="csv",
            sampling_rate_hz=100.0,
            time_column="time",
            display_channels=["ax", "ay"],
        )
    )

    session, _store = wizard.to_result()

    assert len(session.signals) == 1
    assert session.signals[0].path == "signals/imu.csv"
    assert session.signals[0].name == "imu"
    assert session.signals[0].display_channels == ["ax", "ay"]

    wizard.close()


def test_session_wizard_caps_created_session_videos_to_two_slots(tmp_path: Path) -> None:
    _app()
    wizard = SessionWizard()
    wizard.dir_input.setText(str(tmp_path / "session"))
    wizard.name_input.setText("With Videos")
    wizard.video_list.addItem("primary.mp4")
    wizard.video_list.addItem("secondary.mp4")
    wizard.video_list.addItem("ignored.mp4")

    session, _store = wizard.to_result()

    assert [video.path for video in session.videos] == ["primary.mp4", "secondary.mp4"]
    assert [video.role for video in session.videos] == ["primary", "secondary"]

    wizard.close()
