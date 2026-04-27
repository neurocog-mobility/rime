from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.settings import AppSettings
from rime_ui.windows.main_window import RimeMainWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_applies_custom_shortcuts() -> None:
    app = _app()
    window = RimeMainWindow()
    window._app_settings = AppSettings(
        shortcut_overrides={
            "show_shortcuts": "Ctrl+/",
            "edit_annotation": "F2",
            "delete_selection": "",
            "toggle_model_runner": "Ctrl+6",
        }
    )

    window._apply_app_settings()
    app.processEvents()

    assert window.shortcuts_action.shortcut().toString() == "Ctrl+/"
    assert window.annotation_toolbar.edit_action.shortcut().toString() == "F2"
    assert window.annotation_toolbar.delete_action.shortcut().toString() == ""
    assert window.model_runner_action.shortcut().toString() == "Ctrl+6"

    window.close()


def test_main_window_global_navigation_advances_playhead_even_with_timeline_selection() -> None:
    app = _app()
    window = RimeMainWindow()

    class FakePlayer:
        def __init__(self) -> None:
            self.position_ms = 1_000

        def get_duration_ms(self) -> int:
            return 10_000

        def get_position_ms(self) -> int:
            return self.position_ms

        def set_position_ms(self, ms: int) -> None:
            self.position_ms = ms

    fake_player = FakePlayer()
    window.video_player = fake_player

    store = AnnotationStore()
    store.add(
        Annotation(
            id="a1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=300.0,
        )
    )
    window.timeline.set_store(store)
    window.timeline.select_annotation("a1")

    handled = window._handle_global_navigation(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    )
    handled_fast = window._handle_global_navigation(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    )

    app.processEvents()

    assert handled is True
    assert handled_fast is True
    assert fake_player.position_ms == 703

    window.close()


def test_accepting_auto_created_ghost_does_not_seek_to_another_ghost(monkeypatch) -> None:
    _app()
    window = RimeMainWindow()

    store = AnnotationStore()
    store.add(
        Annotation(
            id="auto1",
            lane="Core",
            label="Core",
            start_ms=1_000.0,
            end_ms=2_000.0,
            ghost=True,
            source="rule:auto_create",
        )
    )
    store.add(
        Annotation(
            id="auto2",
            lane="Core",
            label="Core",
            start_ms=8_000.0,
            end_ms=9_000.0,
            ghost=True,
            source="rule:auto_create",
        )
    )
    window.annotations = store
    window.timeline.set_store(store)
    window.timeline.set_duration(10_000.0)
    window.timeline.set_view_range(0.0, 2_500.0)
    window.timeline.select_annotation("auto1")

    def accept_ghost(ann_id: str) -> tuple[Annotation, list[object]]:
        annotation = store.get(ann_id)
        assert annotation is not None
        annotation.ghost = False
        return annotation, []

    window.context = SimpleNamespace(accept_ghost=accept_ghost)
    monkeypatch.setattr(window, "_refresh_annotation_views", lambda: None)
    monkeypatch.setattr(window, "_show_violation_dialog", lambda violation: None)

    seek_calls: list[float] = []
    monkeypatch.setattr(window.timeline, "seek_to", lambda time_ms: seek_calls.append(time_ms))

    before_range = window.timeline.get_view_range()
    window._on_accept_ghost()

    assert seek_calls == []
    assert window.timeline.get_selected_id() == "auto1"
    assert window.timeline.get_view_range() == before_range

    window.close()


def test_accepting_model_ghost_advances_review_with_seek(monkeypatch) -> None:
    _app()
    window = RimeMainWindow()

    store = AnnotationStore()
    store.add(
        Annotation(
            id="model1",
            lane="Core",
            label="Core",
            start_ms=1_000.0,
            end_ms=2_000.0,
            ghost=True,
            source="model:demo",
        )
    )
    store.add(
        Annotation(
            id="model2",
            lane="Core",
            label="Core",
            start_ms=8_000.0,
            end_ms=9_000.0,
            ghost=True,
            source="model:demo",
        )
    )
    window.annotations = store
    window.timeline.set_store(store)
    window.timeline.select_annotation("model1")

    def accept_ghost(ann_id: str) -> tuple[Annotation, list[object]]:
        annotation = store.get(ann_id)
        assert annotation is not None
        annotation.ghost = False
        return annotation, []

    window.context = SimpleNamespace(accept_ghost=accept_ghost)
    monkeypatch.setattr(window, "_refresh_annotation_views", lambda: None)
    monkeypatch.setattr(window, "_show_violation_dialog", lambda violation: None)

    seek_calls: list[float] = []
    monkeypatch.setattr(window.timeline, "seek_to", lambda time_ms: seek_calls.append(time_ms))

    window._on_accept_ghost()

    assert seek_calls == [8_000.0]
    assert window.timeline.get_selected_id() == "model2"

    window.close()
