"""Dataset export dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from rime_core.annotation import AnnotationStore
from rime_core.io import (
    ExportError,
    bids_session_paths,
    export_bids_dataset,
    export_parquet,
    export_signal_clips,
    export_video_clips,
)
from rime_core.io.exporters import _filtered_annotations, _find_ffmpeg
from rime_core.signals import Signal
from rime_core.workspace import WorkingContext
from rime_ui.theme import PATH_INPUT_MIN_WIDTH


class ExportDialog(QDialog):
    """Configure and run single-session dataset export."""

    def __init__(
        self,
        context: WorkingContext,
        signals: list[Signal],
        default_output_dir: Path | str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._signals = list(signals)
        self._ffmpeg_available = _find_ffmpeg() is not None
        self._default_output_dir = (
            Path(default_output_dir)
            if default_output_dir is not None and str(default_output_dir).strip()
            else self._context.session.session_dir / "exports"
        )
        self.output_dir: Path | None = None
        self.exported_files = 0
        self.setWindowTitle("Export Dataset")
        self.setMinimumWidth(560)
        self._setup_ui()
        self._populate_lanes()
        self._update_summary()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Export mode:", self))
        self.export_mode_combo = QComboBox(self)
        self.export_mode_combo.addItem("Flat RIME export", "flat")
        self.export_mode_combo.addItem("BIDS Dataset", "bids")
        self.export_mode_combo.currentIndexChanged.connect(self._on_export_mode_changed)
        mode_row.addWidget(self.export_mode_combo, 1)
        layout.addLayout(mode_row)

        output_row = QHBoxLayout()
        self.output_dir_label = QLabel("Export folder for this session:", self)
        self.output_dir_edit = QLineEdit(str(self._default_output_dir), self)
        self.output_dir_edit.setMinimumWidth(PATH_INPUT_MIN_WIDTH)
        self.output_dir_edit.textChanged.connect(self._update_summary)
        output_row.addWidget(self.output_dir_label)
        output_row.addWidget(self.output_dir_edit, 1)
        browse_button = QPushButton("Browse...", self)
        browse_button.clicked.connect(self._browse_output_dir)
        browse_button.setToolTip("Choose an export folder.")
        output_row.addWidget(browse_button)
        layout.addLayout(output_row)

        contents_box = QGroupBox("Contents", self)
        contents_form = QFormLayout(contents_box)
        contents_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.annotations_checkbox = QCheckBox("Annotation metadata (annotations.parquet)", self)
        self.annotations_checkbox.setChecked(True)
        self.annotations_checkbox.setEnabled(False)
        contents_form.addRow(self.annotations_checkbox)

        self.signal_checkbox = QCheckBox("Signal clips", self)
        self.signal_checkbox.setChecked(bool(self._signals))
        self.signal_checkbox.setEnabled(bool(self._signals))
        self.signal_checkbox.toggled.connect(self._update_summary)
        contents_form.addRow(self.signal_checkbox)

        self.signal_padding_spin = QSpinBox(self)
        self.signal_padding_spin.setRange(0, 60_000)
        self.signal_padding_spin.setValue(500)
        self.signal_padding_spin.setSuffix(" ms")
        self.signal_padding_spin.valueChanged.connect(self._update_summary)
        contents_form.addRow("Signal padding:", self.signal_padding_spin)

        self.video_checkbox = QCheckBox("Video clips", self)
        self.video_checkbox.setChecked(False)
        self.video_checkbox.setEnabled(bool(self._context.session.videos) and self._ffmpeg_available)
        if not self._ffmpeg_available:
            self.video_checkbox.setToolTip("Install ffmpeg to enable video clip export.")
        self.video_checkbox.toggled.connect(self._update_summary)
        contents_form.addRow(self.video_checkbox)

        self.video_padding_spin = QSpinBox(self)
        self.video_padding_spin.setRange(0, 60_000)
        self.video_padding_spin.setValue(500)
        self.video_padding_spin.setSuffix(" ms")
        self.video_padding_spin.valueChanged.connect(self._update_summary)
        contents_form.addRow("Video padding:", self.video_padding_spin)

        self.video_role_combo = QComboBox(self)
        self.video_role_combo.addItem("Primary video", "primary")
        self.video_role_combo.addItem("All videos", "all")
        self.video_role_combo.currentIndexChanged.connect(self._update_summary)
        contents_form.addRow("Video source:", self.video_role_combo)

        self.video_status_label = QLabel(self)
        self.video_status_label.setWordWrap(True)
        contents_form.addRow("", self.video_status_label)

        layout.addWidget(contents_box)

        filters_box = QGroupBox("Filters", self)
        filters_layout = QVBoxLayout(filters_box)
        self.all_lanes_checkbox = QCheckBox("All lanes", self)
        self.all_lanes_checkbox.setChecked(True)
        self.all_lanes_checkbox.toggled.connect(self._on_all_lanes_toggled)
        filters_layout.addWidget(self.all_lanes_checkbox)

        self.lanes_list = QListWidget(self)
        self.lanes_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.lanes_list.itemSelectionChanged.connect(self._update_summary)
        filters_layout.addWidget(self.lanes_list)

        self.include_ghost_checkbox = QCheckBox("Include ghost annotations", self)
        self.include_ghost_checkbox.toggled.connect(self._update_summary)
        filters_layout.addWidget(self.include_ghost_checkbox)
        layout.addWidget(filters_box)

        summary_box = QGroupBox("Summary", self)
        summary_layout = QVBoxLayout(summary_box)
        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        layout.addWidget(summary_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            self,
        )
        buttons.accepted.connect(self._on_export)
        buttons.rejected.connect(self.reject)
        self._export_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._export_button.setText("Export")
        self._export_button.setProperty("role", "primary")
        layout.addWidget(buttons)

    def _populate_lanes(self) -> None:
        self.lanes_list.clear()
        for lane in self._context.schema.lanes:
            item = QListWidgetItem(lane.name)
            self.lanes_list.addItem(item)
            item.setSelected(True)
        self.lanes_list.setEnabled(False)

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Export Directory",
            self.output_dir_edit.text().strip() or str(self._context.session.session_dir),
        )
        if path:
            self.output_dir_edit.setText(path)

    def _on_all_lanes_toggled(self, checked: bool) -> None:
        self.lanes_list.setEnabled(not checked)
        if checked:
            for index in range(self.lanes_list.count()):
                self.lanes_list.item(index).setSelected(True)
        self._update_summary()

    def _selected_lanes(self) -> list[str] | None:
        if self.all_lanes_checkbox.isChecked():
            return None
        selected = [item.text() for item in self.lanes_list.selectedItems()]
        return selected or []

    def _resolve_video_count(self) -> int:
        if self.video_role_combo.currentData() == "all":
            return len(self._context.session.videos)
        return 1 if self._context.session.videos else 0

    def _is_bids_mode(self) -> bool:
        return str(self.export_mode_combo.currentData()) == "bids"

    def _bids_blocker_message(self) -> str | None:
        if self._context.session.provenance.recording_relative_timing_verified:
            return None
        return "BIDS export requires verified recording-relative annotation timing for this session."

    def _on_export_mode_changed(self, *_args) -> None:
        self._update_summary()

    def _update_summary(self) -> None:
        bids_mode = self._is_bids_mode()
        lanes = self._selected_lanes()
        include_ghost = self.include_ghost_checkbox.isChecked()
        all_annotations = _filtered_annotations(
            self._context.store,
            include_ghost=include_ghost,
            lanes=lanes,
        )
        interval_annotations = _filtered_annotations(
            self._context.store,
            include_ghost=include_ghost,
            lanes=lanes,
            include_points=False,
        )
        signal_clip_estimate = (
            len(interval_annotations) * len(self._signals) if self.signal_checkbox.isChecked() else 0
        )
        video_clip_estimate = (
            len(interval_annotations) * self._resolve_video_count()
            if self.video_checkbox.isChecked() and not bids_mode
            else 0
        )
        summary = [f"{len(all_annotations)} annotations", f"{len(self._signals)} signals"]

        if bids_mode:
            self.output_dir_label.setText("BIDS output root:")
            self.annotations_checkbox.setText("BIDS events (required)")
            self.signal_checkbox.setText("Motion recordings + clip derivatives")
            self.video_checkbox.setChecked(False)
            self.video_checkbox.setEnabled(False)
            self.video_padding_spin.setEnabled(False)
            self.video_role_combo.setEnabled(False)
            paths = bids_session_paths(Path(self.output_dir_edit.text().strip() or "."), self._context.session)
            summary.extend(
                [
                    f"Estimated motion exports: {len(self._signals) if self.signal_checkbox.isChecked() else 0}",
                    f"Estimated clip derivatives: {signal_clip_estimate}",
                    f"Preview: {paths.beh_dir.parent}",
                ]
            )
            blocker = self._bids_blocker_message()
            if blocker:
                self.video_status_label.setText(blocker)
                self._export_button.setEnabled(False)
            else:
                self.video_status_label.setText(
                    "Exports validator-targeted BIDS raw outputs plus derivative clip files."
                )
                self._export_button.setEnabled(True)
        else:
            self.output_dir_label.setText("Export folder for this session:")
            self.annotations_checkbox.setText("Annotation metadata (annotations.parquet)")
            self.signal_checkbox.setText("Signal clips")
            self.video_checkbox.setEnabled(
                bool(self._context.session.videos) and self._ffmpeg_available
            )
            summary.extend(
                [
                    f"{len(self._context.session.videos)} videos",
                    f"Estimated signal clips: {signal_clip_estimate}",
                    f"Estimated video clips: {video_clip_estimate}",
                ]
            )
            self._export_button.setEnabled(True)
        if not bids_mode and not self._ffmpeg_available:
            self.video_status_label.setText("Video clip export unavailable: ffmpeg not found on PATH.")
        elif not bids_mode and not self._context.session.videos:
            self.video_status_label.setText("Video clip export unavailable: no videos in this session.")
        elif not bids_mode:
            self.video_status_label.setText("")
        video_controls_enabled = (
            self.video_checkbox.isChecked() and self.video_checkbox.isEnabled() and not bids_mode
        )
        self.video_padding_spin.setEnabled(video_controls_enabled)
        self.video_role_combo.setEnabled(video_controls_enabled)
        self.summary_label.setText(" | ".join(summary))

    def _on_export(self) -> None:
        output_dir_text = self.output_dir_edit.text().strip()
        if not output_dir_text:
            QMessageBox.warning(self, "Missing Output Directory", "Choose an export directory.")
            return

        lanes = self._selected_lanes()
        if lanes == []:
            QMessageBox.warning(self, "Missing Lanes", "Select at least one lane to export.")
            return

        output_dir = Path(output_dir_text)
        include_ghost = self.include_ghost_checkbox.isChecked()
        export_store = self._filtered_store(lanes)

        try:
            if self._is_bids_mode():
                blocker = self._bids_blocker_message()
                if blocker:
                    QMessageBox.warning(self, "BIDS Export Unavailable", blocker)
                    return
                exported_files = export_bids_dataset(
                    export_store,
                    self._context.session,
                    self._signals,
                    output_dir,
                    padding_ms=float(self.signal_padding_spin.value()),
                    include_ghost=include_ghost,
                    lanes=lanes,
                    export_motion=self.signal_checkbox.isChecked(),
                    export_clips=self.signal_checkbox.isChecked(),
                )
            else:
                export_parquet(
                    export_store,
                    self._context.session,
                    output_dir / "annotations.parquet",
                    include_ghost=include_ghost,
                )
                exported_files = 1

                if self.signal_checkbox.isChecked():
                    exported_files += export_signal_clips(
                        export_store,
                        self._context.session,
                        self._signals,
                        output_dir,
                        padding_ms=float(self.signal_padding_spin.value()),
                        include_ghost=include_ghost,
                        lanes=lanes,
                    )

                if self.video_checkbox.isChecked():
                    progress = QProgressDialog("Exporting video clips...", "Cancel", 0, 0, self)
                    progress.setWindowTitle("Export Dataset")
                    progress.setAutoClose(True)
                    progress.setAutoReset(True)
                    progress.show()
                    try:
                        exported_files += export_video_clips(
                            export_store,
                            self._context.session,
                            output_dir,
                            padding_ms=float(self.video_padding_spin.value()),
                            include_ghost=include_ghost,
                            lanes=lanes,
                            video_role=str(self.video_role_combo.currentData()),
                        )
                    finally:
                        progress.close()
        except ExportError as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Failed to export dataset:\n{exc}")
            return

        self.output_dir = output_dir
        self.exported_files = exported_files
        self.accept()

    def _filtered_store(self, lanes: list[str] | None) -> AnnotationStore:
        store = AnnotationStore()
        store._session_id = self._context.store._session_id
        store._session_name = self._context.store._session_name
        for annotation in _filtered_annotations(
            self._context.store,
            include_ghost=True,
            lanes=lanes,
        ):
            store.add(annotation)
        return store
