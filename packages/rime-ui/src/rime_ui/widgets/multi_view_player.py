"""Multi-view video player with side-by-side and single-video display modes."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from rime_core.sessions import VideoConfig
from rime_ui.theme import (
    COLOR_VIDEO_BG,
    media_controls_stylesheet,
    set_layout_metrics,
    set_zero_margins,
    video_overlay_label_stylesheet,
)


# Frame stepping constants
FRAME_DURATION_MS = 33  # ~30fps
SCRUB_STEP_MS = 100  # Mouse wheel step
SPEED_STEPS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]

# Display modes (cycled with V key)
MODE_SIDE_BY_SIDE = "side_by_side"
MODE_PRIMARY_ONLY = "primary_only"
MODE_SECONDARY_ONLY = "secondary_only"
_MODE_CYCLE = [MODE_SIDE_BY_SIDE, MODE_PRIMARY_ONLY, MODE_SECONDARY_ONLY]
_MODE_LABELS = {
    MODE_SIDE_BY_SIDE: "Side-by-Side",
    MODE_PRIMARY_ONLY: "Primary Only",
    MODE_SECONDARY_ONLY: "Secondary Only",
}


def _infer_label(path: str) -> str:
    """Auto-infer a display label from the video filename."""
    name = Path(path).stem.lower()
    if re.search(r"front", name):
        return "Frontal"
    if re.search(r"sag", name):
        return "Sagittal"
    if re.search(r"later", name):
        return "Lateral"
    if re.search(r"top|overhead|bird", name):
        return "Overhead"
    return ""


class _VideoPane(QWidget):
    """A single video display pane with label overlay."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(0)  # muted by default

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet(f"background-color: {COLOR_VIDEO_BG};")
        self.player.setVideoOutput(self.video_widget)

        # Stacked layout: video at back, label overlay on top
        layout = QStackedLayout(self)
        layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        layout.addWidget(self.video_widget)

        # Label overlay
        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.setStyleSheet(video_overlay_label_stylesheet())
        label_container = QWidget()
        label_container.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        label_layout = QVBoxLayout(label_container)
        set_zero_margins(label_layout)
        label_layout.addWidget(
            self._label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        label_layout.addStretch()
        layout.addWidget(label_container)

        self.offset_ms = 0.0
        self._config: VideoConfig | None = None
        self._first_frame_shown = False

        self.player.mediaStatusChanged.connect(self._on_media_status)

    def load(self, config: VideoConfig, base_dir: Path) -> None:
        """Load a video from config."""
        self._config = config
        self.offset_ms = config.offset_ms
        label = config.label or _infer_label(config.path)
        self._label.setText(label)
        self._label.setVisible(bool(label))
        self._first_frame_shown = False

        video_path = base_dir / config.path
        self.player.setSource(QUrl.fromLocalFile(str(video_path)))

    def get_label(self) -> str:
        return self._label.text()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if (
            status == QMediaPlayer.MediaStatus.LoadedMedia
            and not self._first_frame_shown
        ):
            self._first_frame_shown = True
            self.player.play()
            QTimer.singleShot(50, self._pause_first_frame)

    def _pause_first_frame(self) -> None:
        self.player.pause()
        self.player.setPosition(0)


class MultiViewPlayer(QWidget):
    """Multi-view video player with side-by-side and single-video modes.

    The primary pane drives timing while secondary panes play in parallel.
    """

    position_scrubbed = Signal(int)  # position_ms
    position_changed = Signal(int)  # forwarded from primary
    duration_changed = Signal(int)  # forwarded from primary

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._panes: list[_VideoPane] = []
        self._primary_index = 0
        self._display_mode = MODE_SIDE_BY_SIDE

        # Playback state
        self._loop_start_ms = 0
        self._loop_end_ms = 0
        self._loop_active = False
        self._playback_rate = 1.0
        self._duration_ms = 0

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        set_zero_margins(root_layout)

        # Container for video panes (rebuilt on mode change)
        self._video_container = QWidget()
        self._video_container.setStyleSheet(f"background-color: {COLOR_VIDEO_BG};")
        root_layout.addWidget(self._video_container, stretch=1)

        # Controls bar
        controls = QWidget()
        controls.setObjectName("mediaControlsRoot")
        controls.setStyleSheet(media_controls_stylesheet())

        controls_layout = QHBoxLayout(controls)
        set_layout_metrics(controls_layout, spacing=10)

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("playbackTransportButton")
        self.play_btn.clicked.connect(self._toggle_play)
        controls_layout.addWidget(self.play_btn)

        time_group = QWidget(controls)
        time_group.setObjectName("playbackTimeGroup")
        time_layout = QHBoxLayout(time_group)
        set_layout_metrics(time_layout, margins=(10, 4, 10, 4), spacing=0)

        self.position_label = QLabel("00:00.000")
        self.position_label.setObjectName("playbackCurrentTime")
        time_layout.addWidget(self.position_label)

        time_divider = QLabel("/")
        time_divider.setObjectName("playbackTimeDivider")
        time_layout.addWidget(time_divider)

        self.duration_label = QLabel("00:00.000")
        self.duration_label.setObjectName("playbackDurationTime")
        time_layout.addWidget(self.duration_label)
        time_group.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(time_group)

        controls_layout.addStretch(1)

        status_group = QWidget(controls)
        status_layout = QHBoxLayout(status_group)
        set_zero_margins(status_layout, spacing=8)

        self.speed_label = QLabel("1.0x")
        self.speed_label.setObjectName("playbackBadge")
        status_layout.addWidget(self.speed_label)

        self.loop_label = QLabel("")
        self.loop_label.setObjectName("playbackLoopBadge")
        self.loop_label.setVisible(False)
        status_layout.addWidget(self.loop_label)

        controls_layout.addWidget(status_group)

        root_layout.addWidget(controls)

    # ------------------------------------------------------------------
    # Video loading
    # ------------------------------------------------------------------

    def load_videos(self, videos: list[VideoConfig], session_dir: Path) -> None:
        """Load one or more videos. First 'primary' role video drives timing."""
        for pane in self._panes:
            pane.player.stop()
            pane.setParent(None)
            pane.deleteLater()
        self._panes.clear()

        if not videos:
            return

        # Find primary index
        self._primary_index = 0
        for i, v in enumerate(videos):
            if v.role == "primary":
                self._primary_index = i
                break

        # Create panes
        for i, vc in enumerate(videos):
            pane = _VideoPane()
            pane.load(vc, session_dir)
            if i == self._primary_index:
                pane.audio.setVolume(1.0)
            else:
                pane.audio.setVolume(0)
            self._panes.append(pane)

        # Connect primary signals
        primary = self._panes[self._primary_index]
        primary.player.positionChanged.connect(self._on_position_changed)
        primary.player.durationChanged.connect(self._on_duration_changed)
        primary.player.playbackStateChanged.connect(self._on_state_changed)
        primary.player.errorOccurred.connect(self._on_error)

        self._apply_speed_to_all()
        self._rebuild_layout()

    # ------------------------------------------------------------------
    # Display mode: side_by_side / primary_only / secondary_only
    # ------------------------------------------------------------------

    def set_display_mode(self, mode: str) -> None:
        if mode not in _MODE_CYCLE:
            return
        # Skip secondary_only if only one video
        if mode == MODE_SECONDARY_ONLY and len(self._panes) < 2:
            mode = MODE_SIDE_BY_SIDE
        self._display_mode = mode
        self._rebuild_layout()

    def toggle_display_mode(self) -> str:
        """Cycle to the next display mode. Returns the new mode label."""
        if len(self._panes) < 2:
            # Single video — no cycling needed
            return _MODE_LABELS.get(self._display_mode, "")

        try:
            idx = _MODE_CYCLE.index(self._display_mode)
        except ValueError:
            idx = 0
        new_mode = _MODE_CYCLE[(idx + 1) % len(_MODE_CYCLE)]
        self.set_display_mode(new_mode)
        return _MODE_LABELS.get(self._display_mode, "")

    def get_display_mode(self) -> str:
        return self._display_mode

    def get_display_mode_label(self) -> str:
        return _MODE_LABELS.get(self._display_mode, "")

    def _rebuild_layout(self) -> None:
        """Rebuild the video container based on current mode and panes."""
        old_layout = self._video_container.layout()
        if old_layout is not None:
            for pane in self._panes:
                pane.setParent(None)
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget and widget not in self._panes:
                    widget.deleteLater()
            QWidget().setLayout(old_layout)

        if not self._panes:
            new_layout = QVBoxLayout(self._video_container)
            set_zero_margins(new_layout)
            return

        if len(self._panes) == 1 or self._display_mode == MODE_SIDE_BY_SIDE:
            self._build_side_by_side()
        elif self._display_mode == MODE_PRIMARY_ONLY:
            self._build_single(self._primary_index)
        elif self._display_mode == MODE_SECONDARY_ONLY:
            # Show first secondary
            sec_idx = next(
                (i for i in range(len(self._panes)) if i != self._primary_index), 0
            )
            self._build_single(sec_idx)

    def _build_side_by_side(self) -> None:
        layout = QVBoxLayout(self._video_container)
        set_zero_margins(layout)

        if len(self._panes) == 1:
            self._panes[0].setMaximumSize(16777215, 16777215)  # reset constraints
            layout.addWidget(self._panes[0])
            self._panes[0].show()
            return

        splitter = QSplitter(Qt.Orientation.Horizontal)
        # Primary first, then secondaries
        order = [self._primary_index] + [
            i for i in range(len(self._panes)) if i != self._primary_index
        ]
        for idx in order:
            self._panes[idx].setMaximumSize(16777215, 16777215)
            self._panes[idx].setStyleSheet("")
            splitter.addWidget(self._panes[idx])
            self._panes[idx].show()
        splitter.setSizes([1000] * len(self._panes))
        layout.addWidget(splitter)

    def _build_single(self, show_index: int) -> None:
        layout = QVBoxLayout(self._video_container)
        set_zero_margins(layout)

        for i, pane in enumerate(self._panes):
            pane.setMaximumSize(16777215, 16777215)
            pane.setStyleSheet("")
            if i == show_index:
                layout.addWidget(pane)
                pane.show()
            else:
                pane.hide()

    # ------------------------------------------------------------------
    # Synced transport
    # ------------------------------------------------------------------

    @property
    def player(self) -> QMediaPlayer | None:
        """Return the primary QMediaPlayer, or None if no videos loaded."""
        if self._panes:
            return self._panes[self._primary_index].player
        return None

    def _toggle_play(self) -> None:
        if not self._panes:
            return
        primary = self._panes[self._primary_index]
        is_playing = (
            primary.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        if is_playing:
            for pane in self._panes:
                pane.player.pause()
        else:
            # Sync secondaries to primary position before playing
            self._sync_secondaries(primary.player.position())
            for pane in self._panes:
                pane.player.play()

    def set_position_ms(self, ms: int) -> None:
        """Seek all players to position (with offset)."""
        if not self._panes:
            return
        self._panes[self._primary_index].player.setPosition(ms)
        self._sync_secondaries(ms)

    def get_position_ms(self) -> int:
        if not self._panes:
            return 0
        return self._panes[self._primary_index].player.position()

    def get_duration_ms(self) -> int:
        return self._duration_ms

    def _sync_secondaries(self, primary_pos_ms: int) -> None:
        """Sync secondaries — called only on explicit user actions, NOT every frame."""
        for i, pane in enumerate(self._panes):
            if i == self._primary_index:
                continue
            target = int(primary_pos_ms + pane.offset_ms)
            pane.player.setPosition(max(0, target))

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def set_loop(self, start_ms: int, end_ms: int) -> None:
        start = int(max(0, start_ms))
        end = int(max(start + 1, end_ms))
        if self._duration_ms > 0:
            end = min(end, self._duration_ms)
            start = min(start, max(0, end - 1))
        self._loop_start_ms = start
        self._loop_end_ms = end
        self._loop_active = True
        self._update_loop_label()

    def clear_loop(self) -> None:
        self._loop_active = False
        self._update_loop_label()

    def is_loop_active(self) -> bool:
        return self._loop_active

    def _update_loop_label(self) -> None:
        if not self._loop_active:
            self.loop_label.setVisible(False)
            self.loop_label.setText("")
            return
        start = self._loop_start_ms / 1000
        end = self._loop_end_ms / 1000
        self.loop_label.setText(f"ROI: {start:.1f}s - {end:.1f}s")
        self.loop_label.setVisible(True)

    # ------------------------------------------------------------------
    # Speed
    # ------------------------------------------------------------------

    def set_speed(self, rate: float) -> float:
        closest = min(SPEED_STEPS, key=lambda v: abs(v - rate))
        self._playback_rate = closest
        self._apply_speed_to_all()
        self.speed_label.setText(f"{closest:.2g}x")
        return closest

    def get_speed(self) -> float:
        return self._playback_rate

    def speed_up(self) -> float:
        idx = SPEED_STEPS.index(self._playback_rate)
        if idx < len(SPEED_STEPS) - 1:
            return self.set_speed(SPEED_STEPS[idx + 1])
        return self._playback_rate

    def speed_down(self) -> float:
        idx = SPEED_STEPS.index(self._playback_rate)
        if idx > 0:
            return self.set_speed(SPEED_STEPS[idx - 1])
        return self._playback_rate

    def _apply_speed_to_all(self) -> None:
        for pane in self._panes:
            pane.player.setPlaybackRate(self._playback_rate)

    # ------------------------------------------------------------------
    # Primary player callbacks
    # ------------------------------------------------------------------

    def _on_position_changed(self, position_ms: int) -> None:
        # Loop check — on loop boundary, resync everyone
        if (
            self._loop_active
            and self._loop_end_ms > self._loop_start_ms
            and position_ms >= self._loop_end_ms
        ):
            self.set_position_ms(self._loop_start_ms)
            return

        # NOTE: we do NOT call _sync_secondaries here.
        # Secondaries play in parallel at the same rate,
        # staying in sync naturally. Only explicit seeks sync them.

        self.position_label.setText(self._format_time(position_ms))

        # Forward signal
        self.position_changed.emit(position_ms)

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._duration_ms = duration_ms
        self.duration_label.setText(self._format_time(duration_ms))
        if self._loop_active and self._loop_end_ms > duration_ms:
            self.clear_loop()
        self.duration_changed.emit(duration_ms)

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸")
        else:
            self.play_btn.setText("▶")

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            logging.getLogger(__name__).error("Video error: %s", error_string)

    # ------------------------------------------------------------------
    # Wheel / key events
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._duration_ms <= 0:
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        step = SCRUB_STEP_MS if delta > 0 else -SCRUB_STEP_MS
        current = self.get_position_ms()
        new_pos = max(0, min(self._duration_ms, current + step))
        self.set_position_ms(new_pos)
        self.position_scrubbed.emit(new_pos)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._duration_ms <= 0:
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        step = 0
        if key == Qt.Key.Key_Left:
            step = -FRAME_DURATION_MS * (
                10 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1
            )
        elif key == Qt.Key.Key_Right:
            step = FRAME_DURATION_MS * (
                10 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1
            )
        elif key == Qt.Key.Key_Space:
            self._toggle_play()
            event.accept()
            return

        if step != 0:
            current = self.get_position_ms()
            new_pos = max(0, min(self._duration_ms, current + step))
            self.set_position_ms(new_pos)
            self.position_scrubbed.emit(new_pos)
            event.accept()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_time(ms: int) -> str:
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        millis = ms % 1000
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
