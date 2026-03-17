from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation
from rime_core.rule_engine import Violation
from rime_core.schema import ProtocolSchema
from rime_ui.label_dialog import LabelDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_edit_label_dialog_shows_warning_and_fix_button() -> None:
    _app()
    schema = ProtocolSchema.default()
    core_level = schema.get_lane("Core").level  # type: ignore[union-attr]
    source = Annotation(id="c1", lane="Core", label="Core", start_ms=100.0, end_ms=400.0)
    fix = Annotation(id="c1", lane="Core", label="Core", start_ms=100.0, end_ms=250.0)
    violation = Violation(
        rule_action="must_not_overlap",
        message="Core must not overlap Festination/propulsion",
        source_annotation=source,
        can_auto_fix=True,
        fix_annotation=fix,
    )

    dialog = LabelDialog(
        core_level,
        schema=schema,
        current_label="Core",
        violations=[violation],
    )

    assert dialog.warning_list is not None
    assert dialog.warning_list.count() == 1
    assert dialog.warning_list.item(0).text() == "Core must not overlap Festination/propulsion"
    assert dialog.fix_button is not None
    assert dialog.fix_button.isEnabled() is True
    assert dialog.fix_button.text() == "Clip & Continue"

    dialog.close()
