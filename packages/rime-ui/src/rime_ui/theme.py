"""Shared UI theme tokens and styling helpers."""

from __future__ import annotations

from collections.abc import Sequence


SPACE_XS = 4
SPACE_SM = 6
SPACE_MD = 8
SPACE_LG = 12
SPACE_XL = 16

RADIUS_SM = 3
RADIUS_MD = 4
RADIUS_LG = 6

DOCK_MIN_WIDTH = 240
DOCK_DEFAULT_WIDTH = 340
DOCK_CONTENT_MARGIN = 16
PATH_INPUT_MIN_WIDTH = 280

COLOR_VIDEO_BG = "#000000"
COLOR_WINDOW_BG = "#1e1e1e"
COLOR_WINDOW_ALT_BG = "#252526"
COLOR_TIMELINE_ROW_BG = "#2a2a2a"
COLOR_OVERVIEW_BG = "#25282c"
COLOR_SURFACE_BG = "#2d2d2d"
COLOR_PANEL_BG = "#202225"
COLOR_INPUT_BG = "#1e1e1e"
COLOR_BORDER = "#3d3d3d"
COLOR_BORDER_SUBTLE = "#2f3439"
COLOR_TEXT = "#cccccc"
COLOR_TEXT_STRONG = "#ffffff"
COLOR_TEXT_EMPHASIS = "#d8d8d8"
COLOR_TEXT_SOFT = "#b8c0c8"
COLOR_TEXT_MUTED = "#888"
COLOR_TEXT_SUBTLE = "#666"
COLOR_ACCENT = "#0d47a1"
COLOR_ACCENT_HOVER = "#1976d2"
COLOR_ACCENT_ALT = "#35556f"
COLOR_ACCENT_BORDER = "#4d89ad"
COLOR_ACCENT_MUTED = "#4a90d9"
COLOR_BUTTON = "#3d3d3d"
COLOR_BUTTON_HOVER = "#4d4d4d"
COLOR_BUTTON_DISABLED_TEXT = "#777"
COLOR_BUTTON_DISABLED_BORDER = "#2d3136"
COLOR_SIGNAL_BUTTON = "#2d3136"
COLOR_SIGNAL_BUTTON_BORDER = "#3a4046"
COLOR_WARNING_BG = "#36261c"
COLOR_WARNING_BORDER = "#7a4a2a"
COLOR_WARNING_TEXT = "#ffd7b3"
COLOR_WARNING_ACCENT = "#d7ba7d"
COLOR_WARNING_ICON = "#ffb703"
COLOR_LOOP_BG = "#163624"
COLOR_LOOP_BORDER = "#57b073"
COLOR_LOOP_ACCENT = "#7be89b"
COLOR_LOOP_TEXT = "#d7ffe3"
COLOR_PLAYHEAD = "#ff6b57"
COLOR_COMPARISON = "#22c55e"
COLOR_PENDING = "#f59e0b"
COLOR_TRIM_EDGE = "#ff4444"
COLOR_ANCHOR = "#ffee00"
COLOR_CONFIDENCE_WARN = "#b07a00"
COLOR_CONFIDENCE_ERROR = "#d92d20"
COLOR_IRR_POOR = "#7f1d1d"
COLOR_IRR_FAIR = "#92400e"
COLOR_THRESHOLD = "#f5d742"
COLOR_TIME_LABEL = "#9aa3ab"
COLOR_OVERVIEW_VIEWPORT = "#c7ccd1"
COLOR_OVERVIEW_HANDLE = "#dce3ea"
COLOR_OVERVIEW_VIEWPORT_BORDER = "#e5ebf0"
COLOR_CONFLICT_BG = "#3d2800"

SIGNAL_PLOT_COLORS = (
    "#4fc3f7",
    "#81c784",
    "#ffb74d",
    "#f06292",
    "#ba68c8",
    "#4db6ac",
    "#ffd54f",
    "#90caf9",
)


def set_layout_metrics(
    layout, *, margins: int | Sequence[int] = SPACE_MD, spacing: int = SPACE_MD
) -> None:
    """Apply standard margins and spacing to a layout."""
    if isinstance(margins, int):
        left = top = right = bottom = margins
    else:
        left, top, right, bottom = margins
    layout.setContentsMargins(left, top, right, bottom)
    layout.setSpacing(spacing)


