"""Video player widget for RIME."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from rime_ui.theme import (
    COLOR_VIDEO_BG,
    media_controls_stylesheet,
    set_layout_metrics,
    set_zero_margins,
)


# Frame stepping constants
FRAME_DURATION_MS = 33  # ~30fps
SCRUB_STEP_MS = 100  # Mouse wheel step
SPEED_STEPS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]


class VideoPlayer(QWidget):
    """Video player with basic playback controls."""

    # Emitted when position changes via scrubbing (for external sync)
    position_scrubbed = Signal(int)  # position_ms

    def __init__(self) -> None:
        super().__init__()

        self._loop_start_ms = 0
        self._loop_end_ms = 0
        self._loop_active = False
        self._playback_rate = 1.0

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._setup_ui()
        self._setup_player()

    def _setup_ui(self) -> None:
        """Create player UI."""
        layout = QVBoxLayout(self)
        set_zero_margins(layout)

        # Video display
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet(f"background-color: {COLOR_VIDEO_BG};")
        layout.addWidget(self.video_widget, stretch=1)

        # Controls bar
        controls = QWidget()
        controls.setObjectName("mediaControlsRoot")
        controls.setStyleSheet(media_controls_stylesheet(include_slider=True))

        controls_layout = QHBoxLayout(controls)
        set_layout_metrics(controls_layout, spacing=10)

        # Play/Pause button
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
        controls_layout.addWidget(time_group)

        # Seek slider
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.position_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls_layout.addWidget(self.position_slider, stretch=1)

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

        layout.addWidget(controls)

    def _setup_player(self) -> None:
        """Initialize media player."""
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        # Connect signals
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_error)

        self._duration_ms = 0
        self._first_frame_shown = False
        self.set_speed(1.0)

    def load_video(self, path: str) -> None:
        """Load a video file."""
        self._first_frame_shown = False
        self.player.setSource(QUrl.fromLocalFile(path))

    def _toggle_play(self) -> None:
        """Toggle play/pause."""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_position_changed(self, position_ms: int) -> None:
        """Handle video playback position changes."""
        if (
            self._loop_active
            and self._loop_end_ms > self._loop_start_ms
            and position_ms >= self._loop_end_ms
        ):
            self.player.setPosition(self._loop_start_ms)
            return

        if not self.position_slider.isSliderDown():
            if self._duration_ms > 0:
                slider_pos = int((position_ms / self._duration_ms) * 1000)
                self.position_slider.setValue(slider_pos)
        self.position_label.setText(self._format_time(position_ms))

    def _on_duration_changed(self, duration_ms: int) -> None:
        """Update when video duration is known."""
        self._duration_ms = duration_ms
        self.duration_label.setText(self._format_time(duration_ms))
        if self._loop_active and self._loop_end_ms > duration_ms:
            self.clear_loop()

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        """Update play button based on state."""
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸")
        else:
            self.play_btn.setText("▶")

    @staticmethod
    def _format_time(ms: int) -> str:
        """Format milliseconds as MM:SS.mmm."""
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        millis = ms % 1000
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

    def get_position_ms(self) -> int:
        """Get current playback position in milliseconds."""
        return self.player.position()

    def get_duration_ms(self) -> int:
        return self._duration_ms

    def set_position_ms(self, ms: int) -> None:
        """Set playback position in milliseconds."""
        self.player.setPosition(ms)

    def set_loop(self, start_ms: int, end_ms: int) -> None:
        """Enable bounded loop playback."""
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
        """Disable loop playback."""
        self._loop_active = False
        self._update_loop_label()

    def is_loop_active(self) -> bool:
        return self._loop_active

    def set_speed(self, rate: float) -> float:
        """Set playback speed to the nearest supported step."""
        closest = min(SPEED_STEPS, key=lambda value: abs(value - rate))
        self._playback_rate = closest
        self.player.setPlaybackRate(closest)
        self.speed_label.setText(f"{closest:.2g}x")
        return closest

    def get_speed(self) -> float:
        return self._playback_rate

    def speed_up(self) -> float:
        index = SPEED_STEPS.index(self._playback_rate)
        if index < len(SPEED_STEPS) - 1:
            return self.set_speed(SPEED_STEPS[index + 1])
        return self._playback_rate

    def speed_down(self) -> float:
        index = SPEED_STEPS.index(self._playback_rate)
        if index > 0:
            return self.set_speed(SPEED_STEPS[index - 1])
        return self._playback_rate

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Handle media status changes to show first frame."""
        # When media is loaded, play briefly then pause to render the first frame
        if (
            status == QMediaPlayer.MediaStatus.LoadedMedia
            and not self._first_frame_shown
        ):
            self._first_frame_shown = True
            self.player.play()
            # Give Qt time to decode and render a frame, then pause
            QTimer.singleShot(50, self._pause_for_first_frame)

    def _pause_for_first_frame(self) -> None:
        """Pause playback after first frame is rendered."""
        self.player.pause()
        self.player.setPosition(0)

    def _on_slider_moved(self, position: int) -> None:
        """Handle slider movement (0-1000 range)."""
        if self._duration_ms > 0:
            ms = int((position / 1000) * self._duration_ms)
            self.set_position_ms(ms)
            self.position_label.setText(self._format_time(ms))

    def _on_slider_pressed(self) -> None:
        """Handle slider press (pause playback)."""
        self._was_playing = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.player.pause()

    def _on_slider_released(self) -> None:
        """Handle slider release (resume playback if playing)."""
        if getattr(self, "_was_playing", False):
            self.player.play()

    def _on_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        """Handle media player errors."""
        if error != QMediaPlayer.Error.NoError:
            print(f"Video error: {error_string}")

    def _update_loop_label(self) -> None:
        if not self._loop_active:
            self.loop_label.setVisible(False)
            self.loop_label.setText("")
            return
        start = self._loop_start_ms / 1000
        end = self._loop_end_ms / 1000
        self.loop_label.setText(f"ROI: {start:.1f}s - {end:.1f}s")
        self.loop_label.setVisible(True)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel for precision scrubbing."""
        if self._duration_ms <= 0:
            return

        # Determine scroll direction (positive = up/right = forward)
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()

        # Calculate step direction
        step = SCRUB_STEP_MS if delta > 0 else -SCRUB_STEP_MS

        # Apply position change
        current = self.player.position()
        new_pos = max(0, min(self._duration_ms, current + step))
        self.player.setPosition(new_pos)
        self.position_scrubbed.emit(new_pos)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard for frame stepping."""
        if self._duration_ms <= 0:
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        # Frame stepping
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
            current = self.player.position()
            new_pos = max(0, min(self._duration_ms, current + step))
            self.player.setPosition(new_pos)
            self.position_scrubbed.emit(new_pos)
            event.accept()
        else:
            super().keyPressEvent(event)
