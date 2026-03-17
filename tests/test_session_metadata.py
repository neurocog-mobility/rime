from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.context import WorkingContext
from rime_core.session import VideoConfig
from rime_ui import main_window as main_window_module
from rime_ui.main_window import RimeMainWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_edit_metadata_updates_session_and_window_title(tmp_path, monkeypatch) -> None:
    _app()
    context = WorkingContext.create(
        session_dir=tmp_path / "metadata-session",
        name="Original Name",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )

    saved: list[str] = []
    monkeypatch.setattr(context, "save", lambda: saved.append("saved"))
    monkeypatch.setattr(
        main_window_module.SessionMetadataDialog,
        "edit_session",
        lambda _session, _parent=None: {
            "name": "Updated Name",
            "rater": "AZ",
            "subject_id": "S001",
            "condition": "PD",
            "medication_state": "on",
            "session_start_utc": "2024-03-01T09:31:22Z",
        },
    )

    window = RimeMainWindow()
    window._load_context(context)
    window._on_edit_metadata()

    assert context.session.name == "Updated Name"
    assert context.session.rater == "AZ"
    assert context.session.subject is not None
    assert context.session.subject.id == "S001"
    assert context.session.subject.condition == "PD"
    assert context.session.subject.medication_state == "on"
    assert context.session.session_start_utc == "2024-03-01T09:31:22Z"
    assert window.windowTitle() == "RIME - Updated Name"
    assert window.annotations._session_name == "Updated Name"
    assert saved == ["saved"]

    window.close()
