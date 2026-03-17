"""Main window for RIME application."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum, auto
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QByteArray, QEvent, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rime_core import (
    Annotation,
    AnnotationStore,
    CMFPackage,
    CMFValidationError,
    DEFAULT_PANEL_VISIBILITY,
    InferenceResult,
    InputBinding,
    MAX_SESSION_VIDEOS,
    ModelSettings,
    OutputMapping,
    SignalConfig,
    Session,
    SubjectInfo,
    VideoConfig,
    WorkingContext,
    import_session_from_elan,
    load_settings,
    load_session,
    normalize_session_videos,
    save_settings,
    split_annotation,
)
from rime_core.checkpoints import (
    KIND_MANUAL,
    KIND_PRE_DESTRUCTIVE,
    KIND_RESTORE_GUARD,
    KIND_SESSION_OPEN,
    create_checkpoint,
    list_checkpoints,
    load_checkpoint,
)
from rime_core.inference import InferenceError
from rime_core.signals import Signal
from rime_core.schema import ProtocolSchema, SchemaValidationError
from rime_core.rule_engine import Violation
from rime_ui.annotation_list import AnnotationListPanel
from rime_ui.annotation_toolbar import AnnotationToolbar
from rime_ui.clinical_panel import ClinicalPanel
from rime_ui.checkpoint_dialog import RestoreCheckpointDialog
from rime_ui.export_dialog import ExportDialog
from rime_ui.import_dialog import ImportDialog
from rime_ui.irr_panel import IRRPanel
from rime_ui.label_dialog import LabelDialog
from rime_ui.model_eval_panel import ModelEvalPanel
from rime_ui.model_loader_dialog import ModelLoaderDialog
from rime_ui.model_runner import ModelRunnerPanel
from rime_ui.model_settings_dialog import ModelSettingsDialog
from rime_ui.multi_view_player import (
    MODE_PRIMARY_ONLY,
    MODE_SECONDARY_ONLY,
    MODE_SIDE_BY_SIDE,
    MultiViewPlayer,
)
from rime_ui.overview_strip import OverviewStrip
from rime_ui.preferences_dialog import PreferencesDialog
from rime_ui.schema_browser import SchemaBrowserWindow
from rime_ui.session_metadata_dialog import SessionMetadataDialog
from rime_ui.session_wizard import SessionWizard
from rime_ui.shortcuts import (
    ACCEPT_GHOST,
    ADD_SNAP_POINT,
    CLEAR_SNAPS,
    COLLAPSE_ALL,
    COMPARE_SESSION,
    CUT_ANNOTATION,
    EDIT_ANNOTATION,
    EXIT_APP,
    EXPAND_ALL,
    IMPORT_SESSION,
    LOAD_MODEL,
    NEW_SESSION,
    OPEN_SESSION,
    PLAY_PAUSE,
    RUN_INFERENCE,
    SAVE_ANNOTATIONS,
    SHOW_SHORTCUTS,
    SPEED_DOWN,
    SPEED_UP,
    TOGGLE_ANNOTATION_LIST,
    TOGGLE_CLINICAL_OUTCOMES,
    TOGGLE_LOOP,
    TOGGLE_IRR_PANEL,
    TOGGLE_MODEL_EVALUATION,
    TOGGLE_MODEL_RUNNER,
    TOGGLE_VIEW,
    ZOOM_FIT,
    event_matches_shortcut,
    resolve_shortcuts,
    shortcut_sequences,
)
from rime_ui.signal_config_dialog import SignalConfigDialog
from rime_ui.theme import DOCK_DEFAULT_WIDTH, app_stylesheet, main_window_stylesheet, set_zero_margins
from rime_ui.timeline import TimelineWidget
from rime_ui.violation_dialog import ViolationDialog


class LayoutMode(Enum):
    ANNOTATION = auto()
    COMPARISON = auto()


class RimeMainWindow(QMainWindow):
    """Main application window with video player, signal panel, and timeline."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("RIME")
        self.setMinimumSize(1200, 800)

        # State
        self._app_settings = load_settings()
        self._default_schema = ProtocolSchema.default()
        self.context: WorkingContext | None = None
        self.session: Session | None = None
        self.annotations = AnnotationStore()
        self._loaded_models: dict[str, CMFPackage] = {}
        self._active_model_name: str | None = None
        self._last_inference_results: dict[str, InferenceResult] = {}
        self._comparison_store: AnnotationStore | None = None
        self._comparison_session: Session | None = None
        self._violation_annotation_ids: set[str] = set()
        self._layout_mode = LayoutMode.ANNOTATION
        self._pending_modified_annotation_id: str | None = None
        self._annotation_modified_timer = QTimer(self)
        self._annotation_modified_timer.setSingleShot(True)
        self._annotation_modified_timer.timeout.connect(self._commit_annotation_modification_refresh)
        self._resolved_shortcuts = resolve_shortcuts(self._app_settings.shortcut_overrides)
        self._shortcut_actions: dict[str, QAction] = {}
        self._suppress_panel_visibility_persistence = False
        self._suppress_session_persistence = False
        self._closing = False

        # Setup UI
        self._setup_menu()
        self._setup_central_widget()
        self._apply_style()
        self._apply_app_settings()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _setup_menu(self) -> None:
        """Create menu bar."""
        menubar = self.menuBar()

        session_menu = menubar.addMenu("&Session")

        new_action = session_menu.addAction("&New Session...")
        self._register_shortcut_action(NEW_SESSION, new_action)
        new_action.triggered.connect(self._on_new_session)

        open_action = session_menu.addAction("&Open Session...")
        self._register_shortcut_action(OPEN_SESSION, open_action)
        open_action.triggered.connect(self._on_open_session)

        import_action = session_menu.addAction("&Import from ELAN...")
        self._register_shortcut_action(IMPORT_SESSION, import_action)
        import_action.triggered.connect(self._on_import_elan)

        session_menu.addSeparator()
        self.schema_builder_action = session_menu.addAction("View Schema...")
        self.schema_builder_action.triggered.connect(self._on_view_schema)
        self.edit_metadata_action = session_menu.addAction("Edit Metadata...")
        self.edit_metadata_action.setEnabled(False)
        self.edit_metadata_action.triggered.connect(self._on_edit_metadata)

        add_menu = session_menu.addMenu("Add")
        add_videos_action = add_menu.addAction("Video...")
        add_videos_action.triggered.connect(self._on_add_video_files)
        add_signals_action = add_menu.addAction("Signals...")
        add_signals_action.triggered.connect(self._on_add_signal_files)

        session_menu.addSeparator()

        save_action = session_menu.addAction("&Save Annotations")
        self._register_shortcut_action(SAVE_ANNOTATIONS, save_action)
        save_action.triggered.connect(self._on_save_annotations)

        export_action = session_menu.addAction("Export Dataset...")
        export_action.triggered.connect(self._on_export_annotations)

        session_menu.addSeparator()

        exit_action = session_menu.addAction("E&xit")
        self._register_shortcut_action(EXIT_APP, exit_action)
        exit_action.triggered.connect(self.close)

        annotate_menu = menubar.addMenu("&Annotate")
        self.clear_loop_action = annotate_menu.addAction("Clear ROI")
        self.clear_loop_action.triggered.connect(self._on_clear_loop_region)
        self.clear_snaps_action = annotate_menu.addAction("Clear All Snap Points")
        self._register_shortcut_action(CLEAR_SNAPS, self.clear_snaps_action)
        self.clear_snaps_action.triggered.connect(self._on_clear_snap_points)
        annotate_menu.addSeparator()
        self.clear_all_ghosts_action = annotate_menu.addAction("Delete All Ghosts")
        self.clear_all_ghosts_action.triggered.connect(self._on_delete_all_ghosts)
        self.clear_all_annotations_action = annotate_menu.addAction("Delete All Annotations")
        self.clear_all_annotations_action.triggered.connect(self._on_clear_all_annotations)
        annotate_menu.addSeparator()
        self.set_snap_tolerance_action = annotate_menu.addAction("Set Snap Tolerance...")
        self.set_snap_tolerance_action.triggered.connect(self._on_set_snap_tolerance)

        view_menu = menubar.addMenu("&View")
        view_menu.addSection("Video Display")
        self.video_display_group = QActionGroup(self)
        self.video_display_group.setExclusive(True)
        self.video_side_by_side_action = view_menu.addAction("Side by Side")
        self.video_side_by_side_action.setCheckable(True)
        self.video_side_by_side_action.triggered.connect(
            lambda checked: checked and self._set_video_display_mode(MODE_SIDE_BY_SIDE)
        )
        self.video_display_group.addAction(self.video_side_by_side_action)
        self.video_primary_only_action = view_menu.addAction("Primary Only")
        self.video_primary_only_action.setCheckable(True)
        self.video_primary_only_action.triggered.connect(
            lambda checked: checked and self._set_video_display_mode(MODE_PRIMARY_ONLY)
        )
        self.video_display_group.addAction(self.video_primary_only_action)
        self.video_secondary_only_action = view_menu.addAction("Secondary Only")
        self.video_secondary_only_action.setCheckable(True)
        self.video_secondary_only_action.triggered.connect(
            lambda checked: checked and self._set_video_display_mode(MODE_SECONDARY_ONLY)
        )
        self.video_display_group.addAction(self.video_secondary_only_action)
        view_menu.addSeparator()

        view_menu.addSection("Signal Display")
        self.signal_display_group = QActionGroup(self)
        self.signal_display_group.setExclusive(True)
        self.single_signal_action = view_menu.addAction("Single Channel")
        self.single_signal_action.setCheckable(True)
        self.single_signal_action.triggered.connect(
            lambda checked: checked and self._set_signal_display_mode(False)
        )
        self.signal_display_group.addAction(self.single_signal_action)
        self.combined_signals_action = view_menu.addAction("Combined Signals")
        self.combined_signals_action.setCheckable(True)
        self.combined_signals_action.setChecked(True)
        self.combined_signals_action.triggered.connect(
            lambda checked: checked and self._set_signal_display_mode(True)
        )
        self.signal_display_group.addAction(self.combined_signals_action)
        self.select_display_signals_action = view_menu.addAction("Select Display Signals...")
        self.select_display_signals_action.triggered.connect(self._on_select_display_signals)
        view_menu.addSeparator()

        collapse_action = view_menu.addAction("Collapse All Lanes")
        self._register_shortcut_action(COLLAPSE_ALL, collapse_action)
        collapse_action.triggered.connect(self._on_collapse_all)
        expand_action = view_menu.addAction("Expand All Lanes")
        self._register_shortcut_action(EXPAND_ALL, expand_action)
        expand_action.triggered.connect(self._on_expand_all)
        view_menu.addSeparator()
        view_menu.addSection("Panels")
        self.annotation_list_action = view_menu.addAction("Annotation List")
        self.annotation_list_action.setCheckable(True)
        self.annotation_list_action.setChecked(True)
        self._register_shortcut_action(TOGGLE_ANNOTATION_LIST, self.annotation_list_action)
        self.annotation_list_action.triggered.connect(self._on_toggle_annotation_list)
        self.model_runner_action = view_menu.addAction("Model Runner")
        self.model_runner_action.setCheckable(True)
        self.model_runner_action.setChecked(True)
        self._register_shortcut_action(TOGGLE_MODEL_RUNNER, self.model_runner_action)
        self.model_runner_action.triggered.connect(self._on_toggle_model_runner)
        self.model_eval_action = view_menu.addAction("Model Evaluation")
        self.model_eval_action.setCheckable(True)
        self.model_eval_action.setChecked(True)
        self._register_shortcut_action(TOGGLE_MODEL_EVALUATION, self.model_eval_action)
        self.model_eval_action.triggered.connect(self._on_toggle_model_eval)
        self.clinical_action = view_menu.addAction("Clinical Outcomes")
        self.clinical_action.setCheckable(True)
        self.clinical_action.setChecked(True)
        self._register_shortcut_action(TOGGLE_CLINICAL_OUTCOMES, self.clinical_action)
        self.clinical_action.triggered.connect(self._on_toggle_clinical)
        self.irr_action = QAction("IRR Panel", self)
        self.irr_action.setCheckable(True)
        self.irr_action.setChecked(False)
        self.irr_action.setEnabled(False)
        self._register_shortcut_action(TOGGLE_IRR_PANEL, self.irr_action)
        self.irr_action.triggered.connect(self._on_toggle_irr)
        self.show_comparison_action = QAction("Show Comparison", self)
        self.show_comparison_action.setCheckable(True)
        self.show_comparison_action.setChecked(True)
        self.show_comparison_action.setEnabled(False)
        self.show_comparison_action.triggered.connect(self._on_toggle_show_comparison)

        review_menu = menubar.addMenu("&Review")
        self.compare_session_action = review_menu.addAction("Compare Session...")
        self._register_shortcut_action(COMPARE_SESSION, self.compare_session_action)
        self.compare_session_action.triggered.connect(self._on_compare_session)
        self.close_comparison_action = review_menu.addAction("Close Comparison")
        self.close_comparison_action.triggered.connect(self._on_close_comparison)
        self.close_comparison_action.setEnabled(False)
        review_menu.addSeparator()
        self.save_checkpoint_action = review_menu.addAction("Save Checkpoint...")
        self.save_checkpoint_action.triggered.connect(self._on_save_checkpoint)
        self.save_checkpoint_action.setEnabled(False)
        self.restore_checkpoint_action = review_menu.addAction("Restore Checkpoint...")
        self.restore_checkpoint_action.triggered.connect(self._on_restore_checkpoint)
        self.restore_checkpoint_action.setEnabled(False)

        models_menu = menubar.addMenu("&Models")
        self.load_model_action = models_menu.addAction("Load Model...")
        self._register_shortcut_action(LOAD_MODEL, self.load_model_action)
        self.load_model_action.triggered.connect(self._on_load_model)
        self.run_inference_action = QAction("Run Inference", self)
        self._register_shortcut_action(RUN_INFERENCE, self.run_inference_action)
        self.run_inference_action.triggered.connect(self._on_run_inference)
        models_menu.addSeparator()
        self.loaded_model_action = models_menu.addAction("No models loaded")
        self.loaded_model_action.setEnabled(False)

        help_menu = menubar.addMenu("&Help")
        self.preferences_action = help_menu.addAction("Preferences...")
        self.preferences_action.setMenuRole(QAction.MenuRole.NoRole)
        self.preferences_action.triggered.connect(self._on_preferences)
        self.shortcuts_action = QAction("Keyboard Shortcuts", self)
        self._register_shortcut_action(SHOW_SHORTCUTS, self.shortcuts_action)
        self.shortcuts_action.triggered.connect(self._show_shortcut_preferences)
        about_action = help_menu.addAction("About")
        about_action.setMenuRole(QAction.MenuRole.NoRole)
        about_action.triggered.connect(self._show_about)

        self._update_model_actions()

    def _setup_central_widget(self) -> None:
        """Create main layout with video player and timeline deck."""
        self.setDockOptions(
            QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
            | QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.ForceTabbedDocks
        )
        self.setTabPosition(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea,
            QTabWidget.TabPosition.North,
        )

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        set_zero_margins(layout)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.video_player = MultiViewPlayer()
        self.main_splitter.addWidget(self.video_player)

        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        set_zero_margins(detail_layout)
        self.overview_strip = OverviewStrip(self)
        detail_layout.addWidget(self.overview_strip)
        self.annotation_toolbar = AnnotationToolbar(self)
        self.annotation_toolbar.delete_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(self.annotation_toolbar.delete_action)
        detail_layout.addWidget(self.annotation_toolbar)
        self.timeline = TimelineWidget(self._default_schema)
        self.timeline.set_shortcuts(self._resolved_shortcuts)
        detail_layout.addWidget(self.timeline, 1)
        self.main_splitter.addWidget(detail_panel)
        self.main_splitter.setSizes([560, 440])
        layout.addWidget(self.main_splitter)

        self.video_player.position_changed.connect(self._on_video_position_changed)
        self.video_player.position_scrubbed.connect(self._on_video_position_changed)
        self.video_player.duration_changed.connect(self._on_video_duration_changed)
        self.overview_strip.position_selected.connect(self._on_overview_position_selected)
        self.overview_strip.view_range_changed.connect(self._on_overview_view_range_changed)

        self.timeline.annotation_created.connect(self._on_annotation_created)
        self.timeline.annotation_modified.connect(self._on_annotation_modified)
        self.timeline.annotation_deleted.connect(self._on_annotation_deleted)
        self.timeline.annotation_selected.connect(self._on_timeline_annotation_selected)
        self.timeline.ghost_accept_requested.connect(self._on_timeline_ghost_accept_requested)
        self.timeline.position_clicked.connect(self._on_timeline_seek)
        self.timeline.snap_point_added.connect(self._on_snap_added)
        self.timeline.snap_point_removed.connect(self._on_snap_removed)
        self.timeline.snap_point_modified.connect(self._on_snap_modified)
        self.timeline.selection_state_changed.connect(self._on_timeline_selection_changed)
        self.timeline.loop_region_changed.connect(self._on_loop_region_changed)
        self.timeline.view_range_changed.connect(self._on_timeline_view_range_changed)
        self.timeline.lane_header_context_requested.connect(self._on_lane_header_context_requested)

        self.annotation_toolbar.delete_requested.connect(self._on_delete_selected)
        self.annotation_toolbar.accept_ghost_requested.connect(self._on_accept_ghost)
        self.annotation_toolbar.reject_ghost_requested.connect(self._on_reject_ghost)
        self.annotation_toolbar.edit_requested.connect(self._on_edit_annotation)
        self.annotation_toolbar.cut_requested.connect(self._on_cut_annotation)
        self.annotation_toolbar.add_snap_point_requested.connect(self._on_add_snap_at_playhead)
        self.annotation_toolbar.loop_toggled.connect(self._on_toggle_loop)
        self.annotation_toolbar.speed_changed.connect(self._on_set_speed)
        self.annotation_toolbar.zoom_fit_requested.connect(self._on_zoom_fit)
        self.annotation_toolbar.view_toggled.connect(self._on_toggle_view_mode)
        self.timeline.signals.display_mode_changed.connect(self._sync_signal_display_actions)
        self.timeline.signals.display_mode_changed.connect(self._on_signal_display_mode_changed)
        self.timeline.signals.display_selection_changed.connect(self._on_signal_display_selection_changed)

        self.annotation_list_panel = AnnotationListPanel(self._default_schema, self)
        self.annotation_list_panel.annotation_activated.connect(self._on_annotation_list_activated)
        self.annotation_list_panel.annotation_edit_requested.connect(
            self._on_annotation_list_edit_requested
        )
        self.annotation_list_panel.confidence_changed.connect(
            self._on_annotation_confidence_changed
        )
        self.annotation_list_dock = QDockWidget("Annotation List", self)
        self.annotation_list_dock.setWidget(self.annotation_list_panel)
        self.annotation_list_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.annotation_list_dock)
        self.annotation_list_dock.setObjectName("annotation_list_dock")
        self.annotation_list_dock.visibilityChanged.connect(
            self._on_annotation_dock_visibility_changed
        )
        self.annotation_list_dock.topLevelChanged.connect(self._on_dock_layout_changed)
        self.annotation_list_dock.dockLocationChanged.connect(self._on_dock_layout_changed)

        self.model_runner_panel = ModelRunnerPanel(self)
        self.model_runner_panel.load_requested.connect(self._on_load_model)
        self.model_runner_panel.run_requested.connect(self._on_run_inference)
        self.model_runner_panel.settings_requested.connect(self._on_edit_model_settings)
        self.model_runner_panel.review_requested.connect(self._on_review_pending_ghosts)
        self.model_runner_panel.unload_requested.connect(self._on_unload_model)
        self.model_runner_dock = QDockWidget("Model Runner", self)
        self.model_runner_dock.setWidget(self.model_runner_panel)
        self.model_runner_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.model_runner_dock)
        self.model_runner_dock.setObjectName("model_runner_dock")
        self.model_runner_dock.visibilityChanged.connect(self._on_model_runner_dock_visibility_changed)
        self.model_runner_dock.topLevelChanged.connect(self._on_dock_layout_changed)
        self.model_runner_dock.dockLocationChanged.connect(self._on_dock_layout_changed)
        self.tabifyDockWidget(self.annotation_list_dock, self.model_runner_dock)

        self.model_eval_panel = ModelEvalPanel(self)
        self.model_eval_dock = QDockWidget("Model Evaluation", self)
        self.model_eval_dock.setWidget(self.model_eval_panel)
        self.model_eval_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.model_eval_dock)
        self.model_eval_dock.setObjectName("model_eval_dock")
        self.model_eval_dock.visibilityChanged.connect(self._on_model_eval_dock_visibility_changed)
        self.model_eval_dock.topLevelChanged.connect(self._on_dock_layout_changed)
        self.model_eval_dock.dockLocationChanged.connect(self._on_dock_layout_changed)
        self.tabifyDockWidget(self.annotation_list_dock, self.model_eval_dock)

        self.clinical_panel = ClinicalPanel(self)
        self.clinical_dock = QDockWidget("Clinical Outcomes", self)
        self.clinical_dock.setWidget(self.clinical_panel)
        self.clinical_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.clinical_dock)
        self.clinical_dock.setObjectName("clinical_dock")
        self.clinical_dock.visibilityChanged.connect(self._on_clinical_dock_visibility_changed)
        self.clinical_dock.topLevelChanged.connect(self._on_dock_layout_changed)
        self.clinical_dock.dockLocationChanged.connect(self._on_dock_layout_changed)
        self.tabifyDockWidget(self.annotation_list_dock, self.clinical_dock)

        self.irr_panel = IRRPanel(self)
        self.irr_panel.filters_changed.connect(self._on_irr_filters_changed)
        self.irr_panel.result_changed.connect(self._on_irr_result_changed)
        self.irr_panel.close_requested.connect(self._on_close_comparison)
        self.irr_dock = QDockWidget("IRR Panel", self)
        self.irr_dock.setWidget(self.irr_panel)
        self.irr_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.irr_dock.setFeatures(
            self.irr_dock.features() & ~QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.irr_dock)
        self.irr_dock.setObjectName("irr_dock")
        self.irr_dock.visibilityChanged.connect(self._on_irr_dock_visibility_changed)
        self.irr_dock.topLevelChanged.connect(self._on_dock_layout_changed)
        self.irr_dock.dockLocationChanged.connect(self._on_dock_layout_changed)
        self.tabifyDockWidget(self.annotation_list_dock, self.irr_dock)
        self._ensure_right_dock_tabs()
        self.annotation_list_dock.raise_()
        self.tabifiedDockWidgetActivated.connect(self._on_tabified_dock_widget_activated)

        self._update_toolbar_state()
        self._refresh_model_panel()
        self._sync_video_display_actions()
        self._sync_signal_display_actions()
        self._apply_layout(LayoutMode.ANNOTATION)
        QTimer.singleShot(0, self._apply_default_dock_widths)

    def _register_shortcut_action(self, shortcut_id: str, action: QAction) -> None:
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(action)
        self._shortcut_actions[shortcut_id] = action

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_dock_layout_state()
        self._closing = True
        self._suppress_panel_visibility_persistence = True
        super().closeEvent(event)

    def _current_schema(self) -> ProtocolSchema:
        if self.context is not None:
            return self.context.schema
        return self._default_schema

    def _on_video_position_changed(self, position_ms: int) -> None:
        self.overview_strip.set_position(position_ms)
        self.timeline.set_position(position_ms)

    def _on_video_duration_changed(self, duration_ms: int) -> None:
        self.overview_strip.set_duration(duration_ms)
        self.timeline.set_duration(duration_ms)
        start_ms, end_ms = self.timeline.get_view_range()
        self.overview_strip.set_view_range(start_ms, end_ms)

    def _on_overview_position_selected(self, position_ms: float) -> None:
        self.video_player.set_position_ms(int(position_ms))

    def _on_overview_view_range_changed(self, start_ms: float, end_ms: float) -> None:
        self.timeline.set_view_range(start_ms, end_ms)

    def _on_timeline_view_range_changed(self, start_ms: float, end_ms: float) -> None:
        self.overview_strip.set_view_range(start_ms, end_ms)

    def _on_timeline_selection_changed(self, has_annotation: bool, has_snap: bool) -> None:
        has_ghost = False
        if has_annotation:
            selected_id = self.timeline.get_selected_id()
            self.annotation_list_panel.select_annotation(selected_id)
            annotation = self.annotations.get(selected_id) if selected_id else None
            has_ghost = bool(annotation and annotation.ghost)
        else:
            self.annotation_list_panel.select_annotation(None)
        self._update_toolbar_state(
            has_annotation=has_annotation,
            has_snap=has_snap,
            has_ghost=has_ghost,
        )

    def _on_timeline_annotation_selected(self, ann_id: str) -> None:
        self.annotation_list_panel.select_annotation(ann_id)

    def _on_timeline_ghost_accept_requested(self, ann_id: str) -> None:
        if self.timeline.get_selected_id() != ann_id:
            self.timeline.select_annotation(ann_id)
        self._on_accept_ghost()

    def _selected_annotation(self) -> Annotation | None:
        ann_id = self.timeline.get_selected_id()
        if not ann_id:
            return None
        return self.annotations.get(ann_id)

    def _refresh_annotation_views(self) -> None:
        selected_id = self.timeline.get_selected_id()
        self._refresh_rule_violation_markers()
        self.timeline.refresh_annotations()
        self.overview_strip.set_annotations(self.annotations.all())
        self.annotation_list_panel.set_store(self.annotations)
        self.annotation_list_panel.select_annotation(selected_id)
        self._refresh_model_panel()

    def _compute_rule_violation_ids(self) -> set[str]:
        """Return the ids of annotations that currently violate schema rules."""
        return {violation.source_annotation.id for violation in self._current_rule_violations()}

    def _current_rule_violations(self) -> list[Violation]:
        """Return the current rule violations for the live annotation store."""
        if self.context is None:
            return []

        violations: list[Violation] = []
        store = self.annotations
        for annotation in store.annotations.values():
            _, create_violations = self.context.rule_engine.on_create(annotation, store)
            violations.extend(create_violations)

        violations.extend(self.context.rule_engine.validate(store))
        return violations

    def _violations_for_annotation(self, ann_id: str) -> list[Violation]:
        """Return current rule violations affecting one annotation."""
        return [
            violation
            for violation in self._current_rule_violations()
            if violation.source_annotation.id == ann_id
        ]

    def _refresh_rule_violation_markers(self) -> None:
        """Recompute and apply persistent rule-violation markers in the timeline."""
        self._violation_annotation_ids = self._compute_rule_violation_ids()
        self.timeline.set_violation_ids(self._violation_annotation_ids)

    def _update_model_actions(self) -> None:
        model = self._current_model()
        model_loaded = model is not None and self.context is not None and self.session is not None
        runnable = False
        if model is not None and model_loaded:
            runnable = True
            for input_config in model.config.inputs:
                input_type = str(input_config.get("type", "signal")).casefold()
                if input_type == "video":
                    runnable = runnable and bool(self.session.videos)
                else:
                    runnable = runnable and bool(self.context.signals)
        self.run_inference_action.setEnabled(runnable)
        if not self._loaded_models:
            self.loaded_model_action.setText("No models loaded")
        elif model is None:
            self.loaded_model_action.setText(f"{len(self._loaded_models)} models loaded")
        else:
            self.loaded_model_action.setText(
                f"{len(self._loaded_models)} loaded · active: {model.name}"
            )

    def _update_toolbar_state(
        self,
        has_annotation: bool | None = None,
        has_snap: bool | None = None,
        has_ghost: bool | None = None,
    ) -> None:
        if has_annotation is None:
            has_annotation = self.timeline.get_selected_id() is not None
        if has_snap is None:
            has_snap = self.timeline.get_selected_snap_index() is not None
        if has_ghost is None:
            annotation = self._selected_annotation()
            has_ghost = bool(annotation and annotation.ghost)

        loop_active = self.video_player.is_loop_active()
        self.annotation_toolbar.set_selection_state(
            has_annotation,
            has_snap,
            loop_active,
            has_ghost,
        )
        self.annotation_toolbar.set_speed(self.video_player.get_speed())

    def _apply_style(self) -> None:
        """Apply dark theme stylesheet."""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(app_stylesheet())
        self.setStyleSheet(main_window_stylesheet())

    def _on_new_session(self) -> None:
        """Create a new session using wizard dialog."""
        result = SessionWizard.create_session(self, app_settings=self._app_settings)
        if not result:
            return

        session, store = result
        self._load_session_data(session, store)
        self.statusBar().showMessage(f"Created session: {session.name}", 3000)

    def _on_import_elan(self) -> None:
        """Import a .eaf file into a RIME session via the all-in-one dialog."""
        dialog_result = ImportDialog.run(self._current_schema(), parent=self)
        if dialog_result is None:
            return

        (
            eaf_path,
            session_dir,
            tier_map,
            label_map,
            apply_rules,
            additional_videos,
            additional_signals,
        ) = dialog_result

        try:
            output_dir = Path(session_dir)
            normalized_videos = [
                self._normalize_path_for_base(path, output_dir) for path in additional_videos
            ]
            signal_configs: list[SignalConfig] = []
            for path in additional_signals:
                cfg = self._prompt_signal_config(path, output_dir=output_dir)
                if cfg is None:
                    self.statusBar().showMessage("ELAN import cancelled.", 3000)
                    return
                signal_configs.append(cfg)

            schema = self._current_schema()
            session, result = import_session_from_elan(
                eaf_path=Path(eaf_path),
                session_dir=output_dir,
                schema=schema,
                tier_map=tier_map or None,
                label_map=label_map or None,
                apply_rules=apply_rules,
                additional_videos=normalized_videos,
                additional_signals=signal_configs,
            )
            self._load_context(WorkingContext.open(session.session_dir))

            for violation in result.violations:
                self._show_violation_dialog(violation)

            self.statusBar().showMessage(
                f"Imported {Path(eaf_path).name} ({len(result.store.annotations)} annotations)",
                5000,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", f"Failed to import ELAN file:\n{exc}")

    def _on_open_session(self) -> None:
        """Open a session.json file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Session",
            "",
            "Session Files (session.json);;All Files (*)",
        )
        if not path:
            return

        self.open_session_path(path)

    def open_session_path(self, path: str | Path) -> bool:
        """Open a session.json from a specific path."""
        try:
            context = WorkingContext.open(path)
            self._load_context(context)
            self.statusBar().showMessage(f"Opened session: {context.session.name}", 3000)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to load session:\n{exc}")
            return False

    def _load_session_data(self, session: Session, store: AnnotationStore) -> None:
        self._load_context(WorkingContext.open(session.session_dir))

    def _clear_session_state(self) -> None:
        """Reset session-bound UI state before loading another session."""
        self._last_inference_results.clear()
        self._comparison_store = None
        self._comparison_session = None
        self._loaded_models.clear()
        self._active_model_name = None
        self.edit_metadata_action.setEnabled(False)
        self.restore_checkpoint_action.setEnabled(False)
        self.save_checkpoint_action.setEnabled(False)
        self.close_comparison_action.setEnabled(False)
        self.show_comparison_action.setEnabled(False)
        self.show_comparison_action.setChecked(True)
        self.video_player.clear_loop()
        self.timeline.clear_loop_region()
        self.overview_strip.clear_loop_region()
        self.timeline.signals.clear()
        self.timeline.signals.clear_overlays()
        self.timeline.set_snap_points([])
        self.timeline.set_comparison_store(None)
        self.timeline.set_store(AnnotationStore())
        self._violation_annotation_ids.clear()
        self.timeline.set_violation_ids(set())
        self.timeline.set_comparison_match_state()
        self.timeline.set_show_comparison(False)
        self.timeline.lanes.clear_selection()
        self.annotation_list_panel.set_store(None)
        self._apply_layout(LayoutMode.ANNOTATION)
        self._update_toolbar_state(has_annotation=False, has_snap=False, has_ghost=False)
        self._refresh_model_panel()

    def _load_context(self, context: WorkingContext) -> None:
        self._clear_session_state()
        self.context = context
        session = context.session
        store = context.store
        self.session = session
        self.annotations = store
        self.context.loaded_models = dict(self._loaded_models)
        self.setWindowTitle(f"RIME - {session.name}")
        self.timeline.set_schema(context.schema)
        self.annotation_list_panel.set_schema(context.schema)
        self._suppress_session_persistence = True
        try:
            # Load all session videos into multi-view player
            if session.videos:
                self.video_player.load_videos(session.videos, session.session_dir)
            else:
                # Fallback: single primary_video string
                video_path = session.get_primary_video_path()
                if video_path.exists():
                    self.video_player.load_video(str(video_path))
            self._apply_playback_speed_default()

            try:
                self.timeline.signals.set_display_config(self._signal_display_entries())
                self.timeline.signals.set_combined_view(bool(session.signal_display_combined))
                self.timeline.set_snap_points(session.snap_points)
            except Exception as exc:
                self.timeline.signals.clear()
                self.statusBar().showMessage(f"Failed to load signal preview: {exc}", 5000)
            self._sync_video_display_actions()
            self._sync_signal_display_actions()

            self.timeline.set_store(self.annotations)
            self._refresh_rule_violation_markers()
            self.timeline.set_comparison_store(self._comparison_store)
            self.timeline.set_show_comparison(
                self._layout_mode is LayoutMode.COMPARISON and self.show_comparison_action.isChecked()
            )
            self.timeline.set_comparison_filters(None, None, None)
            self.overview_strip.set_duration(self._current_duration_ms())
            self.overview_strip.set_annotations(self.annotations.all())
            start_ms, end_ms = self.timeline.get_view_range()
            self.overview_strip.set_view_range(start_ms, end_ms)
            region = self.timeline.get_loop_region()
            if region is None:
                self.overview_strip.clear_loop_region()
            else:
                self.overview_strip.set_loop_region(*region)
            self.overview_strip.set_position(float(self.video_player.get_position_ms()))
            self.timeline.lanes.clear_selection()
            self.timeline.clear_loop_region()
            self.annotation_list_panel.set_store(self.annotations)
            self.video_player.clear_loop()
            missing_models = self._restore_session_models()
            self._restore_dock_layout_state()
            self._apply_layout(LayoutMode.ANNOTATION)
        finally:
            self._suppress_session_persistence = False
        self.edit_metadata_action.setEnabled(True)
        self.restore_checkpoint_action.setEnabled(True)
        self.save_checkpoint_action.setEnabled(True)
        self._create_checkpoint(KIND_SESSION_OPEN, "Session opened")
        self._update_toolbar_state(has_annotation=False, has_snap=False)
        self._update_model_actions()
        self._refresh_model_panel()
        if missing_models:
            QMessageBox.warning(
                self,
                "Missing Models",
                "The following saved models could not be located and were removed from this session:\n- "
                + "\n- ".join(missing_models),
            )
        self.statusBar().showMessage(
            f"Loaded: {len(session.videos)} videos, {len(session.signals)} signals",
            5000,
        )

    def _on_save_annotations(self) -> None:
        if not self.context:
            QMessageBox.warning(self, "Warning", "No session loaded.")
            return

        try:
            self.context.save()
            self.statusBar().showMessage("Annotations saved.", 3000)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save annotations:\n{exc}")

    def _on_export_annotations(self) -> None:
        if not self.context:
            QMessageBox.warning(self, "Warning", "No session loaded.")
            return

        dialog = ExportDialog(
            self.context,
            list(self.context.signals.values()),
            default_output_dir=self._default_export_dir(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.output_dir is None:
            return
        self.statusBar().showMessage(
            f"Exported {dialog.exported_files} files to {dialog.output_dir}",
            5000,
        )

    def _create_checkpoint(self, kind: str, label: str) -> None:
        if self.context is None or self.session is None:
            return
        create_checkpoint(
            self.session.session_dir,
            self.annotations,
            label=label,
            kind=kind,
            snap_points=self.timeline.get_snap_points(),
            loop_region=self.timeline.get_loop_region(),
        )

    def _restore_checkpoint_snapshot(self, snapshot) -> None:
        if self.context is None or self.session is None:
            return
        self._create_checkpoint(
            KIND_RESTORE_GUARD,
            f"Before restore: {snapshot.entry.label}",
        )
        self.context.replace_store(snapshot.store)
        self.annotations = snapshot.store
        self.timeline.set_store(self.annotations)
        self.timeline.set_snap_points(snapshot.snap_points)
        if snapshot.loop_region is None:
            self.timeline.clear_loop_region()
            self.overview_strip.clear_loop_region()
            self.video_player.clear_loop()
        else:
            start_ms, end_ms = self.timeline.set_loop_region(*snapshot.loop_region)
            self.overview_strip.set_loop_region(start_ms, end_ms)
            self.video_player.set_loop(int(start_ms), int(end_ms))
        self._refresh_annotation_views()
        self._update_toolbar_state(has_annotation=False, has_snap=False, has_ghost=False)

    def _remove_annotations_by_ids(self, annotation_ids: list[str]) -> int:
        if self.context is None:
            return 0
        existing_ids = [ann_id for ann_id in annotation_ids if self.annotations.get(ann_id) is not None]
        for ann_id in existing_ids:
            self.annotations.remove(ann_id)
        if not existing_ids:
            return 0
        self.context.save()
        self._refresh_annotation_views()
        self.timeline.clear_selection()
        self._update_toolbar_state(has_annotation=False, has_snap=False, has_ghost=False)
        return len(existing_ids)

    def _on_compare_session(self) -> None:
        if self.context is None:
            QMessageBox.warning(self, "Warning", "Open a session before loading a comparison session.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Compare Session",
            "",
            "Session Files (session.json);;All Files (*)",
        )
        if not path:
            return
        self.load_comparison_path(path)

    def load_comparison_path(self, path: str | Path) -> bool:
        if self.context is None or self.session is None:
            return False
        try:
            comparison_session = load_session(path)
            annotations_path = comparison_session.session_dir / "annotations" / "annotations.json"
            if annotations_path.exists():
                comparison_store = AnnotationStore.load(annotations_path)
            else:
                comparison_store = AnnotationStore()
                comparison_store._session_id = comparison_session.id
                comparison_store._session_name = comparison_session.name
            self._comparison_session = comparison_session
            self._comparison_store = comparison_store
            self.timeline.set_comparison_store(self._comparison_store)
            self._apply_layout(LayoutMode.COMPARISON)
            self.timeline.refresh_annotations()
            self._refresh_irr_panel()
            self._refresh_model_panel()
            self.statusBar().showMessage(
                f"Loaded comparison session: {comparison_session.name}",
                4000,
            )
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Comparison Error", f"Failed to load comparison session:\n{exc}")
            return False

    def _on_close_comparison(self) -> None:
        self._comparison_session = None
        self._comparison_store = None
        self.timeline.set_comparison_store(None)
        self.timeline.set_comparison_filters(None, None, None)
        self.timeline.set_comparison_match_state()
        self._apply_layout(LayoutMode.ANNOTATION)
        self.timeline.refresh_annotations()
        self._refresh_irr_panel()
        self._refresh_model_panel()
        self.statusBar().showMessage("Closed comparison session.", 3000)

    def _on_load_model(self) -> None:
        package = self._prompt_model_package()
        if package is None:
            return
        self._register_loaded_model(package)

    def load_model_path(self, model_path: str | Path) -> bool:
        model_path = str(model_path)
        if Path(model_path).suffix != ".rime":
            QMessageBox.warning(
                self,
                "Model Error",
                "Select a model package folder ending in .rime.",
            )
            return False

        try:
            if self.context is not None:
                package = self.context.load_model(model_path)
            else:
                from rime_core import CMFLoader

                package = CMFLoader.load(model_path)
            return self._register_loaded_model(package)
        except CMFValidationError as exc:
            QMessageBox.critical(self, "Model Error", f"Failed to load model:\n{exc}")
        except Exception as exc:
            QMessageBox.critical(self, "Model Error", f"Unexpected model load failure:\n{exc}")
        return False

    def _register_loaded_model(self, package: CMFPackage) -> bool:
        if self.context is not None and self.context.loaded_models.get(package.name) is not package:
            self.context.register_model_package(package)
        self._loaded_models[package.name] = package
        self._active_model_name = package.name
        self._last_inference_results.pop(package.name, None)
        self._persist_model_path(package)
        self._update_model_actions()
        self._refresh_model_panel()
        self.statusBar().showMessage(f"Loaded model: {package.name}", 3000)
        return True

    def _prompt_model_package(self) -> CMFPackage | None:
        return ModelLoaderDialog.choose_loaded_package(self)

    def _current_model(self, model_name: str | None = None) -> CMFPackage | None:
        if model_name is not None:
            return self._loaded_models.get(model_name)
        if self._active_model_name and self._active_model_name in self._loaded_models:
            return self._loaded_models[self._active_model_name]
        if not self._loaded_models:
            return None
        return next(iter(self._loaded_models.values()))

    def _on_unload_model(self, model_name: str) -> None:
        if model_name not in self._loaded_models:
            return
        self._loaded_models.pop(model_name)
        self._last_inference_results.pop(model_name, None)
        self._remove_persisted_model_path(model_name)
        if self.context is not None:
            try:
                self.context.unload_model(model_name)
            except KeyError:
                pass
        if self._active_model_name == model_name:
            self._active_model_name = next(iter(self._loaded_models), None)
        self._update_model_actions()
        self._refresh_model_panel()
        self.statusBar().showMessage(f"Unloaded model: {model_name}", 3000)

    def _persist_model_path(self, package: CMFPackage) -> None:
        if self.session is None or self.context is None:
            return
        model_path = str(Path(package.path).expanduser().resolve())
        self.session.model_paths[package.name] = self._normalize_path_for_session(model_path)
        self.context.save()

    def _remove_persisted_model_path(self, model_name: str) -> None:
        if self.session is None or self.context is None:
            return
        if self.session.model_paths.pop(model_name, None) is not None:
            self.context.save()

    def _restore_session_models(self) -> list[str]:
        if self.session is None or self.context is None:
            return []

        missing_models: list[str] = []
        removed_any = False
        for model_name, raw_path in list(self.session.model_paths.items()):
            model_path = self.session.get_model_path(model_name)
            if model_path is None or not model_path.exists():
                self.session.model_paths.pop(model_name, None)
                missing_models.append(model_name)
                removed_any = True
                continue
            try:
                package = self.context.load_model(model_path)
            except Exception:
                self.session.model_paths.pop(model_name, None)
                missing_models.append(model_name)
                removed_any = True
                continue
            if package.name != model_name:
                self.session.model_paths.pop(model_name, None)
                self.session.model_paths[package.name] = self._normalize_path_for_session(
                    str(model_path)
                )
                removed_any = True
            if self.context.loaded_models.get(package.name) is not package:
                self.context.register_model_package(package)
            self._loaded_models[package.name] = package
            self._last_inference_results.pop(package.name, None)
            self._active_model_name = package.name

        if removed_any:
            self.context.save()
        return missing_models

    def _on_run_inference(self, model_name: str | None = None) -> None:
        if self.context is None or self.session is None:
            QMessageBox.warning(self, "Warning", "Open a session before running inference.")
            return
        model = self._current_model(model_name)
        if model is None:
            QMessageBox.warning(self, "Warning", "Load a model before running inference.")
            return
        self._active_model_name = model.name
        if not model.config.output_mappings:
            QMessageBox.warning(
                self,
                "Warning",
                "This model does not define any output mappings in config.json.",
            )
            return

        if not self._ensure_model_settings_ready(model):
            return
        settings = self._current_model_settings(model.name)
        bindings: list[InputBinding] = []
        for input_config in model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            if not input_name:
                QMessageBox.warning(self, "Warning", "Model input is missing a name.")
                return
            binding = self._binding_from_settings(model, input_config, settings)
            bindings.append(binding)

        mappings = self._build_output_mappings(model, settings)
        params = self._build_model_params(model, settings)
        time_range = self.timeline.get_loop_region()

        try:
            result = self.context.run_inference(
                bindings,
                mappings,
                model_name=model.name,
                params=params,
                time_range=time_range,
            )
            self._last_inference_results[model.name] = result
            self._refresh_annotation_views()
            self._update_toolbar_state()
            self.statusBar().showMessage(
                f"Inference complete: {len(result.annotations)} ghost annotations",
                4000,
            )
        except InferenceError as exc:
            QMessageBox.critical(self, "Inference Error", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Inference Error", f"Failed to run inference:\n{exc}")

    def _on_edit_model_settings(self, model_name: str | None = None) -> None:
        if self.context is None or self.session is None:
            QMessageBox.warning(self, "Warning", "Open a session before editing model settings.")
            return
        model = self._current_model(model_name)
        if model is None:
            QMessageBox.warning(self, "Warning", "Load a model before editing model settings.")
            return
        self._active_model_name = model.name

        dialog = ModelSettingsDialog(
            model=model,
            schema=self._current_schema(),
            session=self.session,
            signals=self.context.signals,
            settings=self._current_model_settings(model.name),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.context.save()
        self._refresh_model_panel()
        self.statusBar().showMessage("Model settings saved.", 3000)

    def _current_model_settings(self, model_name: str) -> ModelSettings:
        if self.session is None:
            return ModelSettings()
        return self.session.model_settings.setdefault(model_name, ModelSettings())

    def _build_model_params(self, model: CMFPackage, settings: ModelSettings) -> dict[str, object]:
        defaults = {
            str(entry["name"]): entry.get("default")
            for entry in model.config.parameters
        }
        filtered = {name: settings.params[name] for name in defaults if name in settings.params}
        defaults.update(filtered)
        settings.params = dict(defaults)
        return defaults

    def _build_output_mappings(self, model: CMFPackage, settings: ModelSettings) -> list[OutputMapping]:
        overrides = {
            str(entry.get("output_name", "")): entry
            for entry in settings.output_mappings
            if isinstance(entry, dict)
        }
        resolved: list[dict[str, str]] = []
        mappings: list[OutputMapping] = []
        for default in model.config.output_mappings:
            merged = dict(default)
            merged.update(overrides.get(default["output_name"], {}))
            resolved.append(
                {
                    "output_name": merged["output_name"],
                    "lane": merged["lane"],
                    "label": merged["label"],
                }
            )
            mappings.append(
                OutputMapping(
                    output_name=merged["output_name"],
                    lane=merged["lane"],
                    label=merged["label"],
                )
            )
        settings.output_mappings = resolved
        return mappings

    def _pending_model_ghosts(self, model_name: str) -> list[Annotation]:
        if model_name not in self._loaded_models:
            return []
        source = f"model:{model_name}"
        return sorted(
            [
                annotation
                for annotation in self.annotations.all()
                if annotation.ghost and annotation.source == source
            ],
            key=lambda annotation: (annotation.start_ms, annotation.end_ms, annotation.id),
        )

    def _on_review_pending_ghosts(self, model_name: str | None = None) -> None:
        model = self._current_model(model_name)
        if model is None:
            return
        self._active_model_name = model.name
        pending = self._pending_model_ghosts(model.name)
        if not pending:
            return
        first = pending[0]
        self.timeline.select_annotation(first.id)
        self.timeline.seek_to(first.start_ms)
        self._update_toolbar_state(has_annotation=True, has_snap=False, has_ghost=True)

    def _ensure_model_settings_ready(self, model: CMFPackage) -> bool:
        settings = self._current_model_settings(model.name)
        missing = self._missing_model_settings(model, settings)
        if not missing:
            return True

        message = (
            "This model needs settings before it can run:\n- "
            + "\n- ".join(missing)
            + "\n\nThe model settings dialog will open now."
        )
        QMessageBox.information(self, "Model Settings Required", message)
        self._on_edit_model_settings(model.name)
        return not self._missing_model_settings(model, self._current_model_settings(model.name))

    def _missing_model_settings(self, model: CMFPackage, settings: ModelSettings) -> list[str]:
        missing: list[str] = []
        if self.context is None or self.session is None:
            return ["No active model session"]

        for input_config in model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            input_type = str(input_config.get("type", "signal")).casefold()
            binding_mode = str(input_config.get("binding_mode", "channel_map")).casefold()
            source_value = settings.input_sources.get(input_name)
            if not source_value:
                missing.append(f"{input_name}: source")
                continue

            if input_type == "video":
                if not Path(source_value).exists():
                    missing.append(f"{input_name}: source path not found")
                continue

            signal = self.context.signals.get(source_value)
            if signal is None:
                missing.append(f"{input_name}: selected signal not loaded")
                continue
            if binding_mode == "source_only":
                required_channels = [str(channel) for channel in input_config.get("channels", [])]
                missing_channels = [
                    channel for channel in required_channels if channel not in signal.channels
                ]
                if missing_channels:
                    missing.append(
                        f"{input_name}: missing channels {', '.join(missing_channels)}"
                    )
                continue
            channel_map = settings.input_bindings.get(input_name, {})
            for model_channel in [str(channel) for channel in input_config.get("channels", [])]:
                signal_column = channel_map.get(model_channel)
                if not signal_column:
                    missing.append(f"{input_name}: {model_channel}")
                    continue
                if signal_column not in signal.channels:
                    missing.append(f"{input_name}: {model_channel}->{signal_column}")
        return missing

    def _binding_from_settings(
        self,
        model: CMFPackage,
        input_config: dict,
        settings: ModelSettings,
    ) -> InputBinding:
        if self.context is None or self.session is None:
            raise InferenceError("Session context is not available for model inference")

        input_name = str(input_config.get("name", "")).strip()
        input_type = str(input_config.get("type", "signal")).casefold()
        source_value = settings.input_sources.get(input_name)
        if not source_value:
            raise InferenceError(f"Missing source for model input '{input_name}'")

        if input_type == "video":
            return InputBinding(input_name=input_name, video_path=Path(source_value))

        signal = self.context.signals.get(source_value)
        if signal is None:
            raise InferenceError(
                f"Selected signal '{source_value}' for input '{input_name}' is not loaded"
            )
        binding_mode = str(input_config.get("binding_mode", "channel_map")).casefold()
        channel_map = (
            {}
            if binding_mode == "source_only"
            else dict(settings.input_bindings.get(input_name, {}))
        )
        required_channels = [str(channel) for channel in input_config.get("channels", [])]
        expected_rate = input_config.get("sampling_rate_hz", input_config.get("sample_rate_hz"))
        if expected_rate is not None and not np.isclose(signal.sampling_rate_hz, float(expected_rate)):
            signal = self._resample_signal_for_input(
                signal,
                input_name=input_name,
                required_channels=required_channels,
                channel_map=channel_map,
                target_rate_hz=float(expected_rate),
            )
        return InputBinding(
            input_name=input_name,
            signal=signal,
            channel_map=channel_map or None,
        )

    def _describe_input_bindings(self, bindings: list[InputBinding]) -> str:
        signal_count = 0
        video_count = 0
        for binding in bindings:
            if binding.signal is not None:
                signal_count += 1
            elif binding.video_path is not None:
                video_count += 1

        total = signal_count + video_count
        if total == 0:
            return "—"

        parts: list[str] = []
        if signal_count:
            parts.append(f"{signal_count} signal" + ("s" if signal_count != 1 else ""))
        if video_count:
            parts.append(f"{video_count} video" + ("s" if video_count != 1 else ""))
        return ", ".join(parts)

    def _resample_signal_for_input(
        self,
        signal: Signal,
        *,
        input_name: str,
        required_channels: list[str],
        channel_map: dict[str, str],
        target_rate_hz: float,
    ) -> Signal:
        source_time_ms = signal.get_time_ms()
        if len(source_time_ms) == 0:
            return Signal(
                name=f"{signal.name}:{input_name}@{target_rate_hz:g}Hz",
                data=pd.DataFrame({}),
                sampling_rate_hz=target_rate_hz,
                time_column="sample",
                channels=[],
                offset_ms=signal.offset_ms,
                time_reference="sample_index",
            )

        duration_ms = float(source_time_ms[-1] - source_time_ms[0])
        sample_count = max(1, int(round(duration_ms * target_rate_hz / 1000.0)) + 1)
        target_time_ms = (
            np.arange(sample_count, dtype=np.float64) / target_rate_hz * 1000.0 + source_time_ms[0]
        )

        data: dict[str, np.ndarray] = {}
        used_columns: list[str] = []
        for model_channel in required_channels:
            signal_column = channel_map.get(model_channel, model_channel)
            used_columns.append(signal_column)
            values = signal.get_channel(signal_column).astype(np.float64, copy=False)
            data[signal_column] = np.interp(target_time_ms, source_time_ms, values).astype(
                np.float32
            )

        return Signal(
            name=f"{signal.name}:{input_name}@{target_rate_hz:g}Hz",
            data=pd.DataFrame(data),
            sampling_rate_hz=target_rate_hz,
            time_column="sample",
            channels=used_columns,
            offset_ms=signal.offset_ms,
            time_reference="sample_index",
        )

    def _current_duration_ms(self) -> float:
        duration_ms = float(self.video_player.get_duration_ms())
        if duration_ms > 0:
            return duration_ms
        if self.context is not None and self.context.signals:
            return max(signal.duration_ms for signal in self.context.signals.values())
        if self._last_inference_results:
            return max(float(result.duration_ms) for result in self._last_inference_results.values())
        return 0.0

    def _refresh_model_panel(self) -> None:
        if not hasattr(self, "model_runner_panel"):
            return
        self.model_runner_panel.refresh(
            self._loaded_models,
            self.annotations,
            self.timeline.get_loop_region(),
        )
        targets_by_model = {
            model_name: self._build_output_mappings(
                model,
                self._current_model_settings(model_name),
            )
            for model_name, model in self._loaded_models.items()
            if self.session is not None
        }
        self.model_eval_panel.refresh(
            self._loaded_models,
            targets_by_model,
            self.annotations if self._loaded_models else None,
            self._current_duration_ms(),
            self.session.name if self.session is not None else "",
        )
        self._refresh_clinical_panel()
        self._refresh_irr_panel()

    def _refresh_clinical_panel(self) -> None:
        if not hasattr(self, "clinical_panel"):
            return
        self.clinical_panel.refresh(self.context, self._current_duration_ms())

    def _refresh_irr_panel(self) -> None:
        if not hasattr(self, "irr_panel"):
            return
        self.irr_panel.refresh(
            self.session,
            self.annotations if self.session is not None else None,
            self._comparison_session,
            self._comparison_store,
            self._current_duration_ms(),
        )

    def _on_toggle_show_comparison(self, checked: bool) -> None:
        self.timeline.set_show_comparison(
            checked and self._layout_mode is LayoutMode.COMPARISON and self._comparison_store is not None
        )
        self.timeline.refresh_annotations()

    def _on_irr_filters_changed(
        self,
        lane: str | None,
        source_a: str | None,
        source_b: str | None,
    ) -> None:
        self.timeline.set_comparison_filters(lane, source_a, source_b)
        self.timeline.set_comparison_match_state()
        self.timeline.refresh_annotations()

    def _on_irr_result_changed(self, result) -> None:
        if result is None:
            self.timeline.set_comparison_match_state()
        else:
            self.timeline.set_comparison_match_state(
                matched_primary_ids={a.id for a, _ in result.matched_episodes},
                matched_comparison_ids={b.id for _, b in result.matched_episodes},
                unmatched_primary_ids={annotation.id for annotation in result.unmatched_a},
                unmatched_comparison_ids={annotation.id for annotation in result.unmatched_b},
            )
        self.timeline.refresh_annotations()

    def _on_toggle_model_runner(self, checked: bool) -> None:
        if self._layout_mode is not LayoutMode.ANNOTATION:
            return
        self.model_runner_dock.setVisible(checked)

    def _on_toggle_model_eval(self, checked: bool) -> None:
        if self._layout_mode is not LayoutMode.ANNOTATION:
            return
        self.model_eval_dock.setVisible(checked)

    def _on_toggle_clinical(self, checked: bool) -> None:
        if self._layout_mode is not LayoutMode.ANNOTATION:
            return
        self.clinical_dock.setVisible(checked)

    def _on_toggle_irr(self, checked: bool) -> None:
        if self._layout_mode is not LayoutMode.COMPARISON:
            return
        self.irr_dock.setVisible(checked)
        if checked:
            self.irr_dock.raise_()

    def _on_model_runner_dock_visibility_changed(self, visible: bool) -> None:
        self.model_runner_action.blockSignals(True)
        self.model_runner_action.setChecked(visible)
        self.model_runner_action.blockSignals(False)
        self._persist_panel_visibility("model_runner", visible)

    def _on_model_eval_dock_visibility_changed(self, visible: bool) -> None:
        self.model_eval_action.blockSignals(True)
        self.model_eval_action.setChecked(visible)
        self.model_eval_action.blockSignals(False)
        self._persist_panel_visibility("model_evaluation", visible)

    def _on_clinical_dock_visibility_changed(self, visible: bool) -> None:
        self.clinical_action.blockSignals(True)
        self.clinical_action.setChecked(visible)
        self.clinical_action.blockSignals(False)
        self._persist_panel_visibility("clinical_outcomes", visible)

    def _on_irr_dock_visibility_changed(self, visible: bool) -> None:
        self.irr_action.blockSignals(True)
        self.irr_action.setChecked(visible)
        self.irr_action.blockSignals(False)

    def _set_dock_visible(self, dock: QDockWidget, visible: bool, action=None) -> None:
        if action is not None:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        dock.setVisible(visible)

    def _panel_visibility(self, key: str) -> bool:
        if self.session is None:
            return DEFAULT_PANEL_VISIBILITY.get(key, True)
        return bool(self.session.panel_visibility.get(key, True))

    def _persist_panel_visibility(self, key: str, visible: bool) -> None:
        if (
            self._suppress_panel_visibility_persistence
            or self._suppress_session_persistence
            or self._closing
            or self.context is None
            or self.session is None
        ):
            return
        current = self.session.panel_visibility.get(key)
        if current == visible:
            return
        self.session.panel_visibility[key] = visible
        self.context.save()

    def _persist_dock_layout_state(self) -> None:
        if (
            self._suppress_panel_visibility_persistence
            or self._suppress_session_persistence
            or self._closing
            or self.context is None
            or self.session is None
            or self._layout_mode is not LayoutMode.ANNOTATION
        ):
            return
        state = bytes(self.saveState().toBase64()).decode("ascii")
        if self.session.dock_layout_state == state:
            return
        self.session.dock_layout_state = state
        self.context.save()

    def _apply_default_dock_widths(self) -> None:
        self.resizeDocks(
            [
                self.annotation_list_dock,
                self.model_runner_dock,
                self.model_eval_dock,
                self.clinical_dock,
                self.irr_dock,
            ],
            [DOCK_DEFAULT_WIDTH] * 5,
            Qt.Orientation.Horizontal,
        )

    def _ensure_right_dock_tabs(self) -> None:
        anchor = self.annotation_list_dock
        for dock in (
            self.model_runner_dock,
            self.model_eval_dock,
            self.clinical_dock,
            self.irr_dock,
        ):
            self.tabifyDockWidget(anchor, dock)

    def _restore_dock_layout_state(self) -> None:
        if self.session is None or not self.session.dock_layout_state:
            self._ensure_right_dock_tabs()
            self._apply_default_dock_widths()
            return
        self._suppress_panel_visibility_persistence = True
        try:
            encoded = self.session.dock_layout_state.encode("ascii")
            self.restoreState(QByteArray.fromBase64(encoded))
            self._ensure_right_dock_tabs()
        finally:
            self._suppress_panel_visibility_persistence = False

    def _on_dock_layout_changed(self, *_args) -> None:
        self._persist_dock_layout_state()

    def _on_tabified_dock_widget_activated(self, _dock: QDockWidget) -> None:
        self._persist_dock_layout_state()

    def _apply_layout(self, mode: LayoutMode) -> None:
        self._layout_mode = mode
        comparison_active = mode is LayoutMode.COMPARISON and self._comparison_store is not None
        annotation_actions_enabled = mode is LayoutMode.ANNOTATION and self.session is not None

        self.compare_session_action.setEnabled(not comparison_active)
        self.close_comparison_action.setEnabled(comparison_active)
        self.restore_checkpoint_action.setEnabled(annotation_actions_enabled)
        self.show_comparison_action.setEnabled(comparison_active)
        self.save_checkpoint_action.setEnabled(annotation_actions_enabled)
        self.clear_snaps_action.setEnabled(annotation_actions_enabled)
        self.clear_loop_action.setEnabled(annotation_actions_enabled)
        self.clear_all_ghosts_action.setEnabled(annotation_actions_enabled)
        self.clear_all_annotations_action.setEnabled(annotation_actions_enabled)
        self.set_snap_tolerance_action.setEnabled(annotation_actions_enabled)
        if not comparison_active:
            self.show_comparison_action.blockSignals(True)
            self.show_comparison_action.setChecked(True)
            self.show_comparison_action.blockSignals(False)

        self.timeline.set_signal_panel_visible(mode is LayoutMode.ANNOTATION)
        self.single_signal_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.combined_signals_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.select_display_signals_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.annotation_list_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.model_runner_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.model_eval_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.clinical_action.setEnabled(mode is LayoutMode.ANNOTATION)
        self.irr_action.setEnabled(comparison_active)

        self._suppress_panel_visibility_persistence = True
        try:
            self._set_dock_visible(
                self.annotation_list_dock,
                mode is LayoutMode.ANNOTATION and self._panel_visibility("annotation_list"),
                action=self.annotation_list_action,
            )
            self._set_dock_visible(
                self.model_runner_dock,
                mode is LayoutMode.ANNOTATION and self._panel_visibility("model_runner"),
                action=self.model_runner_action,
            )
            self._set_dock_visible(
                self.model_eval_dock,
                mode is LayoutMode.ANNOTATION and self._panel_visibility("model_evaluation"),
                action=self.model_eval_action,
            )
            self._set_dock_visible(
                self.clinical_dock,
                mode is LayoutMode.ANNOTATION and self._panel_visibility("clinical_outcomes"),
                action=self.clinical_action,
            )
            self._set_dock_visible(
                self.irr_dock,
                mode is LayoutMode.COMPARISON,
                action=self.irr_action,
            )
        finally:
            self._suppress_panel_visibility_persistence = False

        if mode is LayoutMode.COMPARISON:
            self.timeline.set_show_comparison(self.show_comparison_action.isChecked())
            self.main_splitter.setSizes([520, 480])
            if self.irr_dock.isVisible():
                self.irr_dock.raise_()
        else:
            self.timeline.set_show_comparison(False)
            self.main_splitter.setSizes([560, 440])

        self.timeline.refresh_annotations()

    def _on_add_video_files(self) -> None:
        """Add extra videos to currently loaded session metadata."""
        if not self.context or not self.session:
            QMessageBox.warning(self, "No Session", "Open or create a session first.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Video Files to Session",
            "",
            "Videos (*.mp4 *.mov *.avi *.mkv);;All Files (*)",
        )
        if not paths:
            return

        normalized_paths: list[str] = []
        for raw_path in paths:
            normalized = self._normalize_path_for_session(raw_path)
            if normalized not in normalized_paths:
                normalized_paths.append(normalized)

        changed, message = self._apply_selected_video_paths(normalized_paths)
        if not changed:
            self.statusBar().showMessage(message, 3000)
            return

        self.context.save()

        # Reload all videos into multi-view player
        self.video_player.load_videos(self.session.videos, self.session.session_dir)
        self._update_model_actions()
        self._refresh_model_panel()

        self.statusBar().showMessage(message, 4000)

    def _apply_selected_video_paths(self, normalized_paths: list[str]) -> tuple[bool, str]:
        if self.session is None:
            return False, "Open or create a session first."

        current_videos = normalize_session_videos(self.session.videos)
        self.session.videos = list(current_videos)
        self.session.primary_video = current_videos[0].path if current_videos else ""

        existing_paths = {video.path for video in current_videos}
        candidates = [path for path in normalized_paths if path not in existing_paths]
        if not candidates:
            return False, "No new video files were added."

        if len(current_videos) < MAX_SESSION_VIDEOS:
            available_slots = MAX_SESSION_VIDEOS - len(current_videos)
            to_add = candidates[:available_slots]
            ignored = len(candidates) - len(to_add)
            for path in to_add:
                role = "primary" if not self.session.videos else "secondary"
                self.session.videos.append(VideoConfig(path=path, role=role))
                if role == "primary":
                    self.session.primary_video = path
            self.session.videos = normalize_session_videos(self.session.videos)
            self.session.primary_video = self.session.videos[0].path if self.session.videos else ""
            if ignored:
                QMessageBox.information(
                    self,
                    "Video Limit Reached",
                    f"Sessions support up to {MAX_SESSION_VIDEOS} videos. Extra selections were ignored.",
                )
            return True, f"Updated session videos ({len(self.session.videos)}/{MAX_SESSION_VIDEOS})."

        if len(candidates) == 1:
            slot = self._prompt_video_slot_replacement()
            if slot is None:
                return False, "Video update cancelled."
            replacement = replace(current_videos[slot], path=candidates[0])
            current_videos[slot] = replacement
        else:
            reply = QMessageBox.question(
                self,
                "Replace Session Videos",
                "This session already has primary and secondary videos.\n\n"
                "Replace both slots with the first two selected videos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False, "Video update cancelled."
            current_videos = [
                VideoConfig(path=candidates[0], role="primary"),
                VideoConfig(path=candidates[1], role="secondary"),
            ]
            if len(candidates) > MAX_SESSION_VIDEOS:
                QMessageBox.information(
                    self,
                    "Video Limit Reached",
                    f"Only the first {MAX_SESSION_VIDEOS} selected videos were used.",
                )

        self.session.videos = normalize_session_videos(current_videos)
        self.session.primary_video = self.session.videos[0].path if self.session.videos else ""
        return True, f"Updated session videos ({len(self.session.videos)}/{MAX_SESSION_VIDEOS})."

    def _prompt_video_slot_replacement(self) -> int | None:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("Replace Video")
        dialog.setText("This session already has primary and secondary videos.")
        dialog.setInformativeText("Which slot would you like to replace?")
        primary_button = dialog.addButton("Replace Primary", QMessageBox.ButtonRole.AcceptRole)
        secondary_button = dialog.addButton("Replace Secondary", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == primary_button:
            return 0
        if clicked == secondary_button:
            return 1
        return None

    def _on_add_signal_files(self) -> None:
        """Add extra signals to currently loaded session metadata."""
        if not self.context or not self.session:
            QMessageBox.warning(self, "No Session", "Open or create a session first.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Signal Files to Session",
            "",
            "Signal Files (*.csv *.h5 *.hdf5);;All Files (*)",
        )
        if not paths:
            return

        existing = {signal.path for signal in self.session.signals}
        added = 0
        new_configs: list[SignalConfig] = []
        for raw_path in paths:
            normalized = self._normalize_path_for_session(raw_path)
            if normalized in existing:
                continue
            cfg = self._prompt_signal_config(raw_path)
            if cfg is None:
                self.statusBar().showMessage("Signal add cancelled.", 3000)
                return
            new_configs.append(cfg)
            existing.add(normalized)
            added += 1

        if added == 0:
            self.statusBar().showMessage("No new signal files were added.", 3000)
            return

        self.session.signals.extend(new_configs)

        self.context.save()
        self.statusBar().showMessage(f"Added {added} signal file(s) to session metadata.", 4000)

        # Try loading the first newly-added CSV signal as preview.
        for cfg in new_configs:
            try:
                signal = self.context.loader_registry.load(self.session.get_signal_path(cfg), cfg)
                WorkingContext._apply_session_time_alignment(signal, cfg, self.session)
                self.context.signals[WorkingContext._signal_key(cfg, signal)] = signal
            except Exception:
                continue
        self._refresh_loaded_sources()
        self._update_model_actions()
        self._refresh_model_panel()

    def _signal_display_entries(self) -> list[tuple[Signal, list[str]]]:
        if not self.context or not self.session:
            return []

        entries: list[tuple[Signal, list[str]]] = []
        for signal in self.context.signals.values():
            sig_cfg = self._signal_config_for_signal(signal)
            display_channels = list(sig_cfg.display_channels) if sig_cfg else []
            entries.append((signal, display_channels))
        return entries

    def _signal_config_for_signal(self, signal: Signal) -> SignalConfig | None:
        if self.session is None:
            return None
        exact_name_matches = [cfg for cfg in self.session.signals if cfg.name and cfg.name == signal.name]
        if exact_name_matches:
            return exact_name_matches[0]
        stem_matches = [cfg for cfg in self.session.signals if Path(cfg.path).stem == signal.name]
        if stem_matches:
            return stem_matches[0]
        return None

    def _on_signal_display_selection_changed(self, selection: dict[str, list[str]]) -> None:
        if self.context is None or self.session is None:
            return
        if self._suppress_session_persistence:
            return

        updated = False
        for signal in self.context.signals.values():
            cfg = self._signal_config_for_signal(signal)
            if cfg is None:
                continue
            channels = [
                channel
                for channel in signal.channels
                if channel in selection.get(signal.name, [])
            ]
            if cfg.display_channels != channels:
                cfg.display_channels = channels
                updated = True

        if not updated:
            return

        self.context.save()
        self.statusBar().showMessage("Signal display preferences saved.", 2500)

    def _on_signal_display_mode_changed(self, combined: bool) -> None:
        if self.context is None or self.session is None:
            return
        if self._suppress_session_persistence:
            return
        if self.session.signal_display_combined == combined:
            return
        self.session.signal_display_combined = combined
        self.context.save()

    def _refresh_loaded_sources(self) -> None:
        if not self.session:
            return

        current_position_ms = self.video_player.get_position_ms()
        if self.session.videos:
            self.video_player.load_videos(self.session.videos, self.session.session_dir)
            self.video_player.set_position_ms(current_position_ms)
        self.timeline.signals.set_display_config(self._signal_display_entries())
        self.timeline.signals.set_position(float(self.video_player.get_position_ms()))

    def _normalize_path_for_session(self, raw_path: str) -> str:
        """Store path relative to session directory when possible."""
        if not self.session:
            return raw_path
        return self._normalize_path_for_base(raw_path, self.session.session_dir)

    def _normalize_path_for_base(self, raw_path: str, base_dir: Path) -> str:
        """Store path relative to a base directory when possible."""
        path = Path(raw_path)
        if not path.is_absolute():
            return raw_path
        try:
            return str(path.relative_to(base_dir))
        except ValueError:
            return str(path)

    def _prompt_signal_config(self, raw_path: str, output_dir: Path | None = None) -> SignalConfig | None:
        """Confirm signal metadata before adding a file to the session."""
        normalized_path = (
            self._normalize_path_for_base(raw_path, output_dir)
            if output_dir
            else self._normalize_path_for_session(raw_path)
        )
        return SignalConfigDialog.configure_signal(
            signal_path=raw_path,
            stored_path=normalized_path,
            parent=self,
        )

    def _on_annotation_created(self, level: int, start_ms: float, end_ms: float) -> None:
        if not self.context:
            return
        lane_cfg = self.context.schema.get_lane_by_level(level)
        if not lane_cfg:
            return

        label = LabelDialog.get_label(level, self.context.schema, self)
        if not label:
            return

        annotation, violations = self.context.create_annotation(
            lane=lane_cfg.name,
            label=label,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        validate_violations = self.context.validate()
        for violation in [*violations, *validate_violations]:
            self._show_violation_dialog(violation)

        self._refresh_annotation_views()
        self.statusBar().showMessage(f"Created {label} annotation", 2000)
        self._update_toolbar_state()

    def _on_annotation_deleted(self, ann_id: str) -> None:
        if not self.context:
            return
        ann = self.annotations.get(ann_id)
        if not ann:
            return
        if ann.ghost:
            self._on_reject_ghost(ann_id)
            return
        self.context.delete_annotation(ann_id)
        self.timeline.lanes.clear_selection()
        self._refresh_annotation_views()
        self.statusBar().showMessage(f"Deleted {ann.label}", 2000)
        self._update_toolbar_state()

    def _on_annotation_modified(self, ann_id: str, _start_ms: float, _end_ms: float) -> None:
        self._pending_modified_annotation_id = ann_id
        self.overview_strip.set_annotations(self.annotations.all())
        self._annotation_modified_timer.start(150)

    def _commit_annotation_modification_refresh(self) -> None:
        if self.context:
            self.context.save()
        self._refresh_rule_violation_markers()
        self.timeline.refresh_annotations()
        self.overview_strip.set_annotations(self.annotations.all())
        self.annotation_list_panel.set_store(self.annotations)
        if self._pending_modified_annotation_id:
            self.annotation_list_panel.select_annotation(self._pending_modified_annotation_id)
        self._refresh_model_panel()
        self._update_toolbar_state()

    def _on_accept_ghost(self) -> None:
        if not self.context:
            return
        ann = self._selected_annotation()
        if ann is None or not ann.ghost:
            return

        current_key = (ann.start_ms, ann.end_ms, ann.id)
        accepted, violations = self.context.accept_ghost(ann.id)
        self._refresh_annotation_views()
        for violation in violations:
            self._show_violation_dialog(violation)
        if ann.source.startswith("model:"):
            self._select_next_ghost(after_key=current_key, source=ann.source, reveal=True)
        self.statusBar().showMessage(f"Accepted {accepted.label}", 2000)
        self._update_toolbar_state()

    def _on_reject_ghost(self, ann_id: str | None = None) -> None:
        if not self.context:
            return
        target_id = ann_id or self.timeline.get_selected_id()
        if not target_id:
            return
        ann = self.annotations.get(target_id)
        if ann is None or not ann.ghost:
            return

        current_key = (ann.start_ms, ann.end_ms, ann.id)
        label = ann.label
        self.context.reject_ghost(target_id)
        self.timeline.lanes.clear_selection()
        self._refresh_annotation_views()
        if ann.source.startswith("model:"):
            self._select_next_ghost(after_key=current_key, source=ann.source, reveal=True)
        self.statusBar().showMessage(f"Rejected {label}", 2000)
        self._update_toolbar_state()

    def _select_next_ghost(
        self,
        after_key: tuple[float, float, str],
        *,
        source: str | None = None,
        reveal: bool = False,
    ) -> None:
        ghosts = sorted(
            [
                annotation
                for annotation in self.annotations.all()
                if annotation.ghost and (source is None or annotation.source == source)
            ],
            key=lambda annotation: (annotation.start_ms, annotation.end_ms, annotation.id),
        )
        next_ghost = next(
            (
                annotation
                for annotation in ghosts
                if (annotation.start_ms, annotation.end_ms, annotation.id) > after_key
            ),
            None,
        )
        if next_ghost is None and ghosts:
            next_ghost = ghosts[0]
        if next_ghost is None:
            self._update_toolbar_state()
            return
        self.timeline.select_annotation(next_ghost.id)
        if reveal:
            self.timeline.seek_to(next_ghost.start_ms)
        self._update_toolbar_state(has_annotation=True, has_snap=False, has_ghost=True)

    def _show_violation_dialog(self, violation: Violation) -> None:
        decision = ViolationDialog.ask(violation, self)
        if decision.apply_fix:
            self._apply_violation_fix(violation)

    def _apply_violation_fix(self, violation: Violation) -> bool:
        """Apply a suggested rule fix to the live annotation store."""
        if violation.fix_annotation is None or not self.context:
            return False

        fix = violation.fix_annotation
        existing = self.annotations.get(fix.id)
        if existing:
            existing.start_ms = fix.start_ms
            existing.end_ms = fix.end_ms
            existing.label = fix.label
            existing.lane = fix.lane
            existing.event_type = fix.event_type
            existing.source = fix.source
            existing.ghost = fix.ghost
            existing.confidence = fix.confidence
        else:
            self.annotations.add(fix)
        self.context.save()
        self._refresh_annotation_views()
        self._update_toolbar_state()
        return True

    def _on_timeline_seek(self, time_ms: float) -> None:
        self.video_player.set_position_ms(int(time_ms))

    def _on_save_checkpoint(self) -> None:
        if self.session is None:
            return
        label, accepted = QInputDialog.getText(
            self,
            "Save Checkpoint",
            "Checkpoint label:",
            text="Manual checkpoint",
        )
        if not accepted:
            return
        checkpoint_label = label.strip() or "Manual checkpoint"
        self._create_checkpoint(KIND_MANUAL, checkpoint_label)
        self.statusBar().showMessage(f"Checkpoint saved: {checkpoint_label}", 2500)

    def _on_restore_checkpoint(self) -> None:
        if self.session is None:
            return
        checkpoints = list_checkpoints(self.session.session_dir)
        if not checkpoints:
            self.statusBar().showMessage("No checkpoints available", 2000)
            return
        dialog = RestoreCheckpointDialog(
            checkpoints,
            self.session.session_dir / "checkpoints",
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        checkpoint_id = dialog.selected_checkpoint_id()
        if checkpoint_id is None:
            return
        snapshot = load_checkpoint(self.session.session_dir, checkpoint_id)
        self._restore_checkpoint_snapshot(snapshot)
        self.statusBar().showMessage(f"Restored checkpoint: {snapshot.entry.label}", 3000)

    def _on_clear_snap_points(self) -> None:
        count = len(self.timeline.get_snap_points())
        if count == 0:
            self.statusBar().showMessage("No snap points to clear", 2000)
            return
        self._create_checkpoint(KIND_PRE_DESTRUCTIVE, "Clear All Snap Points")
        self.timeline.clear_all_snap_points()
        self._persist_snap_points()
        self._update_toolbar_state(has_snap=False)
        self.statusBar().showMessage(f"Cleared {count} snap points", 2000)

    def _on_snap_added(self, time_ms: float) -> None:
        self._persist_snap_points()
        time_str = f"{int(time_ms / 1000)}:{int(time_ms % 1000):03d}"
        self._update_toolbar_state()
        self.statusBar().showMessage(f"Snap point added at {time_str}", 2000)

    def _on_snap_removed(self, time_ms: float) -> None:
        self._persist_snap_points()
        self._update_toolbar_state()
        self.statusBar().showMessage("Snap point removed", 2000)

    def _on_snap_modified(self) -> None:
        self._persist_snap_points()
        self._update_toolbar_state()

    def _on_delete_selected(self) -> None:
        selected_id = self.timeline.get_selected_id()
        if selected_id:
            self._on_annotation_deleted(selected_id)
            return

        snap_index = self.timeline.get_selected_snap_index()
        if snap_index is not None:
            self.timeline.remove_snap_point(snap_index)
            self._update_toolbar_state()

    def _on_add_snap_at_playhead(self) -> None:
        self.timeline.add_snap_point(self.video_player.get_position_ms())

    def _persist_snap_points(self) -> None:
        if self.context is None or self.session is None:
            return
        snap_points = self.timeline.get_snap_points()
        if self.session.snap_points == snap_points:
            return
        self.session.snap_points = list(snap_points)
        self.context.save()

    def _on_edit_annotation(self, ann_id: str | None = None) -> None:
        target_id = ann_id or self.timeline.get_selected_id()
        if not target_id:
            return

        ann = self.annotations.get(target_id)
        if not ann:
            return

        if not self.context:
            return
        lane_cfg = self.context.schema.get_lane(ann.lane)
        if not lane_cfg:
            return

        decision = LabelDialog.edit_label(
            lane_cfg.level,
            self.context.schema,
            ann.label,
            violations=self._violations_for_annotation(target_id),
            parent=self,
        )
        if not decision:
            return

        if decision.fix_violation is not None:
            if self._apply_violation_fix(decision.fix_violation):
                if self.annotations.get(target_id) is not None:
                    self.timeline.select_annotation(target_id)
                self.statusBar().showMessage("Applied suggested fix", 2000)
            return

        if not decision.label:
            return

        self.context.edit_annotation(target_id, label=decision.label)

        self._refresh_annotation_views()
        self.timeline.select_annotation(target_id)
        self.statusBar().showMessage("Annotation label updated", 2000)
        self._update_toolbar_state()

    def _on_cut_annotation(self) -> None:
        ann = self._selected_annotation()
        if not ann:
            return

        split_ms = self.video_player.get_position_ms()
        parts = split_annotation(self.annotations, ann.id, split_ms)
        if parts is None:
            self.statusBar().showMessage("Move playhead inside the annotation to split.", 2500)
            return

        left, _right = parts
        if self.context:
            self.context.save()

        self._refresh_annotation_views()
        self.timeline.select_annotation(left.id)
        self.statusBar().showMessage("Annotation split at playhead", 2500)
        self._update_toolbar_state()

    def _on_toggle_loop(self, checked: bool) -> None:
        if not checked:
            self.video_player.clear_loop()
            self.timeline.clear_loop_region()
            self.overview_strip.clear_loop_region()
            self._refresh_model_panel()
            self.statusBar().showMessage("ROI cleared from playback/inference", 1500)
            self._update_toolbar_state()
            return

        ann = self._selected_annotation()
        if ann:
            start = max(0, int(ann.start_ms))
            end = int(max(start + 1, ann.end_ms))
            duration = self.video_player.get_duration_ms()
            if duration > 0:
                end = min(end, duration)
            if end <= start:
                end = min(duration, start + 1) if duration > 0 else start + 1
            start, end = self.timeline.set_loop_region(start, end)
            self.video_player.set_loop(int(start), int(end))
            self.video_player.set_position_ms(int(start))
            self.statusBar().showMessage(f"ROI set from {ann.label}", 2000)
            self._update_toolbar_state()
            return

        position = self.video_player.get_position_ms()
        duration = self.video_player.get_duration_ms()
        default_span_ms = 2000
        start = position
        end = position + default_span_ms
        if duration > 0:
            start = max(0, min(start, duration - 1))
            end = min(duration, max(start + 1, end))
        start, end = self.timeline.set_loop_region(start, end)
        self.video_player.set_loop(int(start), int(end))
        self.video_player.set_position_ms(int(start))
        self.statusBar().showMessage("ROI set from playhead", 2000)
        self._update_toolbar_state()

    def _on_loop_region_changed(self, start_ms: float, end_ms: float) -> None:
        self.overview_strip.set_loop_region(start_ms, end_ms)
        if self.video_player.is_loop_active():
            self.video_player.set_loop(int(start_ms), int(end_ms))
        self._refresh_model_panel()

    def _on_set_speed(self, rate: float) -> None:
        actual = self.video_player.set_speed(rate)
        self.annotation_toolbar.set_speed(actual)
        self.statusBar().showMessage(f"Playback speed: {actual:.2g}x", 1500)

    def _on_preferences(self) -> None:
        updated = PreferencesDialog.edit_settings(self._app_settings, self)
        if updated is None:
            return
        self._app_settings = updated
        save_settings(updated)
        self._apply_app_settings()
        self.statusBar().showMessage("Preferences saved.", 2500)

    def _on_edit_metadata(self) -> None:
        if self.context is None or self.session is None:
            QMessageBox.warning(self, "No Session", "Open or create a session first.")
            return

        updated = SessionMetadataDialog.edit_session(self.session, self)
        if updated is None:
            return

        self.session.name = updated["name"]
        self.session.rater = updated["rater"]
        self.session.session_start_utc = updated["session_start_utc"]
        if any(
            (
                updated["subject_id"],
                updated["condition"],
                updated["medication_state"],
            )
        ):
            self.session.subject = SubjectInfo(
                id=updated["subject_id"],
                condition=updated["condition"],
                medication_state=updated["medication_state"],
            )
        else:
            self.session.subject = None

        self.annotations._session_name = self.session.name
        self.context.save()
        self.setWindowTitle(f"RIME - {self.session.name}")
        self._refresh_irr_panel()
        self.statusBar().showMessage("Session metadata updated.", 2500)

    def _show_shortcut_preferences(self) -> None:
        updated = PreferencesDialog.edit_settings(
            self._app_settings,
            self,
            initial_tab="Shortcuts",
        )
        if updated is None:
            return
        self._app_settings = updated
        save_settings(updated)
        self._apply_app_settings()
        self.statusBar().showMessage("Preferences saved.", 2500)

    def _on_view_schema(self) -> None:
        schema_path: Path | None = None
        schema = self._default_schema
        if self.session is not None and self.session.schema_path:
            candidate = Path(self.session.schema_path)
            if not candidate.is_absolute():
                candidate = self.session.session_dir / candidate
            if candidate.exists():
                schema_path = candidate
                try:
                    schema = ProtocolSchema.load(candidate)
                except SchemaValidationError as exc:
                    QMessageBox.warning(
                        self,
                        "Invalid Session Schema",
                        f"Failed to load the session schema:\n{exc}\n\nOpening the built-in schema instead.",
                    )
                    schema = self._default_schema
                    schema_path = None

        dialog = SchemaBrowserWindow(
            schema=schema,
            schema_path=schema_path,
            read_only=True,
            parent=self,
        )
        dialog.exec()

    def _on_zoom_fit(self) -> None:
        self.timeline.zoom_to_fit()

    def _on_toggle_view_mode(self) -> None:
        label = self.video_player.toggle_display_mode()
        self._sync_video_display_actions()
        self.statusBar().showMessage(f"Video display: {label}", 2000)

    def _set_video_display_mode(self, mode: str) -> None:
        self.video_player.set_display_mode(mode)
        self._sync_video_display_actions()
        self.statusBar().showMessage(
            f"Video display: {self.video_player.get_display_mode_label()}",
            2000,
        )

    def _sync_video_display_actions(self) -> None:
        mode = self.video_player.get_display_mode()
        mapping = {
            MODE_SIDE_BY_SIDE: self.video_side_by_side_action,
            MODE_PRIMARY_ONLY: self.video_primary_only_action,
            MODE_SECONDARY_ONLY: self.video_secondary_only_action,
        }
        for action in mapping.values():
            action.blockSignals(True)
            action.setChecked(False)
            action.blockSignals(False)
        target = mapping.get(mode, self.video_side_by_side_action)
        target.blockSignals(True)
        target.setChecked(True)
        target.blockSignals(False)

    def _set_signal_display_mode(self, combined: bool) -> None:
        if self._layout_mode is not LayoutMode.ANNOTATION:
            return
        self.timeline.signals.set_combined_view(combined)
        self._sync_signal_display_actions(combined)
        self.statusBar().showMessage(
            f"Signal display: {'combined channels' if combined else 'single channel'}",
            2000,
        )

    def _sync_signal_display_actions(self, combined: bool | None = None) -> None:
        if combined is None:
            combined = self.timeline.signals.is_combined_view()
        self.combined_signals_action.blockSignals(True)
        self.combined_signals_action.setChecked(combined)
        self.combined_signals_action.blockSignals(False)
        self.single_signal_action.blockSignals(True)
        self.single_signal_action.setChecked(not combined)
        self.single_signal_action.blockSignals(False)

    def _apply_app_settings(self) -> None:
        self._apply_playback_speed_default()
        self._apply_shortcut_settings()

    def _apply_shortcut_settings(self) -> None:
        self._resolved_shortcuts = resolve_shortcuts(self._app_settings.shortcut_overrides)
        for shortcut_id, action in self._shortcut_actions.items():
            shortcut = self._resolved_shortcuts.get(shortcut_id, "")
            action.setShortcuts(list(shortcut_sequences(shortcut)))
        if hasattr(self, "annotation_toolbar"):
            self.annotation_toolbar.apply_shortcuts(self._resolved_shortcuts)
        if hasattr(self, "timeline"):
            self.timeline.set_shortcuts(self._resolved_shortcuts)

    def _trigger_delete_shortcut(self) -> None:
        if not hasattr(self, "annotation_toolbar"):
            return
        if self._focus_widget_uses_delete_key():
            return
        if not self.annotation_toolbar.delete_action.isEnabled():
            return
        self.annotation_toolbar.delete_action.trigger()

    @staticmethod
    def _focus_widget_uses_delete_key() -> bool:
        widget = QApplication.focusWidget()
        if widget is None:
            return False
        if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(widget, QComboBox) and widget.isEditable():
            return True
        return False

    def _apply_playback_speed_default(self) -> None:
        actual = self.video_player.set_speed(self._app_settings.default_playback_speed)
        if hasattr(self, "annotation_toolbar"):
            self.annotation_toolbar.set_speed(actual)

    def _default_export_dir(self) -> Path:
        configured = self._app_settings.default_export_dir.strip()
        if configured:
            session_name = self._safe_export_session_name()
            return Path(configured) / session_name
        if self.session is not None:
            return self.session.session_dir / "exports"
        return Path.cwd() / "exports"

    def _safe_export_session_name(self) -> str:
        if self.session is None:
            return "session"
        raw = (self.session.name or "").strip()
        if not raw:
            return self.session.id or "session"
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", " "} else "_" for ch in raw)
        cleaned = "_".join(cleaned.split())
        return cleaned or (self.session.id or "session")

    @staticmethod
    def _display_source_name(source: str | None) -> str:
        if not source:
            return "all"
        if source == "manual":
            return "manual"
        if source.startswith("model:"):
            return source[len("model:") :]
        if source.startswith("rater:"):
            return source[len("rater:") :]
        return source

    def _on_toggle_annotation_list(self, checked: bool) -> None:
        if self._layout_mode is not LayoutMode.ANNOTATION:
            return
        self.annotation_list_dock.setVisible(checked)

    def _on_annotation_dock_visibility_changed(self, visible: bool) -> None:
        self.annotation_list_action.blockSignals(True)
        self.annotation_list_action.setChecked(visible)
        self.annotation_list_action.blockSignals(False)
        self._persist_panel_visibility("annotation_list", visible)

    def _on_annotation_list_activated(self, ann_id: str) -> None:
        ann = self.annotations.get(ann_id)
        if not ann:
            return
        self.timeline.select_annotation(ann_id)
        self.video_player.set_position_ms(int(ann.start_ms))
        self._update_toolbar_state()

    def _on_annotation_list_edit_requested(self, ann_id: str) -> None:
        self.timeline.select_annotation(ann_id)
        self._on_edit_annotation(ann_id)

    def _on_annotation_confidence_changed(self, ann_id: str, confidence: float) -> None:
        if not self.context:
            return
        try:
            self.context.edit_annotation(ann_id, confidence=confidence)
        except Exception as exc:
            QMessageBox.critical(self, "Confidence Error", f"Failed to update confidence:\n{exc}")
            QTimer.singleShot(0, self._refresh_annotation_views)
            return
        self.statusBar().showMessage(f"Confidence updated to {confidence * 100:.0f}%", 2000)
        QTimer.singleShot(0, self._refresh_annotation_views)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About RIME",
            "RIME\n\nVideo-and-signal annotation environment for multimodal review.",
        )

    def _on_select_display_signals(self) -> None:
        if self._layout_mode is not LayoutMode.ANNOTATION:
            return
        self.timeline.signals.open_display_selector()

    def _on_clear_loop_region(self) -> None:
        if self.timeline.get_loop_region() is None:
            self.statusBar().showMessage("No ROI to clear", 2000)
            return
        self._create_checkpoint(KIND_PRE_DESTRUCTIVE, "Clear ROI")
        self.video_player.clear_loop()
        self.timeline.clear_loop_region()
        self.overview_strip.clear_loop_region()
        self._refresh_model_panel()
        self._update_toolbar_state()
        self.statusBar().showMessage("ROI cleared", 2000)

    def _on_set_snap_tolerance(self) -> None:
        current = int(round(self.timeline.snap_tolerance_ms()))
        value, accepted = QInputDialog.getInt(
            self,
            "Set Snap Tolerance",
            "Snap sensitivity window (ms):",
            value=current,
            minValue=0,
            maxValue=5000,
            step=25,
        )
        if not accepted:
            return
        self.timeline.set_snap_tolerance_ms(float(value))
        self.statusBar().showMessage(f"Snap tolerance set to {value} ms", 2500)

    def _on_delete_all_ghosts(self) -> None:
        if self.context is None:
            return
        ghost_ids = [annotation.id for annotation in self.annotations.all() if annotation.ghost]
        if not ghost_ids:
            self.statusBar().showMessage("No ghost annotations to clear", 2000)
            return
        self._create_checkpoint(KIND_PRE_DESTRUCTIVE, "Delete All Ghosts")
        count = self._remove_annotations_by_ids(ghost_ids)
        self.statusBar().showMessage(f"Deleted {count} ghost annotations", 2500)

    def _on_clear_all_annotations(self) -> None:
        if self.context is None:
            return
        all_ids = [annotation.id for annotation in self.annotations.all()]
        if not all_ids:
            self.statusBar().showMessage("No annotations to clear", 2000)
            return
        self._create_checkpoint(KIND_PRE_DESTRUCTIVE, "Delete All Annotations")
        count = self._remove_annotations_by_ids(all_ids)
        self.statusBar().showMessage(f"Deleted {count} annotations", 2500)

    def _on_lane_header_context_requested(self, lane_name: str, source: str | None, global_pos) -> None:
        if self.context is None or self._layout_mode is not LayoutMode.ANNOTATION:
            return
        menu = QMenu(self)
        clear_ghosts_action = menu.addAction("Clear Ghosts")
        clear_all_action = menu.addAction("Clear All")
        chosen = menu.exec(global_pos)
        if chosen == clear_ghosts_action:
            self._clear_lane_annotations(lane_name, source=source, ghosts_only=True)
        elif chosen == clear_all_action:
            self._clear_lane_annotations(lane_name, source=source, ghosts_only=False)

    def _clear_lane_annotations(
        self,
        lane_name: str,
        *,
        source: str | None,
        ghosts_only: bool,
    ) -> None:
        if self.context is None:
            return
        source_label = self._display_source_name(source)
        annotation_ids = [
            annotation.id
            for annotation in self.annotations.all()
            if annotation.lane == lane_name
            and (source is None or annotation.source == source)
            and (annotation.ghost if ghosts_only else True)
        ]
        if not annotation_ids:
            message = f"No {'ghost ' if ghosts_only else ''}annotations on {lane_name} [{source_label}]"
            self.statusBar().showMessage(message, 2000)
            return
        label = (
            f"Clear Lane Ghosts: {lane_name} [{source_label}]"
            if ghosts_only
            else f"Clear Lane: {lane_name} [{source_label}]"
        )
        self._create_checkpoint(KIND_PRE_DESTRUCTIVE, label)
        count = self._remove_annotations_by_ids(annotation_ids)
        noun = "ghost annotations" if ghosts_only else "annotations"
        self.statusBar().showMessage(
            f"Cleared {count} {noun} on {lane_name} [{source_label}]",
            2500,
        )

    def _on_collapse_all(self) -> None:
        if hasattr(self, "timeline"):
            for name in self.timeline.lanes._group_state:
                self.timeline.lanes._group_state[name] = True
            self.timeline.lanes._recalculate_height()
            self.statusBar().showMessage("All lanes collapsed", 2000)

    def _on_expand_all(self) -> None:
        if hasattr(self, "timeline"):
            for name in self.timeline.lanes._group_state:
                self.timeline.lanes._group_state[name] = False
            self.timeline.lanes._recalculate_height()
            self.statusBar().showMessage("All lanes expanded", 2000)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._handle_global_navigation(event):
            return

        if self._matches_shortcut(event, PLAY_PAUSE):
            if hasattr(self, "video_player"):
                self.video_player._toggle_play()
            event.accept()
            return

        if self._matches_shortcut(event, ADD_SNAP_POINT):
            if hasattr(self, "timeline"):
                self.timeline.add_snap_point(self.timeline._current_position_ms)
            event.accept()
            return

        if self._matches_shortcut(event, ACCEPT_GHOST):
            self._on_accept_ghost()
            event.accept()
            return

        # V = toggle video display mode
        if self._matches_shortcut(event, TOGGLE_VIEW):
            if hasattr(self, "video_player"):
                label = self.video_player.toggle_display_mode()
                self._sync_video_display_actions()
                self.statusBar().showMessage(f"Video display: {label}", 2000)
            event.accept()
            return

        if self._matches_shortcut(event, EDIT_ANNOTATION):
            self._on_edit_annotation()
            event.accept()
            return

        if self._matches_shortcut(event, CUT_ANNOTATION):
            self._on_cut_annotation()
            event.accept()
            return

        if self._matches_shortcut(event, TOGGLE_LOOP):
            if self.video_player.is_loop_active():
                self._on_toggle_loop(False)
            else:
                self._on_toggle_loop(True)
            event.accept()
            return

        if self._matches_shortcut(event, SPEED_DOWN):
            actual = self.video_player.speed_down()
            self.annotation_toolbar.set_speed(actual)
            self.statusBar().showMessage(f"Playback speed: {actual:.2g}x", 1500)
            event.accept()
            return

        if self._matches_shortcut(event, SPEED_UP):
            actual = self.video_player.speed_up()
            self.annotation_toolbar.set_speed(actual)
            self.statusBar().showMessage(f"Playback speed: {actual:.2g}x", 1500)
            event.accept()
            return

        if self._matches_shortcut(event, ZOOM_FIT):
            self._on_zoom_fit()
            event.accept()
            return

        if self._matches_shortcut(event, SHOW_SHORTCUTS):
            self._show_shortcut_preferences()
            event.accept()
            return

        super().keyPressEvent(event)

    def _matches_shortcut(self, event: QKeyEvent, shortcut_id: str) -> bool:
        return event_matches_shortcut(event, self._resolved_shortcuts.get(shortcut_id, ""))

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and self.isActiveWindow():
            ke = event
            if (
                ke.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)
                and watched is QApplication.focusWidget()
                and not self._focus_widget_uses_delete_key()
            ):
                self._trigger_delete_shortcut()
                return True
            if self._handle_global_navigation(event):
                return True
        return super().eventFilter(watched, event)

    def _handle_global_navigation(self, event: QKeyEvent) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False
        if modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            return False

        if not hasattr(self, "video_player") or self.video_player.get_duration_ms() <= 0:
            return False

        frame_ms = 33 * (10 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1)
        step = -frame_ms if key == Qt.Key.Key_Left else frame_ms
        current = self.video_player.get_position_ms()
        new_pos = max(0, min(self.video_player.get_duration_ms(), current + step))
        self.video_player.set_position_ms(new_pos)
        event.accept()
        return True