def set_zero_margins(layout, *, spacing: int = 0) -> None:
    """Clear layout margins while optionally keeping spacing."""
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)


def muted_text_stylesheet(*, color: str = COLOR_TEXT_MUTED, extra: str = "") -> str:
    rules = [f"color: {color};"]
    if extra:
        rules.append(extra.strip())
    return " ".join(rules)


def emphasis_text_stylesheet(
    *, color: str = COLOR_TEXT_EMPHASIS, weight: int = 600
) -> str:
    return f"font-weight: {weight}; color: {color};"


def section_label_stylesheet() -> str:
    """Small all-caps section header label (pass text in uppercase)."""
    return f"color: {COLOR_TEXT_SUBTLE}; font-size: 10px; font-weight: 600;"


def panel_card_stylesheet(name: str) -> str:
    """Scoped stylesheet for a neutral surface card (use with setObjectName)."""
    return (
        f"#{name} {{ background-color: {COLOR_SURFACE_BG};"
        f" border: 1px solid {COLOR_BORDER};"
        f" border-radius: {RADIUS_LG}px; }}"
    )


def main_window_stylesheet() -> str:
    """Application chrome styling for the main window shell."""
    return f"""
        QMainWindow {{ background-color: {COLOR_WINDOW_BG}; }}
        QMenuBar {{ background-color: {COLOR_SURFACE_BG}; color: {COLOR_TEXT}; padding: {SPACE_XS}px; }}
        QMenuBar::item:selected {{ background-color: {COLOR_BORDER}; }}
        QMenu {{ background-color: {COLOR_SURFACE_BG}; color: {COLOR_TEXT}; border: 1px solid {COLOR_BORDER}; }}
        QMenu::item:selected {{ background-color: {COLOR_ACCENT}; }}
        QSplitter::handle {{ background-color: {COLOR_BORDER}; }}
        QSplitter::handle:horizontal {{ width: {SPACE_XS}px; }}
        QSplitter::handle:vertical {{ height: {SPACE_XS}px; }}
        QMainWindow::separator {{ background-color: {COLOR_BORDER}; width: 3px; height: 3px; }}
        QMainWindow::separator:hover {{ background-color: {COLOR_BUTTON}; }}
    """


