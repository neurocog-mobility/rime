"""Shared native desktop layout and control helpers."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QComboBox,
    QFrame,
)


class WorkspaceSection(QFrame):
    """A visible task region with its controls in the section header."""

    def __init__(self, title):
        super().__init__()
        self.setProperty("workspaceSection", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.heading = label(title, "section", wrap=False)
        self.header.addWidget(self.heading)
        layout.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        layout.addLayout(self.body, 1)


class ContentScrollArea(QScrollArea):
    """Prefer the contents' size, with scrolling for larger forms and lists."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def sizeHint(self):
        if self.widget() is None:
            return super().sizeHint()
        size = self.widget().sizeHint()
        screen = self.screen().availableGeometry()
        height = min(size.height(), int(screen.height() * 0.55))
        width = min(size.width(), int(screen.width() * 0.7))
        if height < size.height():
            width += self.verticalScrollBar().sizeHint().width()
        return QSize(width + 2 * self.frameWidth(), height + 2 * self.frameWidth())


def label(text, role="", wrap=True):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if not text:
        widget.hide()
    widget.setProperty("role", role)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def button(text, slot=None, role="", name=""):
    widget = QPushButton(text)
    widget.setProperty("role", role)
    if name:
        widget.setObjectName(name)
    if slot:
        widget.clicked.connect(slot)
    return widget


def column(parent=None, margins=0, spacing=6):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(min(margins, 8), min(margins, 8), min(margins, 8), min(margins, 8))
    layout.setSpacing(spacing)
    return layout


def row(*items):
    layout = QHBoxLayout()
    layout.setSpacing(8)
    for item in items:
        if item is None:
            layout.addStretch()
        else:
            layout.addWidget(item)
    return layout


def combo(items):
    widget = QComboBox()
    widget.addItems(items)
    widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    widget.setMinimumContentsLength(12)
    widget.setToolTip(widget.currentText())
    widget.currentTextChanged.connect(widget.setToolTip)
    return widget


def field(layout, title, widget):
    layout.addWidget(label(title, "muted"))
    layout.addWidget(widget)
    return widget


def scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    return area
