"""Shared keyboard shortcut definitions and helpers for the UI."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence


SECTION_PLAYBACK = "Playback"
SECTION_ANNOTATION = "Annotation Editing"
SECTION_TIMELINE = "Timeline Selection"
SECTION_LAYOUT = "Panels And Layout"
SECTION_SESSION = "Session And Models"
SECTION_HELP = "Help"

SECTION_ORDER = (
    SECTION_PLAYBACK,
    SECTION_ANNOTATION,
    SECTION_TIMELINE,
    SECTION_LAYOUT,
    SECTION_SESSION,
    SECTION_HELP,
)

PLAY_PAUSE = "play_pause"
MOVE_BACKWARD = "move_backward"
MOVE_FORWARD = "move_forward"
MOVE_BACKWARD_FAST = "move_backward_fast"
MOVE_FORWARD_FAST = "move_forward_fast"
ACCEPT_GHOST = "accept_ghost"
DELETE_SELECTION = "delete_selection"
EDIT_ANNOTATION = "edit_annotation"
CUT_ANNOTATION = "cut_annotation"
ADD_SNAP_POINT = "add_snap_point"
TOGGLE_LOOP = "toggle_loop"
SPEED_DOWN = "speed_down"
SPEED_UP = "speed_up"
ZOOM_FIT = "zoom_fit"
TOGGLE_VIEW = "toggle_view"
CLEAR_SELECTION = "clear_selection"
COLLAPSE_ALL = "collapse_all"
EXPAND_ALL = "expand_all"
TOGGLE_ANNOTATION_LIST = "toggle_annotation_list"
TOGGLE_MODEL_RUNNER = "toggle_model_runner"
TOGGLE_MODEL_EVALUATION = "toggle_model_evaluation"
TOGGLE_CLINICAL_OUTCOMES = "toggle_clinical_outcomes"
TOGGLE_IRR_PANEL = "toggle_irr_panel"
NEW_SESSION = "new_session"
OPEN_SESSION = "open_session"
IMPORT_SESSION = "import_session"
SAVE_ANNOTATIONS = "save_annotations"
COMPARE_SESSION = "compare_session"
LOAD_MODEL = "load_model"
RUN_INFERENCE = "run_inference"
CLEAR_SNAPS = "clear_snaps"
SHOW_SHORTCUTS = "show_shortcuts"
EXIT_APP = "exit_app"

HARD_CODED_SHORTCUT_IDS = {
    MOVE_BACKWARD,
    MOVE_FORWARD,
    MOVE_BACKWARD_FAST,
    MOVE_FORWARD_FAST,
}


@dataclass(frozen=True, slots=True)
class ShortcutBinding:
    id: str
    label: str
    description: str
    section: str
    default: str


@dataclass(frozen=True, slots=True)
class ShortcutEntry:
    shortcut: str
    action: str


@dataclass(frozen=True, slots=True)
class ShortcutSection:
    title: str
    entries: tuple[ShortcutEntry, ...]


SHORTCUT_BINDINGS: tuple[ShortcutBinding, ...] = (
    ShortcutBinding(PLAY_PAUSE, "Play or pause", "Play or pause the active video", SECTION_PLAYBACK, "Space"),
    ShortcutBinding(
        MOVE_BACKWARD,
        "Move backward",
        "Step backward one frame",
        SECTION_PLAYBACK,
        "Left",
    ),
    ShortcutBinding(
        MOVE_FORWARD,
        "Move forward",
        "Step forward one frame",
        SECTION_PLAYBACK,
        "Right",
    ),
    ShortcutBinding(
        MOVE_BACKWARD_FAST,
        "Move backward fast",
        "Step backward 10 frames",
        SECTION_PLAYBACK,
        "Shift+Left",
    ),
    ShortcutBinding(
        MOVE_FORWARD_FAST,
        "Move forward fast",
        "Step forward 10 frames",
        SECTION_PLAYBACK,
        "Shift+Right",
    ),
    ShortcutBinding(SPEED_DOWN, "Decrease speed", "Decrease playback speed", SECTION_PLAYBACK, "["),
    ShortcutBinding(SPEED_UP, "Increase speed", "Increase playback speed", SECTION_PLAYBACK, "]"),
    ShortcutBinding(
        TOGGLE_LOOP,
        "Toggle ROI",
        "Toggle the active ROI for playback and inference",
        SECTION_PLAYBACK,
        "L",
    ),
    ShortcutBinding(
        TOGGLE_VIEW,
        "Cycle video layout",
        "Cycle the video layout",
        SECTION_PLAYBACK,
        "V",
    ),
    ShortcutBinding(
        ADD_SNAP_POINT,
        "Add snap point",
        "Add a snap point at the playhead",
        SECTION_ANNOTATION,
        "M",
    ),
    ShortcutBinding(
        ACCEPT_GHOST,
        "Accept ghost",
        "Accept the selected ghost annotation",
        SECTION_ANNOTATION,
        "Return",
    ),
    ShortcutBinding(
        DELETE_SELECTION,
        "Delete or reject",
        "Delete the selected annotation or snap point, or reject a ghost",
        SECTION_ANNOTATION,
        "Delete",
    ),
    ShortcutBinding(
        EDIT_ANNOTATION,
        "Edit annotation",
        "Edit the selected annotation label",
        SECTION_ANNOTATION,
        "E",
    ),
    ShortcutBinding(
        CUT_ANNOTATION,
        "Split annotation",
        "Split the selected annotation at the playhead",
        SECTION_ANNOTATION,
        "C",
    ),
    ShortcutBinding(
        CLEAR_SELECTION,
        "Clear selection",
        "Clear the current timeline selection",
        SECTION_ANNOTATION,
        "Esc",
    ),
    ShortcutBinding(
        ZOOM_FIT,
        "Zoom to fit",
        "Reset the timeline zoom to the full duration",
        SECTION_TIMELINE,
        "Ctrl+0",
    ),
    ShortcutBinding(
        COLLAPSE_ALL,
        "Collapse all lanes",
        "Collapse all annotation lane groups",
        SECTION_LAYOUT,
        "Ctrl+[",
    ),
    ShortcutBinding(
        EXPAND_ALL,
        "Expand all lanes",
        "Expand all annotation lane groups",
        SECTION_LAYOUT,
        "Ctrl+]",
    ),
    ShortcutBinding(
        TOGGLE_ANNOTATION_LIST,
        "Toggle annotation list",
        "Show or hide the annotation list",
        SECTION_LAYOUT,
        "F5",
    ),
    ShortcutBinding(
        TOGGLE_MODEL_RUNNER,
        "Toggle model runner",
        "Show or hide the model runner panel",
        SECTION_LAYOUT,
        "F6",
    ),
    ShortcutBinding(
        TOGGLE_MODEL_EVALUATION,
        "Toggle model evaluation",
        "Show or hide the model evaluation panel",
        SECTION_LAYOUT,
        "F7",
    ),
    ShortcutBinding(
        TOGGLE_CLINICAL_OUTCOMES,
        "Toggle clinical outcomes",
        "Show or hide the clinical outcomes panel",
        SECTION_LAYOUT,
        "F8",
    ),
    ShortcutBinding(
        TOGGLE_IRR_PANEL,
        "Toggle IRR panel",
        "Show or hide the IRR panel",
        SECTION_LAYOUT,
        "F9",
    ),
    ShortcutBinding(NEW_SESSION, "New session", "Create a new session", SECTION_SESSION, "Ctrl+N"),
    ShortcutBinding(OPEN_SESSION, "Open session", "Open an existing session", SECTION_SESSION, "Ctrl+O"),
    ShortcutBinding(
        IMPORT_SESSION,
        "Import from ELAN",
        "Import a session from ELAN",
        SECTION_SESSION,
        "Ctrl+I",
    ),
    ShortcutBinding(
        SAVE_ANNOTATIONS,
        "Save annotations",
        "Save annotations",
        SECTION_SESSION,
        "Ctrl+S",
    ),
    ShortcutBinding(
        COMPARE_SESSION,
        "Compare session",
        "Open a comparison session",
        SECTION_SESSION,
        "Ctrl+2",
    ),
    ShortcutBinding(LOAD_MODEL, "Load model", "Load a model package", SECTION_SESSION, "Ctrl+M"),
    ShortcutBinding(
        RUN_INFERENCE,
        "Run inference",
        "Run inference with the active model",
        SECTION_SESSION,
        "Ctrl+R",
    ),
    ShortcutBinding(
        CLEAR_SNAPS,
        "Clear all snap points",
        "Clear all snap points",
        SECTION_SESSION,
        "Ctrl+Shift+M",
    ),
    ShortcutBinding(
        SHOW_SHORTCUTS,
        "Show shortcuts",
        "Open Preferences on the Shortcuts tab",
        SECTION_HELP,
        "F1",
    ),
    ShortcutBinding(EXIT_APP, "Quit RIME", "Quit RIME", SECTION_HELP, "Ctrl+Q"),
)

SHORTCUT_BINDINGS_BY_ID = {binding.id: binding for binding in SHORTCUT_BINDINGS}


def shortcut_bindings_by_section() -> tuple[tuple[str, tuple[ShortcutBinding, ...]], ...]:
    """Return bindings grouped by section in display order."""
    grouped: list[tuple[str, tuple[ShortcutBinding, ...]]] = []
    for section in SECTION_ORDER:
        section_bindings = tuple(
            binding for binding in SHORTCUT_BINDINGS if binding.section == section
        )
        grouped.append((section, section_bindings))
    return tuple(grouped)


def resolve_shortcuts(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolve active shortcuts from defaults plus user overrides."""
    resolved: dict[str, str] = {}
    for binding in SHORTCUT_BINDINGS:
        if (
            binding.id not in HARD_CODED_SHORTCUT_IDS
            and overrides
            and binding.id in overrides
            and isinstance(overrides[binding.id], str)
        ):
            resolved[binding.id] = overrides[binding.id].strip()
        else:
            resolved[binding.id] = binding.default
    return resolved


