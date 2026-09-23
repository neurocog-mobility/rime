"""Native Qt palette and shared tokens for the v0.2 visual polish pass."""

from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QPushButton, QComboBox, QDoubleSpinBox, QLabel

SPACE = (4, 8, 12, 16, 24)
CONTROL_HEIGHT = 30


def section_font(widget, *, prominent=False):
    font = QFont(widget.font())
    font.setPointSizeF(font.pointSizeF() + (4 if prominent else 1))
    font.setWeight(QFont.Weight.DemiBold)
    return font


def polish_surface(editor):
    """Apply the shared workspace hierarchy to a window or task surface."""
    editor.setObjectName("annotationWorkspacePilot")
    for kind in (QPushButton, QComboBox, QDoubleSpinBox):
        for control in editor.findChildren(kind):
            control.setMinimumHeight(max(control.minimumHeight(), CONTROL_HEIGHT))
    dark = editor.palette().color(QPalette.ColorRole.Window).lightness() < 128
    colors = dict(
        surface="#192129" if dark else "#ffffff",
        inset="#11191f" if dark else "#f4f7fa",
        border="#36434e" if dark else "#d2dbe4",
        inner_border="#2b3740" if dark else "#e6ebf0",
        metric="#1c252d" if dark else "#f8fafc",
        text="#edf2f6" if dark else "#1c2a36",
        muted="#b8c4cf" if dark else "#536576",
        button="#26323c" if dark else "#edf2f6",
        hover="#344552" if dark else "#e0eaf3",
        accent="#087ce2" if dark else "#086bc2",
        disabled="#82909c" if dark else "#687785",
    )
    editor.setStyleSheet(f"""
        #annotationWorkspacePilot QFrame[workspaceSection="true"],
        #annotationWorkspacePilot QGroupBox[workspaceSection="true"] {{
            background: {colors["surface"]}; border: 1px solid {colors["border"]};
            border-radius: 8px; margin: 0; padding: 0;
        }}
        #annotationWorkspacePilot QLabel {{ color: {colors["text"]}; background: transparent; }}
        #annotationWorkspacePilot QLabel[role="muted"] {{ color: {colors["muted"]}; }}
        #annotationWorkspacePilot QScrollArea {{ border: none; background: transparent; }}
        #annotationWorkspacePilot #measurementTiles {{ background: transparent; }}
        #annotationWorkspacePilot QPushButton {{
            color: {colors["text"]}; background: {colors["button"]};
            border: 1px solid {colors["inner_border"]}; border-radius: 5px;
            padding: 4px 10px;
        }}
        #annotationWorkspacePilot QPushButton:hover {{ background: {colors["hover"]}; }}
        #annotationWorkspacePilot QPushButton:pressed {{ background: {colors["border"]}; }}
        #annotationWorkspacePilot QPushButton:focus {{ border: 2px solid {colors["accent"]}; }}
        #annotationWorkspacePilot QPushButton[role="primaryAction"],
        #annotationWorkspacePilot QPushButton[role="primary"] {{
            background: {colors["accent"]}; color: white; border-color: {colors["accent"]};
        }}
        #annotationWorkspacePilot QPushButton[role="primaryAction"]:hover {{ background: #168aea; }}
        #annotationWorkspacePilot QPushButton[role="primaryAction"]:pressed {{ background: #075ca5; }}
        #annotationWorkspacePilot QPushButton[role="secondaryAction"] {{ border-color: {colors["accent"]}; }}
        #annotationWorkspacePilot QPushButton:disabled {{
            color: {colors["disabled"]}; background: {colors["inset"]}; border-color: {colors["border"]};
        }}
        #annotationWorkspacePilot QPushButton[role="metric"] {{
            background: {colors["metric"]}; border-color: {colors["inner_border"]};
            padding: 0; text-align: left;
        }}
        #annotationWorkspacePilot QPushButton[role="metric"]:hover {{ border-color: {colors["accent"]}; }}
        #annotationWorkspacePilot QSplitter::handle {{ background: transparent; height: 6px; }}
        #annotationWorkspacePilot QSplitter::handle:hover {{ background: {colors["border"]}; }}
    """)
    for label in editor.findChildren(QLabel):
        if label.property("role") == "section":
            label.setFont(section_font(editor))
        elif label.property("role") == "heading":
            label.setFont(section_font(editor, prominent=True))


def polish_annotation(editor):
    polish_surface(editor)
    for control in (editor.signals.prev_button, editor.signals.next_button):
        control.setFixedWidth(CONTROL_HEIGHT)
    editor.clock.setMinimumWidth(
        editor.clock.fontMetrics().horizontalAdvance("0000.00 / 0000.00 s")
    )
    # Nested splitters can under-allocate a section after shrinking the window.
    # Enforce the contents' actual minimum so signal plots cannot cover playback.
    editor.recordings_panel.layout().activate()
    editor.recordings_panel.setMinimumHeight(editor.recordings_panel.minimumSizeHint().height())


LIGHT = dict(
    window="#eeeeee",
    surface="#ffffff",
    inset="#eeeeee",
    text="#000000",
    muted="#000000",
    accent="#000000",
    on_accent="#ffffff",
    selected="#dddddd",
    border="#aaaaaa",
    control="#555555",
    warning="#000000",
    error="#000000",
)
DARK = LIGHT


def apply_theme(app, mode="system", scale=1.0):
    app.setStyleSheet("")
    palette = app.palette()

    def color(role):
        return palette.color(role).name()

    return dict(
        LIGHT,
        window=color(QPalette.ColorRole.Window),
        surface=color(QPalette.ColorRole.Base),
        text=color(QPalette.ColorRole.Text),
        muted=color(QPalette.ColorRole.Text),
        accent=color(QPalette.ColorRole.Text),
        on_accent=color(QPalette.ColorRole.Base),
        selected=color(QPalette.ColorRole.AlternateBase),
        border=color(QPalette.ColorRole.Mid),
        control=color(QPalette.ColorRole.Text),
        warning=color(QPalette.ColorRole.Text),
    )
