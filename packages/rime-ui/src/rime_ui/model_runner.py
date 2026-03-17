"""Dockable model runner panel."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from rime_core.annotations import AnnotationStore
from rime_core.cmf import CMFPackage
from rime_ui.theme import (
    COLOR_TEXT_EMPHASIS,
    COLOR_LOOP_TEXT,
    DOCK_CONTENT_MARGIN,
    DOCK_MIN_WIDTH,
    emphasis_text_stylesheet,
    muted_text_stylesheet,
    panel_card_stylesheet,
    set_layout_metrics,
    set_zero_margins,
)

try:
    import qtawesome as qta
except ImportError:  # pragma: no cover - fallback for environments without qtawesome
    qta = None


class ModelRunnerPanel(QWidget):
    """List loaded models with per-model actions."""

    load_requested = Signal()
    run_requested = Signal(str)
    settings_requested = Signal(str)
    review_requested = Signal(str)
    unload_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(DOCK_MIN_WIDTH)
        self._cards_layout: QVBoxLayout | None = None
        self._empty_label: QLabel | None = None
        self._scope_label: QLabel | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_layout_metrics(layout, margins=DOCK_CONTENT_MARGIN)

        load_button = QPushButton("Load Model...")
        load_button.clicked.connect(self.load_requested.emit)
        layout.addWidget(load_button)

        self._scope_label = QLabel("Inference scope: full session")
        self._scope_label.setWordWrap(True)
        self._scope_label.setStyleSheet(muted_text_stylesheet())
        layout.addWidget(self._scope_label)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll, 1)

        container = QWidget()
        self._cards_layout = QVBoxLayout(container)
        set_zero_margins(self._cards_layout, spacing=8)
        scroll.setWidget(container)

    def refresh(
        self,
        loaded_models: dict[str, CMFPackage],
        store: AnnotationStore | None,
        time_range: tuple[float, float] | None = None,
    ) -> None:
        if self._cards_layout is None:
            return

        self._update_scope_label(time_range)

        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not loaded_models:
            self._empty_label = QLabel(
                "Load a model to run inference and evaluate predictions against your annotations."
            )
            self._empty_label.setWordWrap(True)
            self._cards_layout.addWidget(self._empty_label)
            self._cards_layout.addStretch(1)
            return

        for model_name in sorted(loaded_models):
            self._cards_layout.addWidget(
                self._build_card(loaded_models[model_name], store)
            )
        self._cards_layout.addStretch(1)

    def _build_card(self, model: CMFPackage, store: AnnotationStore | None) -> QWidget:
        card = QFrame(self)
        card.setObjectName("modelRunnerCard")
        card.setStyleSheet(panel_card_stylesheet("modelRunnerCard"))
        layout = QVBoxLayout(card)
        set_layout_metrics(layout, spacing=6)

        title = QLabel(f"{model.name} v{model.config.version}")
        title.setStyleSheet(emphasis_text_stylesheet())
        layout.addWidget(title)

        action_row = QHBoxLayout()
        set_zero_margins(action_row, spacing=6)

        run_button = QPushButton("Run")
        run_button.setProperty("role", "positive")
        run_button.setToolTip(
            "Run inference on the active ROI if one is set; otherwise run on the full session."
        )
        run_button.clicked.connect(lambda: self.run_requested.emit(model.name))
        action_row.addWidget(run_button, 1)

        settings_button = QPushButton()
        settings_button.setIcon(
            self._icon(
                "mdi6.cog-outline", QStyle.StandardPixmap.SP_FileDialogDetailedView
            )
        )
        settings_button.setFixedSize(28, 28)
        settings_button.setToolTip(f"Open settings for {model.name}.")
        settings_button.clicked.connect(
            lambda: self.settings_requested.emit(model.name)
        )
        action_row.addWidget(settings_button)

        unload_button = QPushButton()
        unload_button.setIcon(
            self._icon("mdi6.close", QStyle.StandardPixmap.SP_TitleBarCloseButton)
        )
        unload_button.setFixedSize(28, 28)
        unload_button.clicked.connect(lambda: self.unload_requested.emit(model.name))
        unload_button.setToolTip(f"Unload {model.name}.")
        action_row.addWidget(unload_button)
        layout.addLayout(action_row)

        predictions, pending = self._counts(model.name, store)
        summary_row = QHBoxLayout()
        set_zero_margins(summary_row, spacing=8)

        summary = QLabel(f"{predictions} predictions · {pending} pending")
        summary.setWordWrap(True)
        summary.setStyleSheet(muted_text_stylesheet())
        summary_row.addWidget(summary, 1)

        review_button = QPushButton("Review")
        review_button.setProperty("role", "primary")
        review_button.setEnabled(pending > 0)
        review_button.clicked.connect(lambda: self.review_requested.emit(model.name))
        review_button.setToolTip(
            "Review pending annotations for this model."
            if pending > 0
            else "No pending annotations to review."
        )
        summary_row.addWidget(review_button)
        layout.addLayout(summary_row)

        return card

    def _update_scope_label(self, time_range: tuple[float, float] | None) -> None:
        if self._scope_label is None:
            return
        if time_range is None:
            self._scope_label.setText("Inference scope: full session")
            self._scope_label.setStyleSheet(muted_text_stylesheet())
            return

        start_ms, end_ms = time_range
        scope_text = (
            "Inference scope: ROI only "
            f"({self._format_seconds(start_ms)}s - {self._format_seconds(end_ms)}s)"
        )
        self._scope_label.setText(scope_text)
        self._scope_label.setStyleSheet(emphasis_text_stylesheet(color=COLOR_LOOP_TEXT))

    @staticmethod
    def _format_seconds(value_ms: float) -> str:
        return f"{value_ms / 1000:.1f}"

    @staticmethod
    def _counts(model_name: str, store: AnnotationStore | None) -> tuple[int, int]:
        if store is None:
            return 0, 0
        source = f"model:{model_name}"
        annotations = [
            annotation for annotation in store.all() if annotation.source == source
        ]
        pending = sum(1 for annotation in annotations if annotation.ghost)
        return len(annotations), pending

    def _icon(self, icon_name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        if qta is not None:
            try:
                return qta.icon(icon_name, color=COLOR_TEXT_EMPHASIS)
            except Exception:
                pass
        return self.style().standardIcon(fallback)