def build_shortcut_sections(
    shortcuts: Mapping[str, str] | None = None,
) -> tuple[ShortcutSection, ...]:
    """Build help-dialog sections from active shortcuts."""
    resolved = resolve_shortcuts(shortcuts)
    sections: list[ShortcutSection] = []
    for section, bindings in shortcut_bindings_by_section():
        entries = [
            ShortcutEntry(
                shortcut=display_shortcut(resolved.get(binding.id, "")),
                action=binding.description,
            )
            for binding in bindings
        ]
        if section == SECTION_TIMELINE:
            backward = display_shortcut(resolved.get(MOVE_BACKWARD, ""))
            forward = display_shortcut(resolved.get(MOVE_FORWARD, ""))
            entries.extend(
                (
                    ShortcutEntry(
                        shortcut=f"Alt + {backward} / Alt + {forward}",
                        action="Move the selected snap or point annotation, or the start edge of an interval",
                    ),
                    ShortcutEntry(
                        shortcut="Alt + Shift + Left / Right",
                        action="Move the selected interval end edge",
                    ),
                )
            )
        sections.append(
            ShortcutSection(
                section,
                tuple(entries),
            )
        )
    return tuple(sections)


def display_shortcut(shortcut: str) -> str:
    """Format a shortcut for user-facing display."""
    aliases = shortcut_aliases(shortcut)
    if not aliases:
        return "Unbound"
    return " / ".join(aliases)


