"""Real annotation workspace on the shared evidence timeline."""

from dataclasses import replace
from pathlib import Path
import uuid

from PySide6.QtCore import Qt, Signal, QPoint, QTimer, QEvent, QSignalBlocker
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSplitter,
    QScrollArea,
    QDialog,
    QFormLayout,
    QComboBox,
    QDoubleSpinBox,
    QDialogButtonBox,
    QMessageBox,
    QCheckBox,
    QLineEdit,
    QPlainTextEdit,
    QFrame,
    QSizePolicy,
    QMenu,
    QStyle,
)
from PySide6.QtMultimedia import QMediaPlayer
from rime_core.annotations import Annotation
from rime_core.records import VideoSource, SignalSource
from rime_core.loaders import SignalLoaderRegistry
from rime_ui.timeline import AnnotationLanes
from rime_ui.widgets.multi_view_player import MultiViewPlayer, SPEED_STEPS
from rime_ui.widgets.signals import SignalTrackWidget
from .overview import OverviewStrip
from .boundary_editor import BoundarySpinBox
from .live_measurements import LiveMeasurements
from .suggestions import SuggestionFlow
from rime_core.suggestions import pending, assist
from .style import SPACE, polish_annotation, section_font
from .components import WorkspaceSection, ContentScrollArea


