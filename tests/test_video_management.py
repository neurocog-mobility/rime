from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.sessions import SessionProvenance, VideoConfig, create_session
from rime_ui.windows import main_window as main_window_module
from rime_ui.windows.main_window import RimeMainWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_apply_selected_video_paths_fills_empty_secondary_slot_and_warns_on_extra(
    tmp_path, monkeypatch
) -> None:
    _app()
    session = create_session(
        session_dir=tmp_path / "video-session",
        name="Video Session",
        videos=[VideoConfig(path="primary.mp4", role="primary")],
        provenance=SessionProvenance(origin="manual"),
    )
    window = RimeMainWindow()
    window.session = session

    notices: list[str] = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "information",
        lambda _parent, _title, text: notices.append(text),
    )

    changed, _message = window._apply_selected_video_paths(["secondary.mp4", "extra.mp4"])

    assert changed is True
    assert [video.path for video in session.videos] == ["primary.mp4", "secondary.mp4"]
    assert [video.role for video in session.videos] == ["primary", "secondary"]
    assert len(notices) == 1

    window.close()


def test_apply_selected_video_paths_can_replace_secondary_slot(tmp_path, monkeypatch) -> None:
    _app()
    session = create_session(
        session_dir=tmp_path / "replace-session",
        name="Replace Session",
        videos=[
            VideoConfig(path="primary.mp4", role="primary"),
            VideoConfig(path="secondary.mp4", role="secondary"),
        ],
        provenance=SessionProvenance(origin="manual"),
    )
    window = RimeMainWindow()
    window.session = session
    monkeypatch.setattr(window, "_prompt_video_slot_replacement", lambda: 1)

    changed, _message = window._apply_selected_video_paths(["replacement.mp4"])

    assert changed is True
    assert [video.path for video in session.videos] == ["primary.mp4", "replacement.mp4"]
    assert [video.role for video in session.videos] == ["primary", "secondary"]
    assert session.primary_video == "primary.mp4"

    window.close()
