from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_ui.dialogs.signal_config_dialog import SignalConfigDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_signal_config_dialog_defaults_offset_to_zero() -> None:
    _app()
    dialog = SignalConfigDialog(
        signal_path=Path("imu.csv"),
        stored_path="imu.csv",
        detected={
            "columns": ["time", "acc_x"],
            "channels": ["acc_x"],
            "time_column": "time",
            "sampling_rate_hz": 100.0,
        },
    )

    config = dialog.to_signal_config()

    assert config.offset_ms == 0.0
