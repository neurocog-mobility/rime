"""UI components for RIME."""

from rime_ui.annotation_list import AnnotationListPanel
from rime_ui.annotation_toolbar import AnnotationToolbar
from rime_ui.import_dialog import ImportDialog
from rime_ui.label_dialog import LabelDialog
from rime_ui.main_window import RimeMainWindow
from rime_ui.preferences_dialog import PreferencesDialog
from rime_ui.session_metadata_dialog import SessionMetadataDialog
from rime_ui.session_wizard import SessionWizard
from rime_ui.signals import SignalTrackWidget
from rime_ui.violation_dialog import ViolationDialog

__all__ = [
    "RimeMainWindow",
    "SignalTrackWidget",
    "AnnotationToolbar",
    "AnnotationListPanel",
    "ImportDialog",
    "SessionWizard",
    "ViolationDialog",
    "LabelDialog",
    "PreferencesDialog",
    "SessionMetadataDialog",
]
