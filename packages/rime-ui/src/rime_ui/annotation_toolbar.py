"""Annotation actions toolbar."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QStyle, QToolBar

from rime_ui.shortcuts import (
    ACCEPT_GHOST,
    ADD_SNAP_POINT,
    CUT_ANNOTATION,
    DELETE_SELECTION,
    EDIT_ANNOTATION,
    SPEED_DOWN,
    SPEED_UP,
    TOGGLE_LOOP,
    TOGGLE_VIEW,
    ZOOM_FIT,
    display_shortcut,
    shortcut_sequences,
)
from rime_ui.theme import COLOR_TEXT_EMPHASIS

try:
    import qtawesome as qta
except ImportError:  # pragma: no cover - fallback for environments without qtawesome
    qta = None


SPEED_STEPS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]


class AnnotationToolbar(QToolBar):
    """Toolbar for annotation and review workflows."""

    accept_ghost_requested = Signal()
    reject_ghost_requested = Signal()
    delete_requested = Signal()
    edit_requested = Signal()
    cut_requested = Signal()
    add_snap_point_requested = Signal()
    loop_toggled = Signal(bool)
    speed_changed = Signal(float)
    zoom_fit_requested = Signal()
    view_toggled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Annotation Toolbar", parent)
        self.setMovable(False)
        self.setFloatable(False)
        self.setOrientation(Qt.Orientation.Horizontal)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._current_speed = 1.0
        self._setup_actions()
        self.set_selection_state(
            has_annotation=False,
            has_snap=False,
            loop_active=False,
            has_ghost=False,
        )

    def _setup_actions(self) -> None:
        # ── Annotation editing ─────────────────────────────────────────────
        self.delete_action = self._add_action(
            icon_name="mdi6.delete-outline",
            text="Delete",
            tooltip="Delete selected annotation or snap point",
            fallback=QStyle.StandardPixmap.SP_TrashIcon,
            slot=self.delete_requested.emit,
        )
        self.edit_action = self._add_action(
            icon_name="mdi6.pencil-outline",
            text="Edit",
            tooltip="Edit selected annotation label",
            fallback=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            slot=self.edit_requested.emit,
        )
        self.cut_action = self._add_action(
            icon_name="mdi6.content-cut",
            text="Cut",
            tooltip="Split selected annotation at playhead",
            fallback=QStyle.StandardPixmap.SP_TitleBarShadeButton,
            slot=self.cut_requested.emit,
        )
        self.add_snap_point_action = self._add_action(
            icon_name="mdi6.magnet-on",
            text="Add Snap Point",
            tooltip="Add snap point at playhead",
            fallback=QStyle.StandardPixmap.SP_DialogApplyButton,
            slot=self.add_snap_point_requested.emit,
        )
        self.loop_action = self._add_action(
            icon_name="mdi6.vector-square",
            text="ROI",
            tooltip="Active ROI for playback and inference",
            fallback=QStyle.StandardPixmap.SP_BrowserReload,
            checkable=True,
        )
        self.loop_action.toggled.connect(self.loop_toggled.emit)

        self.addSeparator()

        # ── Playback / navigation ──────────────────────────────────────────
        self.speed_down_action = self._add_action(
            icon_name="mdi6.rewind",
            text="Speed -",
            tooltip="Decrease playback speed",
            fallback=QStyle.StandardPixmap.SP_MediaSeekBackward,
            slot=self._on_speed_down,
        )
        self.speed_up_action = self._add_action(
            icon_name="mdi6.fast-forward",
            text="Speed +",
            tooltip="Increase playback speed",
            fallback=QStyle.StandardPixmap.SP_MediaSeekForward,
            slot=self._on_speed_up,
        )
        self.zoom_fit_action = self._add_action(
            icon_name="mdi6.fit-to-screen-outline",
            text="Zoom Fit",
            tooltip="Reset timeline zoom to full duration",
            fallback=QStyle.StandardPixmap.SP_DesktopIcon,
            slot=self.zoom_fit_requested.emit,
        )
        self.view_toggle_action = self._add_action(
            icon_name="mdi6.view-split-vertical",
            text="Toggle View",
            tooltip="Cycle video display layout",
            fallback=QStyle.StandardPixmap.SP_TitleBarNormalButton,
            slot=self.view_toggled.emit,
        )

        self.addSeparator()

        # ── Ghost review (enabled only when a ghost is selected) ───────────
        self.accept_ghost_action = self._add_action(
            icon_name="mdi6.check-circle-outline",
            text="Accept",
            tooltip="Accept selected ghost annotation",
            fallback=QStyle.StandardPixmap.SP_DialogApplyButton,
            slot=self.accept_ghost_requested.emit,
        )
        self.reject_ghost_action = self._add_action(
            icon_name="mdi6.close-circle-outline",
            text="Reject",
            tooltip="Reject selected ghost annotation",
            fallback=QStyle.StandardPixmap.SP_DialogDiscardButton,
            slot=self.reject_ghost_requested.emit,
        )

    def _add_action(
        self,
        icon_name: str,
        text: str,
        tooltip: str,
        fallback: QStyle.StandardPixmap,
        slot=None,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(self._icon(icon_name, fallback), text, self)
        action.setToolTip(tooltip)
        action.setCheckable(checkable)
        if slot is not None:
            action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _icon(self, icon_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        if qta is not None:
            try:
                return qta.icon(icon_name, color=COLOR_TEXT_EMPHASIS)
            except Exception:
                pass
        return self.style().standardIcon(fallback)

    def set_selection_state(
        self,
        has_annotation: bool,
        has_snap: bool,
        loop_active: bool,
        has_ghost: bool = False,
    ) -> None:
        self.accept_ghost_action.setEnabled(has_ghost)
        self.reject_ghost_action.setEnabled(has_ghost)
        self.delete_action.setEnabled(has_annotation or has_snap)
        self.edit_action.setEnabled(has_annotation)
        self.cut_action.setEnabled(has_annotation)
        self.loop_action.setEnabled(True)
        self.loop_action.blockSignals(True)
        self.loop_action.setChecked(loop_active)
        self.loop_action.blockSignals(False)

    def apply_shortcuts(self, shortcuts: dict[str, str]) -> None:
        self._set_shortcut_tooltip(
            self.delete_action,
            shortcuts.get(DELETE_SELECTION, ""),
            "Delete selected annotation or snap point",
        )
        self._apply_shortcut(
            self.accept_ghost_action,
            shortcuts.get(ACCEPT_GHOST, ""),
            "Accept selected ghost annotation",
        )
        self._set_shortcut_tooltip(
            self.reject_ghost_action,
            shortcuts.get(DELETE_SELECTION, ""),
            "Reject selected ghost annotation",
        )
        self._apply_shortcut(
            self.edit_action,
            shortcuts.get(EDIT_ANNOTATION, ""),
            "Edit selected annotation label",
        )
        self._apply_shortcut(
            self.cut_action,
            shortcuts.get(CUT_ANNOTATION, ""),
            "Split selected annotation at playhead",
        )
        self._apply_shortcut(
            self.add_snap_point_action,
            shortcuts.get(ADD_SNAP_POINT, ""),
            "Add snap point at playhead",
        )
        self._apply_shortcut(
            self.loop_action,
            shortcuts.get(TOGGLE_LOOP, ""),
            "Active ROI for playback and inference",
        )
        self._apply_shortcut(
            self.speed_down_action,
            shortcuts.get(SPEED_DOWN, ""),
            "Decrease playback speed",
        )
        self._apply_shortcut(
            self.speed_up_action,
            shortcuts.get(SPEED_UP, ""),
            "Increase playback speed",
        )
        self._apply_shortcut(
            self.zoom_fit_action,
            shortcuts.get(ZOOM_FIT, ""),
            "Reset timeline zoom to full duration",
        )
        self._apply_shortcut(
            self.view_toggle_action,
            shortcuts.get(TOGGLE_VIEW, ""),
            "Cycle video display layout",
        )

    @staticmethod
    def _apply_shortcut(action: QAction, shortcut: str, tooltip: str) -> None:
        action.setShortcuts(list(shortcut_sequences(shortcut)))
        shown = display_shortcut(shortcut)
        action.setToolTip(f"{tooltip} ({shown})" if shortcut else f"{tooltip} (Unbound)")

    @staticmethod
    def _set_shortcut_tooltip(action: QAction, shortcut: str, tooltip: str) -> None:
        shown = display_shortcut(shortcut)
        action.setToolTip(f"{tooltip} ({shown})" if shortcut else f"{tooltip} (Unbound)")

    def set_speed(self, rate: float) -> None:
        if rate in SPEED_STEPS:
            self._current_speed = rate

    def _on_speed_down(self) -> None:
        index = SPEED_STEPS.index(self._current_speed)
        if index > 0:
            self._current_speed = SPEED_STEPS[index - 1]
        self.speed_changed.emit(self._current_speed)

    def _on_speed_up(self) -> None:
        index = SPEED_STEPS.index(self._current_speed)
        if index < len(SPEED_STEPS) - 1:
            self._current_speed = SPEED_STEPS[index + 1]
        self.speed_changed.emit(self._current_speed)
