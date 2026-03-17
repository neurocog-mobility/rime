"""ELAN import — explicit mapping dialog."""

from __future__ import annotations

import pympi
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rime_core import MAX_SESSION_VIDEOS
from rime_core.elan_import import TierMapping, auto_map_tiers, normalize_label
from rime_core.schema import ProtocolSchema
from rime_ui.theme import COLOR_CONFLICT_BG, PATH_INPUT_MIN_WIDTH, muted_text_stylesheet, set_layout_metrics, set_zero_margins


class ImportDialog(QDialog):
    """All-in-one dialog for importing an ELAN .eaf file into a RIME session."""

    def __init__(self, schema: ProtocolSchema, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import from ELAN")
        self.setMinimumSize(760, 560)

        self._schema = schema
        self.mappings: list[TierMapping] = []
        self._eaf: pympi.Elan.Eaf | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        set_layout_metrics(root)

        source_box = QGroupBox("Source")
        source_layout = QVBoxLayout(source_box)

        eaf_row = QHBoxLayout()
        eaf_row.addWidget(QLabel("ELAN file:"))
        self.eaf_input = QLineEdit()
        self.eaf_input.setMinimumWidth(PATH_INPUT_MIN_WIDTH)
        self.eaf_input.setPlaceholderText("Select a .eaf file...")
        self.eaf_input.setReadOnly(True)
        eaf_row.addWidget(self.eaf_input)
        eaf_browse = QPushButton("Browse...")
        eaf_browse.clicked.connect(self._browse_eaf)
        eaf_browse.setToolTip("Choose an ELAN file to import.")
        eaf_row.addWidget(eaf_browse)
        source_layout.addLayout(eaf_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Output folder:"))
        self.dir_input = QLineEdit()
        self.dir_input.setMinimumWidth(PATH_INPUT_MIN_WIDTH)
        self.dir_input.setPlaceholderText("Where to create the RIME session...")
        self.dir_input.setReadOnly(True)
        dir_row.addWidget(self.dir_input)
        dir_browse = QPushButton("Browse...")
        dir_browse.clicked.connect(self._browse_dir)
        dir_browse.setToolTip("Choose where the imported session should be created.")
        dir_row.addWidget(dir_browse)
        source_layout.addLayout(dir_row)

        root.addWidget(source_box)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        set_zero_margins(body_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal, body)

        mapping_box = QGroupBox("Tier Mapping")
        mapping_layout = QVBoxLayout(mapping_box)
        helper = QLabel(
            "Exact lane-name matches are prefilled; everything else needs a lane or Skip.",
            mapping_box,
        )
        helper.setWordWrap(True)
        helper.setStyleSheet(muted_text_stylesheet())
        mapping_layout.addWidget(helper)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["ELAN Tier", "RIME Lane"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(140)
        self.mapping_placeholder = QLabel("Select an ELAN file to map tiers.")
        self.mapping_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mapping_placeholder.setStyleSheet(muted_text_stylesheet())
        mapping_layout.addWidget(self.mapping_placeholder)
        mapping_layout.addWidget(self.table)
        self.table.hide()
        splitter.addWidget(mapping_box)

        label_box = QGroupBox("Label Mapping")
        label_layout = QVBoxLayout(label_box)
        label_helper = QLabel(
            "Exact label-name matches are prefilled; unmatched labels must be chosen explicitly.",
            label_box,
        )
        label_helper.setWordWrap(True)
        label_helper.setStyleSheet(muted_text_stylesheet())
        label_layout.addWidget(label_helper)
        self.label_table = QTableWidget(0, 3)
        self.label_table.setHorizontalHeaderLabels(["ELAN Tier", "ELAN Label", "RIME Label"])
        self.label_table.horizontalHeader().setStretchLastSection(True)
        self.label_table.setMinimumHeight(180)
        self.label_placeholder = QLabel("Mapped tiers with labels will appear here.")
        self.label_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_placeholder.setStyleSheet(muted_text_stylesheet())
        label_layout.addWidget(self.label_placeholder)
        label_layout.addWidget(self.label_table)
        self.label_table.hide()
        splitter.addWidget(label_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        body_layout.addWidget(splitter)

        media_box = QGroupBox("Media Files")
        media_layout = QVBoxLayout(media_box)

        media_layout.addWidget(QLabel(f"Videos (up to {MAX_SESSION_VIDEOS}):"))
        self.video_list = QListWidget()
        self.video_list.setMinimumHeight(96)
        media_layout.addWidget(self.video_list)
        vid_btns = QHBoxLayout()
        add_vid = QPushButton("Add Video...")
        add_vid.clicked.connect(self._add_videos)
        rm_vid = QPushButton("Remove")
        rm_vid.setProperty("role", "remove")
        rm_vid.clicked.connect(lambda: self._remove_selected(self.video_list))
        vid_btns.addWidget(add_vid)
        vid_btns.addWidget(rm_vid)
        vid_btns.addStretch()
        media_layout.addLayout(vid_btns)

        media_layout.addWidget(QLabel("Signal files (optional):"))
        self.signal_list = QListWidget()
        self.signal_list.setMinimumHeight(72)
        media_layout.addWidget(self.signal_list)
        sig_btns = QHBoxLayout()
        add_sig = QPushButton("Add Signal(s)...")
        add_sig.clicked.connect(self._add_signals)
        rm_sig = QPushButton("Remove")
        rm_sig.setProperty("role", "remove")
        rm_sig.clicked.connect(lambda: self._remove_selected(self.signal_list))
        sig_btns.addWidget(add_sig)
        sig_btns.addWidget(rm_sig)
        sig_btns.addStretch()
        media_layout.addLayout(sig_btns)

        body_layout.addWidget(media_box)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.apply_rules_checkbox = QCheckBox("Apply hierarchy rules after import")
        self.apply_rules_checkbox.setChecked(True)
        root.addWidget(self.apply_rules_checkbox)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.import_btn = QPushButton("Import")
        self.import_btn.setProperty("role", "primary")
        self.import_btn.clicked.connect(self._validate_and_accept)
        self.import_btn.setEnabled(False)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.import_btn)
        root.addLayout(btn_row)

    def _browse_eaf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ELAN File", "", "ELAN Files (*.eaf);;All Files (*)"
        )
        if not path:
            return
        self.eaf_input.setText(path)
        self._load_eaf(path)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.dir_input.setText(path)
            self._update_import_button()

    def _load_eaf(self, path: str) -> None:
        try:
            self._eaf = pympi.Elan.Eaf(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to read ELAN file:\n{exc}")
            return

        tier_names = list(self._eaf.get_tier_names())
        self.mappings = auto_map_tiers(tier_names, self._schema)
        for mapping in self.mappings:
            mapping.annotation_count = len(self._eaf.get_annotation_data_for_tier(mapping.elan_tier))

        self._populate_tier_table()
        self._rebuild_label_table()
        self._update_import_button()

    def _populate_tier_table(self) -> None:
        self.mapping_placeholder.hide()
        self.table.show()
        self.table.setRowCount(len(self.mappings))
        lane_names = self._schema.get_lane_names()

        for row, mapping in enumerate(self.mappings):
            tier_item = QTableWidgetItem(f"{mapping.elan_tier} ({mapping.annotation_count} ann)")
            tier_item.setFlags(tier_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, tier_item)

            lane_combo = QComboBox()
            lane_combo.addItem("Skip")
            for lane in lane_names:
                lane_combo.addItem(lane)
            if mapping.rime_lane and mapping.rime_lane in lane_names:
                lane_combo.setCurrentText(mapping.rime_lane)
            lane_combo.currentIndexChanged.connect(self._rebuild_label_table)
            lane_combo.currentIndexChanged.connect(self._refresh_tier_row_colors)
            self.table.setCellWidget(row, 1, lane_combo)

        self.table.resizeColumnsToContents()
        self._refresh_tier_row_colors()

    def _refresh_tier_row_colors(self) -> None:
        warning_color = QColor(COLOR_CONFLICT_BG)
        for row in range(self.table.rowCount()):
            tier_item = self.table.item(row, 0)
            combo = self.table.cellWidget(row, 1)
            if tier_item is None or not isinstance(combo, QComboBox):
                continue
            if combo.currentText() == "Skip":
                tier_item.setBackground(warning_color)
            else:
                tier_item.setData(Qt.ItemDataRole.BackgroundRole, None)

    def _rebuild_label_table(self) -> None:
        if self._eaf is None:
            self.label_placeholder.show()
            self.label_table.hide()
            self.label_table.setRowCount(0)
            return

        rows: list[tuple[str, str, list[str], str | None]] = []
        for row, mapping in enumerate(self.mappings):
            combo = self.table.cellWidget(row, 1)
            if not isinstance(combo, QComboBox):
                continue
            lane_name = combo.currentText()
            if lane_name == "Skip":
                continue
            lane_labels = self._schema.get_labels(lane_name)
            seen: set[str] = set()
            for _start_ms, _end_ms, label in self._eaf.get_annotation_data_for_tier(mapping.elan_tier):
                raw_label = (label or "").strip()
                if raw_label in seen:
                    continue
                seen.add(raw_label)
                suggested = self._suggest_label_mapping(raw_label, lane_labels)
                rows.append((mapping.elan_tier, raw_label, lane_labels, suggested))

        self.label_table.setRowCount(0)
        if not rows:
            self.label_placeholder.show()
            self.label_table.hide()
            return

        self.label_placeholder.hide()
        self.label_table.show()
        for elan_tier, raw_label, lane_labels, suggested in rows:
            row = self.label_table.rowCount()
            self.label_table.insertRow(row)
            tier_item = QTableWidgetItem(elan_tier)
            tier_item.setFlags(tier_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.label_table.setItem(row, 0, tier_item)
            label_item = QTableWidgetItem(raw_label or "(blank)")
            label_item.setData(Qt.ItemDataRole.UserRole, raw_label)
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.label_table.setItem(row, 1, label_item)
            label_combo = QComboBox()
            label_combo.addItem("Skip")
            for lane_label in lane_labels:
                label_combo.addItem(lane_label)
            if suggested and suggested in lane_labels:
                label_combo.setCurrentText(suggested)
            self.label_table.setCellWidget(row, 2, label_combo)

        self.label_table.resizeColumnsToContents()

    @staticmethod
    def _suggest_label_mapping(raw_label: str, lane_labels: list[str]) -> str | None:
        normalized = normalize_label(raw_label, lane_labels)
        if normalized in lane_labels:
            return normalized
        if not raw_label and len(lane_labels) == 1:
            return lane_labels[0]
        return None

    def _add_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Video Files", "", "Videos (*.mp4 *.mov *.avi *.mkv);;All Files (*)"
        )
        self._add_unique(self.video_list, paths, limit=MAX_SESSION_VIDEOS)

    def _add_signals(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Signal Files", "", "Signals (*.csv *.h5 *.hdf5);;All Files (*)"
        )
        self._add_unique(self.signal_list, paths)

    @staticmethod
    def _add_unique(list_widget: QListWidget, paths: list[str], *, limit: int | None = None) -> None:
        existing = {list_widget.item(i).text() for i in range(list_widget.count())}
        added = 0
        ignored = 0
        for path in paths:
            if path not in existing:
                if limit is not None and list_widget.count() >= limit:
                    ignored += 1
                    continue
                list_widget.addItem(path)
                existing.add(path)
                added += 1
        if ignored:
            QMessageBox.information(
                list_widget,
                "Video Limit Reached",
                f"Sessions support up to {limit} videos. Extra selections were ignored.",
            )
    @staticmethod
    def _remove_selected(list_widget: QListWidget) -> None:
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))

    def _update_import_button(self) -> None:
        has_eaf = bool(self.eaf_input.text().strip())
        has_dir = bool(self.dir_input.text().strip())
        self.import_btn.setEnabled(has_eaf and has_dir)

    def _validate_and_accept(self) -> None:
        if not self.eaf_input.text().strip():
            QMessageBox.warning(self, "Missing File", "Select an ELAN .eaf file.")
            return
        if not self.dir_input.text().strip():
            QMessageBox.warning(self, "Missing Folder", "Select an output folder.")
            return
        if self.video_list.count() == 0:
            reply = QMessageBox.question(
                self,
                "No Videos",
                "No video files added. Continue without video?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self._has_unresolved_label_mappings():
            QMessageBox.warning(
                self,
                "Incomplete Label Mapping",
                "Choose a target schema label for every imported ELAN label before continuing.",
            )
            return
        self.accept()

    def _has_unresolved_label_mappings(self) -> bool:
        for row in range(self.label_table.rowCount()):
            combo = self.label_table.cellWidget(row, 2)
            if isinstance(combo, QComboBox) and combo.currentText() == "Skip":
                return True
        return False

    def get_result(
        self,
    ) -> tuple[str, str, dict[str, str], dict[str, str], bool, list[str], list[str]]:
        tier_map: dict[str, str] = {}
        label_map: dict[str, str] = {}

        for row, mapping in enumerate(self.mappings):
            combo = self.table.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                selected = combo.currentText()
                if selected != "Skip":
                    tier_map[mapping.elan_tier] = selected

        for row in range(self.label_table.rowCount()):
            raw_item = self.label_table.item(row, 1)
            combo = self.label_table.cellWidget(row, 2)
            if raw_item is None or not isinstance(combo, QComboBox):
                continue
            raw_label = raw_item.data(Qt.ItemDataRole.UserRole)
            selected = combo.currentText()
            if selected != "Skip" and isinstance(raw_label, str):
                label_map[raw_label] = selected

        videos = [self.video_list.item(i).text() for i in range(self.video_list.count())]
        signals = [self.signal_list.item(i).text() for i in range(self.signal_list.count())]

        return (
            self.eaf_input.text().strip(),
            self.dir_input.text().strip(),
            tier_map,
            label_map,
            self.apply_rules_checkbox.isChecked(),
            videos,
            signals,
        )

    @classmethod
    def run(
        cls, schema: ProtocolSchema, parent: QWidget | None = None
    ) -> tuple[str, str, dict[str, str], dict[str, str], bool, list[str], list[str]] | None:
        dialog = cls(schema, parent=parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.get_result()
