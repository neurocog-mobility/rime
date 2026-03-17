from __future__ import annotations

import os

import pandas as pd
from PySide6.QtWidgets import QApplication

from rime_core.context import WorkingContext
from rime_core.session import SignalConfig, VideoConfig
from rime_core.signals import Signal
from rime_ui.main_window import RimeMainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_signal_display_selection_updates_session_and_saves(tmp_path, monkeypatch) -> None:
    _app()
    context = WorkingContext.create(
        session_dir=tmp_path / "signal-display-session",
        name="Signal Display",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        signals=[
            SignalConfig(
                path="signals/imu.csv",
                name="imu",
                type="imu",
                format="csv",
                sampling_rate_hz=100.0,
                time_column="time",
                display_channels=["ax"],
            )
        ],
    )
    context.signals = {
        "imu": Signal(
            name="imu",
            data=pd.DataFrame({"time": [0.0, 1.0], "ax": [0.0, 1.0], "ay": [1.0, 2.0]}),
            sampling_rate_hz=1.0,
            time_column="time",
            channels=["ax", "ay"],
        )
    }

    saved: list[str] = []
    monkeypatch.setattr(context, "save", lambda: saved.append("saved"))

    window = RimeMainWindow()
    window._load_context(context)
    window._on_signal_display_selection_changed({"imu": ["ay"]})

    assert context.session.signals[0].display_channels == ["ay"]
    assert saved == ["saved"]

    window.close()
