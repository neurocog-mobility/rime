"""Signal panel widget for displaying synchronized signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from rime_ui.theme import (
    COLOR_ACCENT_MUTED,
    COLOR_PLAYHEAD,
    COLOR_TEXT,
    COLOR_THRESHOLD,
    COLOR_WINDOW_BG,
    SIGNAL_PLOT_COLORS,
    emphasis_text_stylesheet,
    muted_text_stylesheet,
    set_layout_metrics,
    set_zero_margins,
    signal_controls_stylesheet,
)

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

if TYPE_CHECKING:
    from rime_core.signals import Signal


@dataclass
class _SignalEntry:
    signal: "Signal"
    channels: list[str]

    @property
    def name(self) -> str:
        return self.signal.name


class _SignalDisplaySelectorDialog(QDialog):
    """Choose which signal channels are displayed in the collapsed signal panel."""

    def __init__(self, entries: list[_SignalEntry], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._boxes: dict[tuple[str, str], QCheckBox] = {}
        self.setWindowTitle("Signal Display")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget(scroll)
        container_layout = QVBoxLayout(container)
        set_zero_margins(container_layout, spacing=8)

        for entry in entries:
            if not entry.signal.channels:
                continue
            group = QWidget(container)
            group_layout = QVBoxLayout(group)
            set_zero_margins(group_layout)
            title = QLabel(entry.name, group)
            title.setStyleSheet(emphasis_text_stylesheet())
            group_layout.addWidget(title)
            for channel in entry.signal.channels:
                box = QCheckBox(channel, group)
                box.setChecked(channel in entry.channels)
                self._boxes[(entry.name, channel)] = box
                group_layout.addWidget(box)
            container_layout.addWidget(group)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> dict[str, list[str]]:
        selected: dict[str, list[str]] = {}
        for (signal_name, channel), box in self._boxes.items():
            if box.isChecked():
                selected.setdefault(signal_name, []).append(channel)
        return selected


class SignalTrackWidget(QWidget):
    """
    Read-only signal display that follows the canonical timeline controller.

    Default behavior is a single collapsed plot row showing all configured signal
    channels together. Users can toggle to a one-channel-at-a-time view and cycle
    through visible channels with the embedded control strip.
    """

    display_mode_changed = Signal(bool)  # True = combined, False = single
    display_selection_changed = Signal(dict)  # signal_name -> channels

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[_SignalEntry] = []
        self._plots: list = []
        self._overlays: dict[str, list[pg.LinearRegionItem]] = {}
        self._overlay_data: dict[str, dict] = {}
        self._playhead_lines: list = []
        self._snap_lines: list = []
        self._last_snap_times_ms: list[float] = []
        self._last_position_ms = 0.0
        self._last_x_range: tuple[float, float] | None = None
        self._combined_view = True
        self._single_channel_index = 0
        self._duration_s = 0.5

        self._setup_ui()
        self._refresh_controls()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        set_zero_margins(layout)

        self.controls = QWidget(self)
        self.controls.setObjectName("signalControlsRoot")
        self.controls.setStyleSheet(signal_controls_stylesheet())
        controls_layout = QHBoxLayout(self.controls)
        set_layout_metrics(controls_layout, spacing=6)

        self.combined_toggle = QPushButton("Combined", self.controls)
        self.combined_toggle.setCheckable(True)
        self.combined_toggle.clicked.connect(self._on_combined_toggled)
        self.combined_toggle.setToolTip("Show all configured channels together.")
        controls_layout.addWidget(self.combined_toggle)

        nav_group = QWidget(self.controls)
        nav_group.setObjectName("signalControlsNavGroup")
        nav_layout = QHBoxLayout(nav_group)
        set_zero_margins(nav_layout, spacing=4)

        self.prev_button = QPushButton("◀", nav_group)
        self.prev_button.clicked.connect(lambda: self._advance_signal(-1))
        self.prev_button.setToolTip("Show the previous visible channel.")
        nav_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("▶", nav_group)
        self.next_button.clicked.connect(lambda: self._advance_signal(1))
        self.next_button.setToolTip("Show the next visible channel.")
        nav_layout.addWidget(self.next_button)
        controls_layout.addWidget(nav_group)

        self.current_label = QLabel("No signals", self.controls)
        self.current_label.setMinimumWidth(200)
        controls_layout.addWidget(self.current_label, 1)

        self.selector_button = QPushButton("Display...", self.controls)
        self.selector_button.clicked.connect(self._open_display_selector)
        self.selector_button.setToolTip("Choose which channels are visible in the signal panel.")
        controls_layout.addWidget(self.selector_button)

        layout.addWidget(self.controls)

        if not HAS_PYQTGRAPH:
            label = QLabel("Signal plotting requires pyqtgraph.\npip install pyqtgraph", self)
            label.setStyleSheet(muted_text_stylesheet(extra="padding: 20px;"))
            layout.addWidget(label)
            self.setMinimumHeight(96)
            return

        pg.setConfigOptions(antialias=True, background=COLOR_WINDOW_BG, foreground=COLOR_TEXT)
        self.graphics_widget = pg.GraphicsLayoutWidget()
        self.graphics_widget.setMinimumHeight(96)
        layout.addWidget(self.graphics_widget, 1)
        self.setMinimumHeight(120)

    def set_x_range(self, start_s: float, end_s: float) -> None:
        """Set the visible X-axis range (in seconds)."""
        self._last_x_range = (start_s, end_s)
        if not self._plots:
            return
        self._plots[0].setXRange(start_s, end_s, padding=0)

    def add_overlay(
        self, ann_id: str, start_s: float, end_s: float, color: str = COLOR_ACCENT_MUTED
    ) -> None:
        """Add or update an annotation overlay region on the active signal plot."""
        self._overlay_data[ann_id] = {"start": start_s, "end": end_s, "color": color}
        display_end_s = end_s if end_s > start_s else start_s + 0.02

        if not HAS_PYQTGRAPH or not self._plots:
            return

        c = QColor(color)
        c.setAlpha(42)
        brush = pg.mkBrush(c)
        hover_brush = pg.mkBrush(c.lighter(115))

        if ann_id in self._overlays:
            for region in self._overlays[ann_id]:
                region.setRegion([start_s, display_end_s])
                region.setBrush(brush)
                region.setHoverBrush(hover_brush)
            return

        regions = []
        for plot in self._plots:
            region = pg.LinearRegionItem(
                values=[start_s, display_end_s],
                orientation=pg.LinearRegionItem.Vertical,
                brush=brush,
                movable=False,
            )
            region.setHoverBrush(hover_brush)
            region.setZValue(-5)
            plot.addItem(region)
            regions.append(region)
        self._overlays[ann_id] = regions

    def remove_overlay(self, ann_id: str) -> None:
        """Remove an annotation overlay from the active signal plot."""
        if ann_id in self._overlay_data:
            del self._overlay_data[ann_id]
        if ann_id not in self._overlays:
            return
        regions = self._overlays.pop(ann_id)
        for region in regions:
            for plot in self._plots:
                try:
                    plot.removeItem(region)
                except Exception:
                    pass

    def clear_overlays(self) -> None:
        """Remove all overlays."""
        self._overlay_data.clear()
        for regions in self._overlays.values():
            for region in regions:
                for plot in self._plots:
                    try:
                        plot.removeItem(region)
                    except Exception:
                        pass
        self._overlays.clear()

    def set_combined_view(self, enabled: bool) -> None:
        if self._combined_view == enabled:
            return
        self._combined_view = enabled
        self._refresh_signal_view()
        self.display_mode_changed.emit(self._combined_view)

    def set_display_config(self, entries: list[tuple["Signal", list[str]]]) -> None:
        """Replace the displayed signals using the provided signal/channel pairs."""
        self._entries = [
            _SignalEntry(signal=signal, channels=list(channels))
            for signal, channels in entries
        ]
        visible_channels = self._visible_channels()
        self._single_channel_index = min(self._single_channel_index, max(0, len(visible_channels) - 1))
        self._duration_s = self._compute_duration_s()
        self._refresh_signal_view()

    def set_position(self, time_ms: float) -> None:
        """Update playhead position on the active signal plot."""
        self._last_position_ms = time_ms
        time_s = time_ms / 1000.0
        for line in self._playhead_lines:
            line.setValue(time_s)

    def update_snap_lines(self, times_ms: list[float]) -> None:
        """Update snap point lines on the active signal plot."""
        self._last_snap_times_ms = list(times_ms)
        if not HAS_PYQTGRAPH:
            return
        for line in self._snap_lines:
            for plot in self._plots:
                try:
                    plot.removeItem(line)
                except Exception:
                    pass
        self._snap_lines.clear()
        for t in times_ms:
            time_s = t / 1000.0
            for plot in self._plots:
                line = pg.InfiniteLine(
                    pos=time_s,
                    angle=90,
                    pen=pg.mkPen(COLOR_THRESHOLD, width=1, style=Qt.PenStyle.DotLine),
                )
                line.setZValue(6)
                plot.addItem(line)
                self._snap_lines.append(line)

    def clear(self) -> None:
        """Clear all signals and plots."""
        self._entries.clear()
        self._single_channel_index = 0
        self._last_x_range = None
        self._last_snap_times_ms = []
        self._duration_s = 0.5
        self._clear_plot_items()
        self._refresh_controls()

    def _refresh_signal_view(self) -> None:
        self._clear_plot_items()
        self._refresh_controls()
        visible_channels = self._visible_channels()
        if not HAS_PYQTGRAPH or not visible_channels:
            return

        plot = self.graphics_widget.addPlot(row=0, col=0)
        self._configure_plot(plot)
        self._plots = [plot]

        for line_index, (entry, channel) in enumerate(visible_channels):
            time_s = entry.signal.get_time_ms() / 1000.0
            if channel not in entry.signal.channels:
                continue
            color = SIGNAL_PLOT_COLORS[line_index % len(SIGNAL_PLOT_COLORS)]
            plot.plot(
                time_s,
                entry.signal.get_channel(channel),
                pen=pg.mkPen(color, width=1.2),
            )

        playhead = pg.InfiniteLine(
            pos=self._last_position_ms / 1000.0,
            angle=90,
            pen=pg.mkPen(COLOR_PLAYHEAD, width=2),
        )
        playhead.setZValue(7)
        plot.addItem(playhead)
        self._playhead_lines.append(playhead)

        for ann_id, data in self._overlay_data.copy().items():
            self.add_overlay(ann_id, data["start"], data["end"], data["color"])
        self.update_snap_lines(self._last_snap_times_ms)
        if self._last_x_range is not None:
            self.set_x_range(*self._last_x_range)

    def _configure_plot(self, plot) -> None:
        plot.setMenuEnabled(False)
        plot.hideAxis("left")
        plot.hideAxis("bottom")
        plot.showGrid(x=False, y=False)
        plot.setMouseEnabled(x=False, y=False)
        if hasattr(plot, "hideButtons"):
            plot.hideButtons()
        view_box = plot.getViewBox()
        view_box.setMouseEnabled(x=False, y=False)
        max_range = max(self._duration_s, 0.5)
        view_box.setLimits(xMin=0.0, xMax=max_range, minXRange=min(0.5, max_range), maxXRange=max_range)
        view_box.setDefaultPadding(0.0)
        plot.getAxis("left").setStyle(showValues=False)
        plot.getAxis("bottom").setStyle(showValues=False)

    def _clear_plot_items(self) -> None:
        if HAS_PYQTGRAPH:
            self.graphics_widget.clear()
        self._plots.clear()
        self._playhead_lines.clear()
        self._snap_lines.clear()
        self._overlays.clear()

    def _visible_channels(self) -> list[tuple[_SignalEntry, str]]:
        entries = [entry for entry in self._entries if entry.channels]
        channels = [
            (entry, channel)
            for entry in entries
            for channel in entry.channels
            if channel in entry.signal.channels
        ]
        if self._combined_view:
            return channels
        if not channels:
            return []
        self._single_channel_index = min(self._single_channel_index, len(channels) - 1)
        return [channels[self._single_channel_index]]

    def _refresh_controls(self) -> None:
        entries = [entry for entry in self._entries if entry.channels]
        has_entries = bool(self._entries)
        has_visible_entries = bool(entries)
        visible_channels = self._visible_channels()
        visible_channel_count = len(visible_channels) if self._combined_view else sum(
            len(entry.channels) for entry in entries
        )
        all_visible_channels = [
            (entry, channel)
            for entry in entries
            for channel in entry.channels
            if channel in entry.signal.channels
        ]
        can_toggle_combined = visible_channel_count > 1
        self.combined_toggle.blockSignals(True)
        self.combined_toggle.setChecked(self._combined_view)
        self.combined_toggle.blockSignals(False)
        self.combined_toggle.setEnabled(can_toggle_combined)
        if can_toggle_combined:
            self.combined_toggle.setToolTip("Show all configured channels together.")
        elif has_entries:
            self.combined_toggle.setToolTip(
                "Enable at least two displayed channels to switch between combined and single-channel views."
            )
        else:
            self.combined_toggle.setToolTip("Load signals to enable combined view.")
        self.selector_button.setEnabled(has_entries)
        self.prev_button.setEnabled(has_visible_entries and not self._combined_view and len(all_visible_channels) > 1)
        self.next_button.setEnabled(has_visible_entries and not self._combined_view and len(all_visible_channels) > 1)

        if not has_entries:
            self.current_label.setText("No signals")
            self.current_label.setToolTip("")
            return
        if not entries:
            self.current_label.setText("No displayed signals")
            self.current_label.setToolTip("")
            return
        if self._combined_view:
            self.current_label.setText(f"All signals ({len(all_visible_channels)})")
            self.current_label.setToolTip("")
            return
        self._single_channel_index = min(self._single_channel_index, len(all_visible_channels) - 1)
        current_entry, current_channel = all_visible_channels[self._single_channel_index]
        self.current_label.setText(current_entry.name)
        self.current_label.setToolTip(f"{current_entry.name}: {current_channel}")

    def _advance_signal(self, step: int) -> None:
        visible_channels = [
            (entry, channel)
            for entry in self._entries
            if entry.channels
            for channel in entry.channels
            if channel in entry.signal.channels
        ]
        if self._combined_view or len(visible_channels) <= 1:
            return
        self._single_channel_index = (self._single_channel_index + step) % len(visible_channels)
        self._refresh_signal_view()

    def _on_combined_toggled(self, checked: bool) -> None:
        self.set_combined_view(checked)

    def _open_display_selector(self) -> None:
        if not self._entries:
            return
        dialog = _SignalDisplaySelectorDialog(self._entries, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_channel_selection(dialog.selection())

    def open_display_selector(self) -> None:
        self._open_display_selector()

    def is_combined_view(self) -> bool:
        return self._combined_view

    def _apply_channel_selection(self, selection: dict[str, list[str]]) -> None:
        for entry in self._entries:
            entry.channels = [
                channel
                for channel in entry.signal.channels
                if channel in selection.get(entry.name, [])
            ]
        visible_entries = [entry for entry in self._entries if entry.channels]
        if not visible_entries:
            self._combined_view = True
            self._single_channel_index = 0
        else:
            visible_channel_count = sum(
                1
                for entry in visible_entries
                for channel in entry.channels
                if channel in entry.signal.channels
            )
            self._single_channel_index = min(self._single_channel_index, max(0, visible_channel_count - 1))
        self._refresh_signal_view()
        self.display_selection_changed.emit(
            {
                entry.name: list(entry.channels)
                for entry in self._entries
            }
        )

    def _compute_duration_s(self) -> float:
        durations: list[float] = []
        for entry in self._entries:
            time_ms = entry.signal.get_time_ms()
            if len(time_ms):
                durations.append(float(time_ms[-1]) / 1000.0)
        return max(durations, default=0.5)
