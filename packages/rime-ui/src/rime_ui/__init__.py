"""UI components for RIME."""

from rime_ui.dialogs.import_dialog import ImportDialog
from rime_ui.dialogs.label_dialog import LabelDialog
from rime_ui.dialogs.preferences_dialog import PreferencesDialog
from rime_ui.dialogs.session_metadata_dialog import SessionMetadataDialog
from rime_ui.dialogs.session_wizard import SessionWizard
from rime_ui.dialogs.violation_dialog import ViolationDialog
from rime_ui.panels.annotation_list import AnnotationListPanel
from rime_ui.widgets.annotation_toolbar import AnnotationToolbar
from rime_ui.widgets.signals import SignalTrackWidget
from rime_ui.windows.main_window import RimeMainWindow

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
