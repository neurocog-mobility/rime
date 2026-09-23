"""Time boundary control shared by annotation and review editors."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox


class BoundarySpinBox(QDoubleSpinBox):
    focused = Signal(float)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit(self.value())
