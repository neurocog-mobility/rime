from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PySide6.QtWidgets import QApplication

from rime_core import Annotation, Signal, SignalConfig, WorkingContext
from rime_ui.dialogs import export_dialog as export_dialog_module
from rime_ui.dialogs.export_dialog import ExportDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_dialog(tmp_path: Path) -> ExportDialog:
    _app()
    context = WorkingContext.create(
        session_dir=tmp_path / "session",
        name="Export Session",
        signals=[
            SignalConfig(
                path="imu.csv",
                name="Left Ankle",
                type="imu",
                format="csv",
                sampling_rate_hz=2.0,
                time_column="time",
                channels=["acc_x"],
            )
        ],
    )
    context.store.add(
        Annotation(id="fog-1", lane="FOG", label="FOG", start_ms=1000.0, end_ms=2000.0)
    )
    signal = Signal(
        name="imu",
        data=pd.DataFrame({"time": [0.0, 0.5], "acc_x": [1.0, 2.0]}),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x"],
    )
    return ExportDialog(context, [signal], default_output_dir=tmp_path / "exports")


def test_bids_mode_disables_export_until_timing_is_verified(tmp_path: Path) -> None:
    dialog = _make_dialog(tmp_path)

    dialog.export_mode_combo.setCurrentIndex(1)

    assert dialog._is_bids_mode() is True
    assert dialog._export_button.isEnabled() is False
    assert dialog.video_checkbox.isEnabled() is False
    assert "recording-relative annotation timing" in dialog.video_status_label.text()

    dialog.close()


def test_bids_mode_calls_bids_exporter(tmp_path: Path, monkeypatch) -> None:
    dialog = _make_dialog(tmp_path)
    dialog._context.session.provenance.recording_relative_timing_verified = True
    dialog.export_mode_combo.setCurrentIndex(1)

    captured: dict[str, object] = {}

    def fake_export_bids_dataset(store, session, signals, output_root, **kwargs) -> int:
        captured["store_ids"] = [annotation.id for annotation in store.all()]
        captured["session_id"] = session.id
        captured["signal_names"] = [signal.name for signal in signals]
        captured["output_root"] = output_root
        captured["kwargs"] = kwargs
        return 7

    monkeypatch.setattr(export_dialog_module, "export_bids_dataset", fake_export_bids_dataset)

    dialog._on_export()

    assert captured["store_ids"] == ["fog-1"]
    assert captured["signal_names"] == ["imu"]
    assert captured["output_root"] == Path(tmp_path / "exports")
    assert captured["kwargs"]["export_motion"] is True
    assert captured["kwargs"]["export_clips"] is True
    assert dialog.exported_files == 7

    dialog.close()
