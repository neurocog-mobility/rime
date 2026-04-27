from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_ui.dialogs.session_metadata_dialog import SessionMetadataDialog
from rime_core.sessions import VideoConfig
from rime_core.workspace import WorkingContext
from rime_ui.windows import main_window as main_window_module
from rime_ui.windows.main_window import RimeMainWindow


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
            "recording_relative_timing_verified": True,
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
    assert context.session.provenance.recording_relative_timing_verified is True
    assert window.windowTitle() == "RIME - Updated Name"
    assert window.annotations._session_name == "Updated Name"
    assert saved == ["saved"]

    window.close()


def test_session_metadata_dialog_exposes_timing_verification_checkbox(tmp_path) -> None:
    _app()
    context = WorkingContext.create(
        session_dir=tmp_path / "metadata-session",
        name="Original Name",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    context.session.provenance.recording_relative_timing_verified = True

    dialog = SessionMetadataDialog(context.session)

    assert dialog.timing_verified_checkbox.isChecked() is True
    assert "recording start" in dialog.timing_verified_checkbox.toolTip()
    assert "BIDS export" in dialog.timing_help_label.text()
    values = dialog.values()
    assert values["recording_relative_timing_verified"] is True

    dialog.timing_verified_checkbox.setChecked(False)
    values = dialog.values()
    assert values["recording_relative_timing_verified"] is False

    dialog.close()
