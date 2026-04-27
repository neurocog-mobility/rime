from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.sessions import Session, VideoConfig, create_session
from rime_ui.panels.irr_panel import IRRPanel


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _session(tmp_path: Path, name: str, rater: str) -> Session:
    return create_session(
        session_dir=tmp_path / name,
        name=name,
        videos=[VideoConfig(path="video.mp4", role="primary")],
        rater=rater,
    )


def _store(*annotations: Annotation) -> AnnotationStore:
    store = AnnotationStore()
    for annotation in annotations:
        store.add(annotation)
    return store


def test_irr_panel_computes_summary(tmp_path: Path) -> None:
    _app()
    panel = IRRPanel()
    session_a = _session(tmp_path, "session_a", "AZ")
    session_b = _session(tmp_path, "session_b", "MK")
    store_a = _store(
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"),
        Annotation(id="a2", lane="FOG", label="FOG", start_ms=600.0, end_ms=800.0, source="manual"),
    )
    store_b = _store(
        Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0, source="manual"),
    )

    panel.refresh(session_a, store_a, session_b, store_b, 1000.0)
    assert panel.current_source_a() == "manual"
    assert panel.current_source_b() == "manual"
    panel._compute()

    assert panel.placeholder.isHidden()
    assert panel.summary_table.item(3, 1).text() == "1"
    assert panel.summary_table.item(4, 1).text() == "0"
    assert panel.export_matched_button.isEnabled()
    assert panel.export_button.isEnabled()
    assert panel.status_label.text() == "IRR computed."
    assert panel.close_button.isEnabled()


def test_irr_panel_emits_close_requested(tmp_path: Path) -> None:
    _app()
    panel = IRRPanel()
    session_a = _session(tmp_path, "session_a", "AZ")
    session_b = _session(tmp_path, "session_b", "MK")

    panel.refresh(session_a, _store(), session_b, _store(), 1000.0)

    closed: list[bool] = []
    panel.close_requested.connect(lambda: closed.append(True))
    panel.close_button.click()

    assert closed == [True]


def test_irr_panel_rebuilds_matched_episode_store_when_mode_changes(tmp_path: Path) -> None:
    _app()
    panel = IRRPanel()
    session_a = _session(tmp_path, "session_a", "AZ")
    session_b = _session(tmp_path, "session_b", "MK")
    store_a = _store(
        Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0, source="manual"),
    )
    store_b = _store(
        Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0, source="manual"),
    )

    payloads: list[object] = []
    panel.matched_episode_store_changed.connect(payloads.append)
    panel.refresh(session_a, store_a, session_b, store_b, 1000.0)
    panel._compute()

    store, label = payloads[-1]
    assert label == "M (avg)"
    annotation = store.all()[0]
    assert annotation.start_ms == 110.0
    assert annotation.end_ms == 290.0

    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("union"))

    store, label = payloads[-1]
    assert label == "M (∪)"
    annotation = store.all()[0]
    assert annotation.start_ms == 100.0
    assert annotation.end_ms == 300.0