def event_matches_shortcut(event: QKeyEvent, shortcut: str) -> bool:
    """Return True when the event matches a configured single-stroke shortcut."""
    pressed = QKeySequence(event.keyCombination())
    for target in shortcut_sequences(shortcut):
        if pressed.matches(target) == QKeySequence.SequenceMatch.ExactMatch:
            return True
    return False


def shortcut_sequences(shortcut: str) -> tuple[QKeySequence, ...]:
    """Return concrete QKeySequence objects for a shortcut and its aliases."""
    sequences: list[QKeySequence] = []
    for alias in shortcut_aliases(shortcut):
        if alias == "Backspace":
            sequences.append(QKeySequence(Qt.Key.Key_Backspace))
        elif alias == "Delete":
            sequences.append(QKeySequence(Qt.Key.Key_Delete))
        elif alias == "Return":
            sequences.append(QKeySequence(Qt.Key.Key_Return))
        elif alias == "Enter":
            sequences.append(QKeySequence(Qt.Key.Key_Enter))
        else:
            sequences.append(QKeySequence(alias))
    return tuple(sequences)


def shortcut_aliases(shortcut: str) -> tuple[str, ...]:
    """Return equivalent shortcuts that should trigger the same action."""
    normalized = shortcut.strip()
    if not normalized:
        return ()
    aliases = [normalized]
    if normalized == "Delete":
        aliases.append("Backspace")
    elif normalized == "Backspace":
        aliases.append("Delete")
    elif normalized == "Return":
        aliases.append("Enter")
    elif normalized == "Enter":
        aliases.append("Return")
    if sys.platform == "darwin" and normalized == "Delete":
        aliases = ["Backspace", "Delete"]
    return tuple(dict.fromkeys(aliases))