class AnnotationEditor(QWidget):
    changed = Signal()

    def __init__(self, workspace, parent=None, *, timeline_class=AnnotationLanes, review=False):
        super().__init__(parent)
        self.workspace = workspace
        self.visual_pilot = True
        self.review = review
        self.duration = 1.0
        self.loaded_signals = {}
        self._resumed = False
        self._annotation_size_manual = False
        # Load before replacing the open workspace: a failure must be non-destructive.
        for source in workspace.data["sources"]:
            if not Path(source["path"]).is_file():
                raise ValueError(f"Source not found: {source['path']}")
            if source["kind"] == "signal":
                config = SignalSource(**source["config"])
                signal = SignalLoaderRegistry.default().load(Path(source["path"]), config)
                signal.source_id = config.id
                signal.offset_ms = config.offset_ms
                self.loaded_signals[config.id] = signal
        root = QVBoxLayout(self)
        if self.visual_pilot:
            root.setContentsMargins(SPACE[3], SPACE[1], SPACE[3], SPACE[1])
            root.setSpacing(SPACE[1])
        self.measurements = LiveMeasurements(self)
        if not self.visual_pilot:
            root.addWidget(self.measurements)
        self.changed.connect(self.measurements.refresh)
        top = QHBoxLayout()
        model = QPushButton("Run model…")
        self.run_model_button = model
        if self.visual_pilot:
            identity = QVBoxLayout()
            identity.setSpacing(SPACE[0])
            self.workspace_title = QLabel()
            self.workspace_title.setTextFormat(Qt.TextFormat.PlainText)
            self.workspace_title.installEventFilter(self)
            self.workspace_title.setFont(section_font(self, prominent=True))
            self.workspace_title.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            self.workspace_context = QLabel()
            self.workspace_context.setTextFormat(Qt.TextFormat.PlainText)
            self.workspace_context.installEventFilter(self)
            self.workspace_context.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            identity.addWidget(self.workspace_title)
            identity.addWidget(self.workspace_context)
            top.addLayout(identity, 1)
        else:
            top.addWidget(model)
        if not self.visual_pilot:
            top.addStretch()
        for title, slot in (("Alignment…", self.sources), ("Details…", self.details)):
            if self.visual_pilot and title == "Alignment…":
                continue
            b = QPushButton(title)
            b.clicked.connect(slot)
            top.addWidget(b)
        root.addLayout(top)
        if self.visual_pilot:
            self.recordings_panel = WorkspaceSection("Recordings & signals")
            self.annotations_panel = WorkspaceSection("Annotations")
            self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
            self.workspace_splitter.setChildrenCollapsible(False)
            self.workspace_splitter.addWidget(self.recordings_panel)
            self.workspace_splitter.addWidget(self.annotations_panel)
            self.workspace_splitter.setStretchFactor(0, 3)
            self.workspace_splitter.setStretchFactor(1, 2)
            self.workspace_splitter.setSizes([360, 240])
            self.workspace_splitter.splitterMoved.connect(self.annotation_panel_resized)
            root.addWidget(self.workspace_splitter, 1)
            self.alignment_status = QLabel()
            self.alignment_status.setProperty("role", "muted")
            self.alignment_status.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            self.recordings_panel.header.addStretch()
            self.recordings_panel.header.addWidget(self.alignment_status, 1)
            alignment = QPushButton("Alignment…")
            alignment.clicked.connect(self.sources)
            self.recordings_panel.header.addWidget(alignment)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.evidence_splitter = splitter
        splitter.setChildrenCollapsible(False)
        self.player = MultiViewPlayer()
        self.play_shortcut = QShortcut(QKeySequence("Space"), self)
        self.play_shortcut.activated.connect(self.player._toggle_play)
        controls = self.player.findChild(QWidget, "mediaControlsRoot")
        if controls:
            controls.hide()
        self.player.setMinimumHeight(100 if self.visual_pilot else 220)
        splitter.addWidget(self.player)
        self.signals = SignalTrackWidget(native_palette=self.visual_pilot)
        splitter.addWidget(self.signals)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 140])
        self.signals.setVisible(bool(self.loaded_signals))
        # Native macOS splitter sizing can otherwise allocate less than the
        # video widget's explicit minimum and let it cover the signal toolbar.
        splitter.setMinimumHeight(
            self.player.minimumHeight()
            + (self.signals.minimumHeight() + splitter.handleWidth() if self.loaded_signals else 0)
        )
        (self.recordings_panel.body if self.visual_pilot else root).addWidget(splitter, 1)
        bar = QHBoxLayout()
        self.play = QPushButton("Play / Pause")
        self.play.clicked.connect(self.player._toggle_play)
        bar.addWidget(self.play)
        self.speed = QLabel("1×")
        if not self.visual_pilot:
            bar.addWidget(self.speed)
        self.clock = QLabel("0.00 / 0.00 s")
        bar.addWidget(self.clock)
        if not self.visual_pilot:
            bar.addStretch()
        if self.visual_pilot:
            self.speed_choice = QComboBox()
            self.speed_choice.setAccessibleName("Playback speed")
            for rate in SPEED_STEPS:
                self.speed_choice.addItem(f"{rate:g}×", rate)
            self.speed_choice.setCurrentIndex(SPEED_STEPS.index(1.0))
            self.speed_choice.currentIndexChanged.connect(
                lambda: self.player.set_speed(self.speed_choice.currentData())
            )
            bar.insertWidget(2, self.speed_choice)
            self.view_button = QPushButton("View")
            self.view_menu = QMenu(self.view_button)
            self.view_menu.aboutToShow.connect(self.populate_view_menu)
            self.view_button.setMenu(self.view_menu)
            bar.addWidget(self.view_button)
            bar.addStretch()
        (self.recordings_panel.body if self.visual_pilot else root).addLayout(bar)
        self.overview = OverviewStrip(embedded=self.visual_pilot)
        self.overview.native_palette = self.visual_pilot
        if not self.visual_pilot:
            root.addWidget(self.overview)
        tools = self.annotations_panel.header if self.visual_pilot else QHBoxLayout()
        for title, slot in (
            ("Edit", self.edit),
            ("Add interval…", self.add_annotation_menu),
            ("Cut", self.cut),
            ("Delete", self.delete),
            ("Add snap point", self.mark),
        ):
            if (self.visual_pilot and title == "Add snap point") or (
                not self.visual_pilot and title == "Add interval…"
            ):
                continue
            b = QPushButton(title)
            b.clicked.connect(slot)
            b.setVisible(not review or title == "Add snap point")
            tools.addWidget(b)
            if title == "Add interval…":
                self.add_button = b
                b.setToolTip("Choose a lane and enter boundaries, or drag on an empty part of a lane.")
        self.magnet = QCheckBox("Magnet")
        self.magnet.setChecked(True)
        self.magnet.toggled.connect(
            lambda value: self.lanes.set_snap_tolerance_ms(500 if value else 0)
        )
        tools.addWidget(self.magnet)
        self.loop = QCheckBox("Loop ROI")
        self.loop.toggled.connect(self.set_loop)
        if not self.visual_pilot:
            tools.addWidget(self.loop)
        if self.visual_pilot:
            tools.addStretch()
            more = QPushButton("Tools")
            more.setObjectName("annotationTools")
            menu = QMenu(more)
            menu.addAction("Add snap point at playhead", self.mark)
            menu.addAction("Zoom to full recording", lambda: self.view_range(0, self.duration))
            loop_action = menu.addAction("Loop selected region")
            loop_action.setCheckable(True)
            loop_action.toggled.connect(self.loop.setChecked)
            self.loop.toggled.connect(loop_action.setChecked)
            more.setMenu(menu)
            tools.addWidget(more)
            model.setProperty("role", "secondaryAction")
            tools.addWidget(model)
        for title, slot in (
            ("Speed −", lambda: self.change_speed(-1)),
            ("Speed +", lambda: self.change_speed(1)),
            ("Zoom fit", lambda: self.view_range(0, self.duration)),
            ("Toggle view", self.player.toggle_display_mode),
        ):
            if self.visual_pilot:
                continue
            b = QPushButton(title)
            b.clicked.connect(slot)
            tools.addWidget(b)
        if not self.visual_pilot:
            root.addLayout(tools)
        self.lanes = timeline_class(workspace.schema, single_set=True)
        self.lanes.native_palette = self.visual_pilot
        if self.visual_pilot:
            self.lanes.embed_overview(self.overview)
        self.lanes.installEventFilter(self)
        self.lanes.set_schema(workspace.schema)
        self.lanes.set_store(workspace.store)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.lanes)
        area.setMinimumHeight(100 if self.visual_pilot else 160)
        if self.visual_pilot:
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.annotation_area = area
        if self.visual_pilot:
            self.lanes.content_height_changed.connect(
                lambda: QTimer.singleShot(0, self, self.fit_annotation_area)
            )
        (self.annotations_panel.body if self.visual_pilot else root).addWidget(area, 1)
        self.lanes.annotation_created.connect(self.create)
        self.lanes.annotation_modified.connect(self.modify)
        self.lanes.annotation_deleted.connect(self.delete_id)
        self.lanes.annotation_selected.connect(self.seek_annotation)
        self.lanes.position_clicked.connect(self.seek)
        self.lanes.loop_region_changed.connect(self.region)
        self.lanes.view_range_changed.connect(self.view_range)
        self.lanes.snap_point_added.connect(self.snaps_changed)
        self.lanes.snap_point_removed.connect(self.snaps_changed)
        self.lanes.snap_point_modified.connect(self.snaps_changed)
        self.overview.position_selected.connect(self.seek)
        self.overview.view_range_changed.connect(self.view_range)
        self.player.position_changed.connect(self.position)
        self.player.duration_changed.connect(self.set_duration)
        self.signals.display_selection_changed.connect(self.channels_changed)
        videos = [
            VideoSource(**s["config"]) for s in workspace.data["sources"] if s["kind"] == "video"
        ]
        self.player.load_videos(
            videos, {s["config"]["id"]: s["path"] for s in workspace.data["sources"]}
        )
        if self.visual_pilot:
            primary = self.player._panes[self.player._primary_index].player
            primary.playbackStateChanged.connect(self.playback_state)
            self.playback_state(primary.playbackState())
        for pane in self.player._panes:
            pane.player.errorOccurred.connect(lambda error, detail: self.error(detail))
        self.suggestions = SuggestionFlow(self, model, root)
        if self.visual_pilot:
            root.removeWidget(self.suggestions.strip)
            self.annotations_panel.body.addWidget(self.suggestions.strip)
            root.addWidget(self.measurements)
            polish_annotation(self)
            self.signals.ensurePolished()
            self.signals.setMinimumHeight(self.signals.minimumSizeHint().height())
            splitter.setMinimumHeight(
                self.player.minimumHeight()
                + (
                    self.signals.minimumHeight() + splitter.handleWidth()
                    if self.loaded_signals
                    else 0
                )
            )
        self.refresh()
        self.lanes.blockSignals(True)
        self.lanes.set_snap_points(workspace.data["view"].get("snap_points", []))
        self.lanes.blockSignals(False)

    def error(self, text):
        QMessageBox.warning(self, "Workspace", str(text))

    def playback_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.setText("Pause" if playing else "Play")
        self.play.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaPause
                if playing
                else QStyle.StandardPixmap.SP_MediaPlay
            )
        )
        self.play.setProperty("role", "primaryAction")

    def populate_view_menu(self):
        self.view_menu.clear()
        self.view_menu.addAction("Toggle video layout", self.player.toggle_display_mode)
        self.view_menu.addSeparator()
        channels = self.view_menu.addAction(
            "Choose signal channels…", self.signals._open_display_selector
        )
        channels.setEnabled(bool(self.loaded_signals))
        combined = self.view_menu.addAction("Show all signal channels together")
        combined.setCheckable(True)
        combined.setChecked(self.signals._combined_view)
        combined.setEnabled(self.signals.combined_toggle.isEnabled())
        combined.toggled.connect(self.signals.set_combined_view)
        for title, direction, control in (
            ("Previous signal channel", -1, self.signals.prev_button),
            ("Next signal channel", 1, self.signals.next_button),
        ):
            action = self.view_menu.addAction(
                title,
                lambda checked=False, direction=direction: self.signals._advance_signal(direction),
            )
            action.setEnabled(control.isEnabled())

    def mutate(self, function):
        try:
            function()
        except Exception as exc:
            self.error(exc)
        self.refresh()
        self.changed.emit()

    def refresh(self):
        if self.visual_pilot:
            self.refresh_identity()
            self.add_button.setText(
                "Add annotation…" if any(lane.lane_type == "point" for lane in self.workspace.schema.lanes)
                else "Add interval…"
            )
            self.add_button.setEnabled(bool(self.workspace.schema.lanes))
        schema = self.workspace.schema
        if self.lanes.schema.to_dict() != schema.to_dict():
            self.lanes.set_schema(schema)
        self.measurements.refresh()
        selected = self.lanes.get_selected_id()
        store = self.workspace.store
        for _, item in pending(self.workspace.data):
            store.add(
                replace(
                    Annotation(**item.get("draft", item["annotation"])),
                    ghost=True,
                    source="suggestions",
                )
            )
        self.lanes.set_store(store)
        self.suggestions.refresh()
        if selected:
            with QSignalBlocker(self.lanes):
                self.lanes.select_annotation(selected)
        self.overview.set_annotations(self.workspace.store.all())
        channels = self.workspace.data["view"].get("channels", {})
        entries = []
        for source in self.workspace.data["sources"]:
            config = source["config"]
            if source["kind"] == "signal":
                signal = self.loaded_signals[config["id"]]
                signal.offset_ms = config["offset_ms"]
                entries.append((signal, channels.get(config["id"], signal.channels[:1])))
            else:
                for pane in self.player._panes:
                    if pane._config.id == config["id"]:
                        pane.offset_ms = config["offset_ms"]
        self.signals.blockSignals(True)
        self.signals.set_display_config(entries)
        self.signals.blockSignals(False)
        QTimer.singleShot(0, self, self.align_tracks)
        self.view_range(*self.lanes.get_view_range())
        self.player.set_position_ms(self.player.get_position_ms())
        if self.visual_pilot:
            QTimer.singleShot(0, self, self.fit_annotation_area)

    def eventFilter(self, watched, event):
        if (
            self.visual_pilot
            and event.type() == QEvent.Type.Resize
            and watched
            in (getattr(self, "workspace_title", None), getattr(self, "workspace_context", None))
        ):
            QTimer.singleShot(0, self, self.refresh_identity)
        if watched is getattr(self, "lanes", None) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            QTimer.singleShot(0, self, self.align_tracks)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.visual_pilot and hasattr(self, "workspace_title"):
            self.refresh_identity()
            QTimer.singleShot(0, self, self.fit_annotation_area)
        QTimer.singleShot(0, self, self.align_tracks)

    def showEvent(self, event):
        super().showEvent(event)
        if self.visual_pilot:
            QTimer.singleShot(0, self, lambda: polish_annotation(self))
            QTimer.singleShot(0, self, self.fit_annotation_area)

    def annotation_panel_resized(self, *_):
        self._annotation_size_manual = True

    def fit_annotation_area(self):
        """Fit visible tracks, preserving evidence space and any manual split."""
        if self._annotation_size_manual or not hasattr(self, "annotation_area"):
            return
        total = sum(self.workspace_splitter.sizes())
        self.annotations_panel.layout().activate()
        minimum = self.annotations_panel.minimumSizeHint().height()
        desired = minimum + max(0, self.lanes.minimumHeight() - self.annotation_area.minimumHeight())
        desired = max(minimum, min(desired, total // 2))
        desired = min(desired, total - self.recordings_panel.minimumHeight())
        if desired > 0:
            self.workspace_splitter.setSizes([total - desired, desired])

    def refresh_identity(self):
        for label, text in (
            (self.workspace_title, self.workspace.data["name"]),
            (
                self.workspace_context,
                f"{'Review' if self.review else 'Annotation'} workspace · Protocol: {self.workspace.schema.name}",
            ),
        ):
            label.setText(
                label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, label.width())
            )
            label.setToolTip(text)
        if hasattr(self, "alignment_status"):
            sources = self.workspace.data["sources"]
            offsets = [
                f"{s['config'].get('label') or s['config'].get('name') or 'Signal'} {s['config']['offset_ms'] / 1000:+g} s"
                for s in sources[1:]
            ]
            text = " · ".join(offsets) if offsets else "Video 1 is the time reference"
            self.alignment_status.setText(
                self.alignment_status.fontMetrics().elidedText(
                    text, Qt.TextElideMode.ElideRight, self.alignment_status.width()
                )
            )
            self.alignment_status.setToolTip(
                text + "\nDeclared offsets; alignment is not automatically verified."
            )

    def align_tracks(self):
        graphics = getattr(self.signals, "graphics_widget", None)
        if graphics is None or not hasattr(self, "lanes"):
            return
        lane_origin = self.lanes.mapTo(self, QPoint(0, 0)).x()
        if self.visual_pilot:
            gutter = lane_origin + self.lanes._label_width - self.signals.mapTo(self, QPoint(0, 0)).x()
            if self.signals.controls.width() != gutter:
                self.signals.controls.setFixedWidth(max(0, gutter))
                self.signals.layout().activate()
        origin = graphics.mapTo(self, QPoint(0, 0)).x()
        left = lane_origin + self.lanes._label_width - origin
        right = graphics.width() - (lane_origin + self.lanes.width() - origin)
        inset = 0 if self.visual_pilot else 1
        graphics.ci.layout.setContentsMargins(max(0, left - inset), 0, max(0, right - inset), 0)
        if self.visual_pilot:
            self.signals.set_time_guides(self.lanes.time_ticks())

    def set_duration(self, duration):
        if duration <= 0:
            return
        self.duration = float(duration)
        self.measurements.duration_ms = self.duration
        self.measurements.refresh()
        self.lanes.set_duration(duration)
        self.overview.set_duration(duration)
        self.view_range(0, duration)
        if not self._resumed:
            self._resumed = True
            QTimer.singleShot(
                150, self, lambda: self.seek(self.workspace.data["view"].get("position_ms", 0))
            )

    def view_range(self, start, end):
        self.lanes.blockSignals(True)
        self.lanes.set_view_range(start, end)
        self.lanes.blockSignals(False)
        self.overview.set_view_range(start, end)
        for plot in self.signals._plots:
            plot.getViewBox().setLimits(
                xMin=0,
                xMax=self.duration / 1000,
                minXRange=min(0.5, self.duration / 1000),
                maxXRange=self.duration / 1000,
            )
        self.signals.set_x_range(start / 1000, end / 1000)
        if self.visual_pilot:
            self.signals.set_time_guides(self.lanes.time_ticks())

    def seek(self, milliseconds):
        value = max(0, min(self.duration, milliseconds))
        self.player.set_position_ms(int(value))
        self.position(value)

    def position(self, milliseconds):
        self.clock.setText(f"{milliseconds / 1000:.2f} / {self.duration / 1000:.2f} s")
        self.lanes.set_position(milliseconds)
        self.overview.set_position(milliseconds)
        self.signals.set_position(milliseconds)

    def seek_annotation(self, identifier):
        annotation = self.workspace.store.get(identifier)
        if annotation is None:
            item = next(
                (
                    item
                    for _, item in pending(self.workspace.data)
                    if item["annotation"]["id"] == identifier
                ),
                None,
            )
            if item is not None:
                annotation = Annotation(**item.get("draft", item["annotation"]))
        if annotation is not None:
            self.seek(annotation.start_ms)

    def change_speed(self, direction):
        rate = self.player.speed_up() if direction > 0 else self.player.speed_down()
        self.speed.setText(f"{rate:g}×")
        if self.visual_pilot:
            with QSignalBlocker(self.speed_choice):
                self.speed_choice.setCurrentIndex(self.speed_choice.findData(rate))

    def region(self, start, end):
        self.overview.set_loop_region(start, end)
        if self.loop.isChecked():
            self.player.set_loop(int(start), int(end))

    def set_loop(self, enabled):
        region = self.lanes.get_loop_region()
        selected = self.lanes.get_selected_id() or self.suggestions.selected
        proposal = next(
            (
                item.get("draft", item["annotation"])
                for _, item in pending(self.workspace.data)
                if item["annotation"]["id"] == selected
            ),
            None,
        )
        if enabled and proposal and proposal["end_ms"] > proposal["start_ms"]:
            region = (proposal["start_ms"], proposal["end_ms"])
            self.lanes.set_loop_region(*region)
        if enabled and not region:
            annotation = self.workspace.store.get(self.lanes.get_selected_id())
            if annotation:
                region = (annotation.start_ms, annotation.end_ms)
                self.lanes.set_loop_region(*region)
        if enabled and region:
            self.region(*region)
        else:
            self.player.clear_loop()
            self.lanes.clear_loop_region()
            self.overview.clear_loop_region()
            if enabled:
                self.loop.setChecked(False)

    def mark(self):
        self.lanes.add_snap_point(self.player.get_position_ms())
        self.snaps_changed()

    def snaps_changed(self, *_):
        points = self.lanes.get_snap_points()
        self.workspace.data["view"]["snap_points"] = points
        self.signals.update_snap_lines(points)
        self.changed.emit()

    def channels_changed(self, selection):
        self.workspace.data["view"]["channels"] = selection
        self.changed.emit()

    def create(self, level, start, end):
        lane = self.workspace.schema.get_lane_by_level(level)
        if lane:
            self.annotation_dialog(
                Annotation(
                    uuid.uuid4().hex,
                    lane.name,
                    lane.labels[0],
                    start,
                    start if lane.lane_type == "point" else end,
                    event_type=lane.lane_type,
                )
            )

    def add_annotation_menu(self):
        menu = QMenu(self.add_button)
        for lane in self.workspace.schema.lanes:
            menu.addAction(
                lane.name + (" (point)" if lane.lane_type == "point" else ""),
                lambda checked=False, level=lane.level: self.add_at_playhead(level),
            )
        menu.exec(self.add_button.mapToGlobal(QPoint(0, self.add_button.height())))
        menu.deleteLater()

    def add_at_playhead(self, level):
        start = min(self.duration, max(0, self.player.get_position_ms()))
        if self.workspace.schema.get_lane_by_level(level).lane_type != "point" and start == self.duration:
            start = max(0, self.duration - 1000)
        end = min(self.duration, start + 1000)
        self.create(level, start, end)

    def edit(self):
        annotation = self.workspace.store.get(self.lanes.get_selected_id())
        if annotation:
            self.annotation_dialog(annotation)

    def annotation_dialog(self, annotation, commit=None):
        dialog = QDialog(self)
        dialog.setWindowTitle(annotation.lane)
        form = QFormLayout(dialog)
        label = QComboBox()
        label.addItems(self.workspace.schema.get_lane(annotation.lane).labels)
        label.setCurrentText(annotation.label)
        form.addRow("Label", label)
        spins = []
        for title, value in (("Start", annotation.start_ms), ("End", annotation.end_ms)):
            spin = BoundarySpinBox()
            spin.setRange(0, self.duration / 1000)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setValue(value / 1000)
            spin.valueChanged.connect(lambda seconds: self.seek(seconds * 1000))
            spin.focused.connect(lambda seconds: self.seek(seconds * 1000))
            form.addRow(title, spin)
            spins.append(spin)
        spins[1].setEnabled(annotation.event_type != "point")
        if commit:

            def preview_boundary():
                store = self.workspace.store
                for _, item in pending(self.workspace.data):
                    ghost = replace(
                        Annotation(**item.get("draft", item["annotation"])),
                        ghost=True,
                        source="suggestions",
                    )
                    if ghost.id == annotation.id:
                        ghost = replace(
                            ghost,
                            start_ms=spins[0].value() * 1000,
                            end_ms=(spins[0] if ghost.event_type == "point" else spins[1]).value()
                            * 1000,
                            label=label.currentText(),
                        )
                    store.add(ghost)
                self.lanes.set_store(store)
                with QSignalBlocker(self.lanes):
                    self.lanes.select_annotation(annotation.id)

            for spin in spins:
                spin.valueChanged.connect(preview_boundary)
            label.currentTextChanged.connect(preview_boundary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        form.addRow(buttons)

        def accept():
            updated = replace(
                annotation,
                label=label.currentText(),
                start_ms=spins[0].value() * 1000,
                end_ms=spins[0].value() * 1000
                if annotation.event_type == "point"
                else spins[1].value() * 1000,
            )
            try:
                if commit:
                    commit(updated)
                else:
                    created = self.workspace.store.get(updated.id) is None
                    self.workspace.put_annotation(updated)
                    if created:
                        messages = assist(self.workspace, updated)
                        if messages:
                            self.error("\n".join(dict.fromkeys(messages)))
            except ValueError as exc:
                self.error(exc)
                return
            dialog.accept()
            self.refresh()
            self.changed.emit()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()
        self.refresh()

    def modify(self, identifier, start, end):
        annotation = self.workspace.store.get(identifier)
        if annotation:
            self.mutate(
                lambda: self.workspace.put_annotation(
                    replace(annotation, start_ms=start, end_ms=end)
                )
            )

    def delete(self):
        identifier = self.lanes.get_selected_id()
        if identifier:
            self.delete_id(identifier)
        elif self.lanes.get_selected_snap_index() is not None:
            self.lanes.remove_snap_point(self.lanes.get_selected_snap_index())
            self.snaps_changed()

    def delete_id(self, identifier):
        self.mutate(lambda: self.workspace.delete_annotation(identifier))

    def cut(self):
        annotation = self.workspace.store.get(self.lanes.get_selected_id())
        point = self.player.get_position_ms()
        if annotation and annotation.start_ms < point < annotation.end_ms:
            from dataclasses import asdict

            second_id = uuid.uuid4().hex

            def update(d):
                for run in d.get("suggestion_runs", []):
                    for item in run["suggestions"]:
                        outputs = item.get("output_ids", [])
                        if annotation.id in outputs:
                            outputs.append(second_id)
                d["annotations"] = [a for a in d["annotations"] if a["id"] != annotation.id]
                d["annotations"].extend(
                    [
                        asdict(replace(annotation, end_ms=point)),
                        asdict(replace(annotation, id=second_id, start_ms=point)),
                    ]
                )

            self.mutate(lambda: self.workspace.change(update))

    def sources(self):
        # Non-modal: playback, seeking and evidence stay available while aligning.
        existing = getattr(self, "alignment_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Alignment")
        layout = QVBoxLayout(dialog)
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(0, 0, 0, 0)
        area = ContentScrollArea(dialog)
        area.setWidget(body)
        layout.addWidget(area)
        form.addRow(QLabel("Timeline time = source time + offset"))
        help_text = QLabel(
            "Already synchronized before import? Leave offsets at zero if the sources "
            "already share the video timeline. Describe the method, tools, timing cues "
            "or checks in the notes below. Notes are saved with the workspace and "
            "included in measurement records."
        )
        help_text.setWordWrap(True)
        form.addRow(help_text)
        videos = 0
        for source in self.workspace.data["sources"]:
            config = source["config"]
            if source["kind"] == "video":
                videos += 1
            spin = QDoubleSpinBox()
            spin.setRange(-86400, 86400)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setSuffix(" s")
            spin.setValue(config["offset_ms"] / 1000)
            spin.setEnabled(not (source["kind"] == "video" and videos == 1))
            spin.valueChanged.connect(
                lambda seconds, identifier=config["id"]: self.mutate(
                    lambda: self.workspace.set_offset(identifier, seconds * 1000)
                )
            )
            form.addRow(
                QLabel(config.get("label") or config.get("name") or Path(source["path"]).name), spin
            )
            note = QPlainTextEdit(source.get("synchronization_note", ""))
            note.setObjectName(f"synchronization_note_{config['id']}")
            note.setPlaceholderText(
                "E.g. synchronized before import using hardware timestamps; "
                "alignment checked against a visible tap."
            )
            note.setFixedHeight(note.fontMetrics().lineSpacing() * 3 + 12)
            note.textChanged.connect(
                lambda field=note, identifier=config["id"]: self.mutate(
                    lambda: self.workspace.set_synchronization_note(identifier, field.toPlainText())
                )
            )
            form.addRow("Synchronization notes", note)
        close = QPushButton("Close")
        close.clicked.connect(dialog.close)
        layout.addWidget(close)
        self.alignment_dialog = dialog
        dialog.adjustSize()
        dialog.show()

    def details(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Workspace details")
        form = QFormLayout(dialog)
        name = QLineEdit(self.workspace.data["name"])
        rater = QLineEdit(self.workspace.data.get("rater", ""))
        form.addRow("Name", name)
        form.addRow("Annotator", rater)
        form.addRow("Protocol", QLabel(self.workspace.schema.name))
        fields = {}
        for key, value in self.workspace.data["research_context"].items():
            fields[key] = QLineEdit(str(value))
            form.addRow(key.capitalize(), fields[key])
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.rejected.connect(dialog.reject)

        def save():
            try:
                self.workspace.change(
                    lambda d: d.update(
                        name=name.text().strip(),
                        rater=rater.text().strip(),
                        research_context={key: value.text() for key, value in fields.items()},
                    )
                )
            except ValueError as exc:
                self.error(exc)
                return
            self.changed.emit()
            dialog.accept()

        buttons.accepted.connect(save)
        form.addRow(buttons)
        dialog.exec()

    def pause(self):
        for pane in self.player._panes:
            pane.player.pause()

    def save(self):
        self.workspace.data["view"]["position_ms"] = self.player.get_position_ms()
        self.workspace.save()
        self.changed.emit()
