from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from rime_core import MAX_SESSION_VIDEOS, ProtocolSchema
from rime_core.elan_import import TierMapping
from rime_ui.dialogs import import_dialog as import_dialog_module
from rime_ui.dialogs.import_dialog import ImportDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_import_dialog_caps_video_list_to_two_slots(monkeypatch) -> None:
    _app()
    dialog = ImportDialog(ProtocolSchema.default())

    notices: list[str] = []
    monkeypatch.setattr(
        import_dialog_module.QMessageBox,
        "information",
        lambda _parent, _title, text: notices.append(text),
    )

    dialog._add_unique(
        dialog.video_list,
        ["one.mp4", "two.mp4", "three.mp4"],
        limit=MAX_SESSION_VIDEOS,
    )

    assert [dialog.video_list.item(i).text() for i in range(dialog.video_list.count())] == [
        "one.mp4",
        "two.mp4",
    ]
    assert len(notices) == 1

    dialog.close()


def test_import_dialog_marks_skipped_tiers_with_muted_amber() -> None:
    _app()
    dialog = ImportDialog(ProtocolSchema.default())
    dialog.mappings = [
        TierMapping(elan_tier="Walk", rime_lane="Tasks", annotation_count=3),
        TierMapping(elan_tier="Unknown", rime_lane=None, annotation_count=1),
    ]

    dialog._populate_tier_table()

    assigned_color = dialog.table.item(0, 0).background().color()
    skipped_color = dialog.table.item(1, 0).background().color()

    assert assigned_color != QColor("#3d2800")
    assert skipped_color == QColor("#3d2800")

    dialog.close()
