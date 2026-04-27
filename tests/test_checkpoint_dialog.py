from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from rime_core.checkpoints import CheckpointEntry
from rime_ui.dialogs.checkpoint_dialog import RestoreCheckpointDialog


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_restore_dialog_open_folder_opens_checkpoint_dir(monkeypatch, tmp_path: Path) -> None:
    _app()
    checkpoint_dir = tmp_path / "checkpoints"
    dialog = RestoreCheckpointDialog(
        [
            CheckpointEntry(
                id="chk-1",
                label="Manual checkpoint",
                kind="manual",
                created="2026-03-14T12:00:00+00:00",
                snapshot_file="chk-1.json",
            )
        ],
        checkpoint_dir,
    )

    launched: list[list[str]] = []

    def fake_popen(cmd: list[str]) -> object:
        launched.append(cmd)
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    dialog.open_folder_button.click()

    if sys.platform == "darwin":
        expected = ["open", str(checkpoint_dir)]
    elif os.name == "nt":
        expected = ["explorer", str(checkpoint_dir)]
    else:
        expected = ["xdg-open", str(checkpoint_dir)]

    assert launched == [expected]