def media_controls_stylesheet(*, include_slider: bool = False) -> str:
    """Shared styling for video-player control bars."""
    slider_rules = ""
    if include_slider:
        slider_rules = f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {COLOR_BUTTON};
                border-radius: {RADIUS_SM}px;
            }}
            QSlider::handle:horizontal {{
                background: {COLOR_ACCENT};
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLOR_ACCENT_HOVER};
                border-radius: {RADIUS_SM}px;
            }}
        """
    return f"""
        QWidget#mediaControlsRoot {{
            background-color: {COLOR_SURFACE_BG};
            padding: {SPACE_MD}px;
        }}
        QPushButton#playbackTransportButton {{
            background-color: {COLOR_BUTTON};
            color: {COLOR_TEXT_STRONG};
            border: none;
            padding: {SPACE_MD}px {SPACE_XL}px;
            border-radius: {RADIUS_MD}px;
            min-width: 60px;
            font-weight: 600;
        }}
        QPushButton#playbackTransportButton:hover {{
            background-color: {COLOR_BUTTON_HOVER};
        }}
        QPushButton#playbackTransportButton:pressed {{
            background-color: {COLOR_ACCENT};
        }}
        QWidget#playbackTimeGroup {{
            background-color: {COLOR_WINDOW_BG};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: 2px {SPACE_MD}px;
        }}
        QLabel#playbackCurrentTime {{
            color: {COLOR_TEXT_STRONG};
            font-family: monospace;
            font-weight: 600;
        }}
        QLabel#playbackTimeDivider {{
            color: {COLOR_TEXT_SUBTLE};
            font-family: monospace;
            padding: 0 {SPACE_XS}px;
        }}
        QLabel#playbackDurationTime {{
            color: {COLOR_TEXT_SOFT};
            font-family: monospace;
        }}
        QLabel#playbackBadge {{
            background-color: {COLOR_WINDOW_BG};
            color: {COLOR_TEXT_SOFT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: 4px {SPACE_MD}px;
            font-family: monospace;
            font-weight: 600;
        }}
        QLabel#playbackLoopBadge {{
            background-color: {COLOR_LOOP_BG};
            color: {COLOR_LOOP_TEXT};
            border: 1px solid {COLOR_LOOP_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: 4px {SPACE_MD}px;
            font-family: monospace;
            font-weight: 600;
        }}
        {slider_rules}
        QLabel {{
            color: {COLOR_TEXT};
            font-family: monospace;
        }}
    """


def signal_controls_stylesheet() -> str:
    """Styling for the compact signal panel control strip."""
    return f"""
        QWidget#signalControlsRoot {{
            background-color: {COLOR_PANEL_BG};
            border-top: 1px solid {COLOR_BORDER_SUBTLE};
            border-bottom: 1px solid {COLOR_BORDER_SUBTLE};
        }}
        QWidget#signalControlsNavGroup {{
            background: transparent;
            border: none;
        }}
        QPushButton {{
            background-color: {COLOR_SIGNAL_BUTTON};
            color: {COLOR_TEXT_EMPHASIS};
            border: 1px solid {COLOR_SIGNAL_BUTTON_BORDER};
            border-radius: {RADIUS_SM}px;
            padding: 3px {SPACE_MD}px;
            min-width: 28px;
        }}
        QPushButton:hover:!disabled {{
            border-color: {COLOR_ACCENT_BORDER};
            background-color: {COLOR_BUTTON_HOVER};
        }}
        QPushButton:checked {{
            background-color: {COLOR_ACCENT_ALT};
            border-color: {COLOR_ACCENT_BORDER};
            color: {COLOR_TEXT_STRONG};
        }}
        QPushButton:disabled {{
            background-color: {COLOR_PANEL_BG};
            color: {COLOR_BUTTON_DISABLED_TEXT};
            border-color: {COLOR_BUTTON_DISABLED_BORDER};
        }}
        QLabel {{
            color: {COLOR_TEXT_SOFT};
        }}
    """


def video_overlay_label_stylesheet() -> str:
    """Overlay label styling for video panes."""
    return (
        "QLabel {"
        f"  color: {COLOR_TEXT_STRONG};"
        "  background-color: rgba(0, 0, 0, 140);"
        "  font-size: 11px;"
        "  font-weight: bold;"
        f"  padding: 3px {SPACE_MD}px;"
        f"  border-bottom-right-radius: {RADIUS_MD}px;"
        "}"
    )


def splitter_handle_stylesheet(*, width: int = 3) -> str:
    """Minimal splitter handle styling."""
    return (
        f"QSplitter::handle {{ background-color: {COLOR_BORDER}; width: {width}px; }}"
    )


def label_dialog_stylesheet() -> str:
    """Shared styling for the label-picker dialog."""
    return f"""
        QDialog {{
            background-color: {COLOR_SURFACE_BG};
        }}
        QLabel {{
            color: {COLOR_TEXT};
            font-size: 13px;
            padding: {SPACE_XS}px 0;
        }}
        QFrame#warningFrame {{
            background-color: {COLOR_WARNING_BG};
            border: 1px solid {COLOR_WARNING_BORDER};
            border-radius: {RADIUS_LG}px;
        }}
        QLabel#warningTitle {{
            color: {COLOR_WARNING_TEXT};
            font-weight: 600;
        }}
        QLineEdit {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: {SPACE_MD}px;
        }}
        QLineEdit:focus {{
            border: 1px solid {COLOR_ACCENT};
        }}
        QListWidget {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: {SPACE_XS}px;
        }}
        QListWidget::item {{
            padding: {SPACE_MD}px;
            border-radius: {RADIUS_SM}px;
        }}
        QListWidget::item:selected {{
            background-color: {COLOR_ACCENT};
        }}
        QListWidget::item:hover {{
            background-color: {COLOR_BORDER};
        }}
        QPushButton {{
            background-color: {COLOR_BUTTON};
            color: {COLOR_TEXT_STRONG};
            border: none;
            padding: {SPACE_MD}px {SPACE_XL}px;
            border-radius: {RADIUS_MD}px;
            min-width: 70px;
        }}
        QPushButton:hover {{
            background-color: {COLOR_BUTTON_HOVER};
        }}
        QPushButton:pressed {{
            background-color: {COLOR_ACCENT};
        }}
    """


def app_stylesheet() -> str:
    """Application-wide stylesheet applied to QApplication.

    Covers all widget types that appear in dialogs and panels. The main window
    shell styles (menubar, splitter) are layered on top via main_window_stylesheet().
    Button role variants require setProperty("role", "primary" | "destructive")
    on the button instance at construction time.
    """
    return f"""
        QWidget {{
            background-color: {COLOR_WINDOW_BG};
            color: {COLOR_TEXT};
        }}
        QDialog {{
            background-color: {COLOR_SURFACE_BG};
        }}
        QGroupBox {{
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            margin-top: {SPACE_LG}px;
            padding-top: {SPACE_SM}px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 {SPACE_SM}px;
            color: {COLOR_TEXT_SOFT};
        }}
        QPushButton {{
            background-color: {COLOR_BUTTON};
            color: {COLOR_TEXT_STRONG};
            border: none;
            padding: {SPACE_SM}px {SPACE_LG}px;
            border-radius: {RADIUS_MD}px;
            min-width: 64px;
        }}
        QPushButton:hover:!disabled {{
            background-color: {COLOR_BUTTON_HOVER};
        }}
        QPushButton:pressed {{
            background-color: {COLOR_ACCENT};
        }}
        QPushButton:disabled {{
            background-color: {COLOR_SIGNAL_BUTTON};
            color: {COLOR_BUTTON_DISABLED_TEXT};
            border: 1px solid {COLOR_BUTTON_DISABLED_BORDER};
        }}
        QPushButton[role="primary"] {{
            background-color: {COLOR_ACCENT};
            color: {COLOR_TEXT_STRONG};
            font-weight: 600;
        }}
        QPushButton[role="primary"]:hover:!disabled {{
            background-color: {COLOR_ACCENT_HOVER};
        }}
        QPushButton[role="primary"]:pressed {{
            background-color: {COLOR_ACCENT_HOVER};
        }}
        QPushButton[role="primary"]:disabled {{
            background-color: {COLOR_ACCENT_ALT};
            color: {COLOR_TEXT_SOFT};
            border: none;
        }}
        QPushButton[role="destructive"] {{
            background-color: transparent;
            color: {COLOR_TRIM_EDGE};
            border: 1px solid {COLOR_TRIM_EDGE};
        }}
        QPushButton[role="destructive"]:hover:!disabled {{
            background-color: rgba(255, 68, 68, 0.15);
        }}
        QPushButton[role="destructive"]:pressed {{
            background-color: rgba(255, 68, 68, 0.3);
        }}
        QPushButton[role="remove"] {{
            background-color: transparent;
            color: {COLOR_TRIM_EDGE};
            border: none;
        }}
        QPushButton[role="remove"]:hover:!disabled {{
            background-color: rgba(255, 68, 68, 0.12);
            border-radius: {RADIUS_MD}px;
        }}
        QPushButton[role="remove"]:pressed {{
            background-color: rgba(255, 68, 68, 0.25);
        }}
        QPushButton[role="positive"] {{
            background-color: {COLOR_LOOP_BORDER};
            color: {COLOR_WINDOW_BG};
            font-weight: 600;
            border: none;
        }}
        QPushButton[role="positive"]:hover:!disabled {{
            background-color: {COLOR_LOOP_ACCENT};
        }}
        QPushButton[role="positive"]:pressed {{
            background-color: {COLOR_LOOP_BORDER};
        }}
        QPushButton[role="positive"]:disabled {{
            background-color: {COLOR_SIGNAL_BUTTON};
            color: {COLOR_BUTTON_DISABLED_TEXT};
            border: none;
        }}
        QLineEdit {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: {SPACE_SM}px {SPACE_MD}px;
            selection-background-color: {COLOR_ACCENT};
        }}
        QLineEdit:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QLineEdit:disabled {{
            color: {COLOR_TEXT_MUTED};
            border-color: {COLOR_BUTTON_DISABLED_BORDER};
        }}
        QComboBox {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: {SPACE_SM}px {SPACE_MD}px;
            min-width: 80px;
        }}
        QComboBox:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QComboBox::drop-down {{
            border: none;
            width: {SPACE_XL}px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLOR_SURFACE_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            selection-background-color: {COLOR_ACCENT};
            selection-color: {COLOR_TEXT_STRONG};
            outline: none;
        }}
        QListWidget {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            outline: none;
        }}
        QListWidget::item {{
            padding: {SPACE_SM}px {SPACE_MD}px;
        }}
        QListWidget::item:selected {{
            background-color: {COLOR_ACCENT};
            color: {COLOR_TEXT_STRONG};
        }}
        QListWidget::item:hover:!selected {{
            background-color: {COLOR_BORDER};
        }}
        QTableWidget {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            gridline-color: {COLOR_BORDER};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_SM}px;
        }}
        QTableWidget::item:selected {{
            background-color: {COLOR_ACCENT};
            color: {COLOR_TEXT_STRONG};
        }}
        QHeaderView::section {{
            background-color: {COLOR_SURFACE_BG};
            color: {COLOR_TEXT_SOFT};
            border: none;
            border-bottom: 1px solid {COLOR_BORDER};
            border-right: 1px solid {COLOR_BORDER};
            padding: {SPACE_SM}px {SPACE_MD}px;
        }}
        QScrollBar:vertical {{
            background-color: {COLOR_WINDOW_BG};
            width: 10px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background-color: {COLOR_BUTTON};
            border-radius: 5px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {COLOR_BUTTON_HOVER};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar:horizontal {{
            background-color: {COLOR_WINDOW_BG};
            height: 10px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {COLOR_BUTTON};
            border-radius: 5px;
            min-width: 24px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {COLOR_BUTTON_HOVER};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
        QTabWidget::pane {{
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            background-color: {COLOR_SURFACE_BG};
        }}
        QMainWindow QTabBar {{
            qproperty-expanding: 1;
        }}
        QTabBar::tab {{
            background-color: {COLOR_WINDOW_BG};
            color: {COLOR_TEXT_MUTED};
            border: 1px solid {COLOR_BORDER};
            border-bottom: none;
            padding: {SPACE_SM}px {SPACE_LG}px;
            border-top-left-radius: {RADIUS_SM}px;
            border-top-right-radius: {RADIUS_SM}px;
        }}
        QTabBar::tab:selected {{
            background-color: {COLOR_SURFACE_BG};
            color: {COLOR_TEXT};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {COLOR_BORDER};
            color: {COLOR_TEXT};
        }}
        QCheckBox {{
            color: {COLOR_TEXT};
            spacing: {SPACE_SM}px;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_SM}px;
            background-color: {COLOR_INPUT_BG};
        }}
        QCheckBox::indicator:checked {{
            background-color: {COLOR_ACCENT};
            border-color: {COLOR_ACCENT};
        }}
        QCheckBox::indicator:hover {{
            border-color: {COLOR_ACCENT};
        }}
        QLabel {{
            color: {COLOR_TEXT};
            background-color: transparent;
        }}
        QToolBar {{
            background-color: {COLOR_SURFACE_BG};
            border-bottom: 1px solid {COLOR_BORDER};
            spacing: 2px;
            padding: 2px 4px;
        }}
        QToolBar::separator {{
            background-color: {COLOR_BORDER};
            width: 1px;
            margin: 4px 4px;
        }}
        QToolButton {{
            background-color: transparent;
            border: none;
            border-radius: {RADIUS_MD}px;
            padding: {SPACE_SM}px;
        }}
        QToolButton:hover {{
            background-color: {COLOR_BUTTON};
        }}
        QToolButton:pressed, QToolButton:checked {{
            background-color: {COLOR_ACCENT};
        }}
        QDockWidget {{
            color: {COLOR_TEXT};
            border: 2px solid {COLOR_TEXT_SUBTLE};
        }}
        QDockWidget::title {{
            background-color: {COLOR_SURFACE_BG};
            border-bottom: 2px solid {COLOR_TEXT_SUBTLE};
            padding: {SPACE_MD}px {SPACE_LG}px;
            font-weight: 600;
        }}
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
        QScrollArea > QWidget > QWidget {{
            background-color: transparent;
        }}
        QToolTip {{
            background-color: {COLOR_SURFACE_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            padding: {SPACE_XS}px {SPACE_SM}px;
        }}
        QSpinBox, QDoubleSpinBox {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
            padding: {SPACE_SM}px;
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QTextEdit, QPlainTextEdit {{
            background-color: {COLOR_INPUT_BG};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: {RADIUS_MD}px;
        }}
    """
