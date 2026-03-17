from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.annotations import AnnotationStore
from rime_core.context import WorkingContext
from rime_core.session import VideoConfig
from rime_ui.main_window import LayoutMode, RimeMainWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_layout_modes_toggle_panel_visibility() -> None:
    app = _app()
    window = RimeMainWindow()
    window.show()
    app.processEvents()

    window._comparison_store = AnnotationStore()
    window._apply_layout(LayoutMode.COMPARISON)
    app.processEvents()

    assert window._layout_mode is LayoutMode.COMPARISON
    assert window.timeline.is_signal_panel_visible() is False
    assert window.annotation_list_dock.isHidden() is True
    assert window.model_runner_dock.isHidden() is True
    assert window.model_eval_dock.isHidden() is True
    assert window.clinical_dock.isHidden() is True
    assert window.irr_dock.isHidden() is False
    assert window.irr_action.isEnabled() is True
    assert window.irr_action.isChecked() is True
    assert window.annotation_list_action.isEnabled() is False
    assert window.model_runner_action.isEnabled() is False
    assert window.model_eval_action.isEnabled() is False
    assert window.single_signal_action.isEnabled() is False
    assert window.combined_signals_action.isEnabled() is False
    assert window.select_display_signals_action.isEnabled() is False
    assert window.compare_session_action.isEnabled() is False
    assert window.show_comparison_action.isEnabled() is True
    assert window.close_comparison_action.isEnabled() is True

    window._comparison_store = None
    window._apply_layout(LayoutMode.ANNOTATION)
    app.processEvents()

    assert window._layout_mode is LayoutMode.ANNOTATION
    assert window.timeline.is_signal_panel_visible() is True
    assert window.annotation_list_dock.isHidden() is False
    assert window.model_runner_dock.isHidden() is False
    assert window.model_eval_dock.isHidden() is False
    assert window.clinical_dock.isHidden() is False
    assert window.irr_dock.isHidden() is True
    assert window.irr_action.isEnabled() is False
    assert window.irr_action.isChecked() is False
    assert window.annotation_list_action.isEnabled() is True
    assert window.model_runner_action.isEnabled() is True
    assert window.model_eval_action.isEnabled() is True
    assert window.single_signal_action.isEnabled() is True
    assert window.combined_signals_action.isEnabled() is True
    assert window.select_display_signals_action.isEnabled() is True
    assert window.compare_session_action.isEnabled() is True
    assert window.show_comparison_action.isEnabled() is False
    assert window.close_comparison_action.isEnabled() is False

    window.close()


def test_irr_dock_can_be_reopened_in_comparison_mode() -> None:
    app = _app()
    window = RimeMainWindow()
    window.show()
    app.processEvents()

    window._comparison_store = AnnotationStore()
    window._apply_layout(LayoutMode.COMPARISON)
    app.processEvents()

    window.irr_dock.hide()
    app.processEvents()
    assert window.irr_action.isChecked() is False

    window.irr_action.trigger()
    app.processEvents()

    assert window.irr_dock.isHidden() is False
    assert window.irr_action.isChecked() is True

    window.close()


def test_default_export_dir_uses_session_subfolder_when_root_is_configured() -> None:
    _app()
    window = RimeMainWindow()
    window._app_settings.default_export_dir = "/tmp/rime-exports"
    window.session = SimpleNamespace(name="Test Session 01", session_dir=Path("/tmp/session"))

    assert window._default_export_dir() == Path("/tmp/rime-exports/Test_Session_01")

    window._app_settings.default_export_dir = ""
    assert window._default_export_dir() == Path("/tmp/session/exports")

    window.close()


def test_loading_context_enables_annotate_menu_actions(tmp_path: Path) -> None:
    _app()
    window = RimeMainWindow()
    context = WorkingContext.create(
        session_dir=tmp_path / "annotate-enabled-session",
        name="Annotate Enabled",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )

    window._load_context(context)

    assert window.clear_snaps_action.isEnabled() is True
    assert window.clear_loop_action.isEnabled() is True
    assert window.clear_all_ghosts_action.isEnabled() is True
    assert window.clear_all_annotations_action.isEnabled() is True
    assert window.set_snap_tolerance_action.isEnabled() is True

    window.close()


def test_menu_order_and_labels_match_review_pass() -> None:
    _app()
    window = RimeMainWindow()

    top_level = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert top_level == ["Session", "Annotate", "View", "Review", "Models", "Help"]

    assert window.clear_all_ghosts_action.text() == "Delete All Ghosts"
    assert window.clear_all_annotations_action.text() == "Delete All Annotations"
    assert window.combined_signals_action.text() == "Combined Signals"
    assert window.model_runner_action.text() == "Model Runner"
    assert window.clinical_action.text() == "Clinical Outcomes"
    assert window.irr_action.text() == "IRR Panel"
    assert window.model_runner_dock.windowTitle() == "Model Runner"
    assert window.irr_dock.windowTitle() == "IRR Panel"

    window.close()


def test_clinical_dock_toggle_persists_to_session_and_restores_after_reload(tmp_path: Path) -> None:
    app = _app()
    window = RimeMainWindow()
    context = WorkingContext.create(
        session_dir=tmp_path / "panel-visibility-session",
        name="Panel Visibility",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )

    window._load_context(context)
    app.processEvents()

    assert window.clinical_dock.isHidden() is False
    assert window.clinical_action.isChecked() is True

    window.clinical_dock.hide()
    app.processEvents()

    assert context.session.panel_visibility["clinical_outcomes"] is False
    assert window.clinical_action.isChecked() is False

    reopened = WorkingContext.open(context.session.session_dir)
    reloaded_window = RimeMainWindow()
    reloaded_window._load_context(reopened)
    app.processEvents()

    assert reloaded_window.clinical_dock.isHidden() is True
    assert reloaded_window.clinical_action.isChecked() is False

    window.close()
    reloaded_window.close()


def test_annotation_panel_preferences_survive_comparison_mode_switch(tmp_path: Path) -> None:
    app = _app()
    window = RimeMainWindow()
    context = WorkingContext.create(
        session_dir=tmp_path / "panel-layout-switch-session",
        name="Panel Layout Switch",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    context.session.panel_visibility["clinical_outcomes"] = False
    context.save()

    window._load_context(context)
    app.processEvents()

    assert window.clinical_dock.isHidden() is True

    window._comparison_store = AnnotationStore()
    window._apply_layout(LayoutMode.COMPARISON)
    app.processEvents()
    window._comparison_store = None
    window._apply_layout(LayoutMode.ANNOTATION)
    app.processEvents()

    assert window.clinical_dock.isHidden() is True
    assert context.session.panel_visibility["clinical_outcomes"] is False

    window.close()


def test_closing_window_does_not_persist_all_panels_as_hidden(tmp_path: Path) -> None:
    app = _app()
    window = RimeMainWindow()
    context = WorkingContext.create(
        session_dir=tmp_path / "panel-close-session",
        name="Panel Close",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )

    window._load_context(context)
    app.processEvents()

    window.annotation_list_dock.hide()
    app.processEvents()
    window.clinical_dock.show()
    window.model_runner_dock.show()
    window.model_eval_dock.show()
    app.processEvents()

    saved_before_close = dict(context.session.panel_visibility)
    assert saved_before_close["annotation_list"] is False
    assert saved_before_close["clinical_outcomes"] is True
    assert saved_before_close["model_runner"] is True
    assert saved_before_close["model_evaluation"] is True

    window.close()
    app.processEvents()

    reopened = WorkingContext.open(context.session.session_dir)

    assert reopened.session.panel_visibility == saved_before_close
