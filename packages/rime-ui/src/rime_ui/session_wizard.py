"""Session creation wizard dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rime_core import (
    AnnotationStore,
    AppSettings,
    MAX_SESSION_VIDEOS,
    ProtocolSchema,
    SignalConfig,
    Session,
    SessionProvenance,
    SubjectInfo,
    VideoConfig,
    create_session,
)
from rime_core.schema import DEFAULT_SCHEMA_PATH, NOTES_ONLY_SCHEMA_PATH
from rime_core.session import save_session
from rime_ui.schema_browser import SchemaBrowserWindow
from rime_ui.signal_config_dialog import SignalConfigDialog
from rime_ui.theme import PATH_INPUT_MIN_WIDTH


_BUILTIN_SCHEMAS: list[tuple[str, str, Path]] = [
    ("notes_only", "Notes Only", NOTES_ONLY_SCHEMA_PATH),
    ("fog_coa", "FOG-COA", DEFAULT_SCHEMA_PATH),
]


class SessionWizard(QDialog):
    """Simple wizard-like dialog for creating a session."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        app_settings: AppSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_settings = app_settings or AppSettings()
        self._selected_schema: ProtocolSchema | None = None
        self._selected_schema_path: Path | None = None
        self.setWindowTitle("New Session")
        self.setMinimumWidth(560)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_input = QLineEdit()
        self.dir_input = QLineEdit()
        self.dir_input.setMinimumWidth(PATH_INPUT_MIN_WIDTH)
        self.rater_input = QLineEdit(self._app_settings.default_rater)
        self.subject_input = QLineEdit()
        self.condition_input = QLineEdit()
        self.med_state_input = QLineEdit()

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_input)
        dir_row.addWidget(browse_btn)
        dir_container = QWidget()
        dir_container.setLayout(dir_row)

        self.schema_combo = QComboBox()
        for key, label, path in _BUILTIN_SCHEMAS:
            self.schema_combo.addItem(f"{label} (built-in)", (key, path))
        fog_index = next((idx for idx, (key, _, _) in enumerate(_BUILTIN_SCHEMAS) if key == "fog_coa"), 0)
        self.schema_combo.setCurrentIndex(fog_index)
        self.schema_combo.currentIndexChanged.connect(self._on_schema_combo_changed)
        self._load_builtin_schema(fog_index)
        create_custom_btn = QPushButton("Create Custom...")
        create_custom_btn.clicked.connect(self._open_schema_editor)
        self.view_schema_btn = QPushButton("View...")
        self.view_schema_btn.clicked.connect(self._open_schema_viewer)
        schema_row = QHBoxLayout()
        schema_row.addWidget(self.schema_combo, 1)
        schema_row.addWidget(create_custom_btn)
        schema_row.addWidget(self.view_schema_btn)
        schema_container = QWidget()
        schema_container.setLayout(schema_row)

        form.addRow("Session name:", self.name_input)
        form.addRow("Session folder:", dir_container)
        form.addRow("Schema:", schema_container)
        form.addRow("Rater ID (optional):", self.rater_input)
        form.addRow("Subject ID (optional):", self.subject_input)
        form.addRow("Condition (optional):", self.condition_input)
        form.addRow("Medication state (optional):", self.med_state_input)
        layout.addLayout(form)

        layout.addWidget(QLabel(f"Videos (optional, up to {MAX_SESSION_VIDEOS}):"))
        self.video_list = QListWidget()
        layout.addWidget(self.video_list)

        video_row = QHBoxLayout()
        add_video_btn = QPushButton("Add Video...")
        add_video_btn.clicked.connect(self._add_videos)
        clear_video_btn = QPushButton("Clear")
        clear_video_btn.setProperty("role", "remove")
        clear_video_btn.clicked.connect(self.video_list.clear)
        video_row.addWidget(add_video_btn)
        video_row.addWidget(clear_video_btn)
        video_row.addStretch()
        layout.addLayout(video_row)

        layout.addWidget(QLabel("Signals (optional):"))
        self.signal_list = QListWidget()
        layout.addWidget(self.signal_list)

        signal_row = QHBoxLayout()
        add_signal_btn = QPushButton("Add Signal(s)...")
        add_signal_btn.clicked.connect(self._add_signals)
        clear_signal_btn = QPushButton("Clear")
        clear_signal_btn.setProperty("role", "remove")
        clear_signal_btn.clicked.connect(self.signal_list.clear)
        signal_row.addWidget(add_signal_btn)
        signal_row.addWidget(clear_signal_btn)
        signal_row.addStretch()
        layout.addLayout(signal_row)

        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        create_btn = QPushButton("Create")
        create_btn.setProperty("role", "primary")
        create_btn.clicked.connect(self._validate_and_accept)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(create_btn)
        layout.addLayout(button_row)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Session Folder")
        if path:
            self.dir_input.setText(path)

    def _load_builtin_schema(self, index: int) -> None:
        _key, _label, path = _BUILTIN_SCHEMAS[index]
        self._selected_schema_path = path
        self._selected_schema = ProtocolSchema.load(path)
        self._update_schema_tooltip()

    def _on_schema_combo_changed(self, index: int) -> None:
        data = self.schema_combo.itemData(index)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        key, maybe_path = data
        if key == "custom":
            self._update_schema_tooltip()
            return
        if isinstance(maybe_path, Path):
            self._selected_schema_path = maybe_path
            self._selected_schema = ProtocolSchema.load(maybe_path)
            self._update_schema_tooltip()

    def _update_schema_tooltip(self) -> None:
        if self._selected_schema is None or self._selected_schema_path is None:
            self.schema_combo.setToolTip("")
            return
        self.schema_combo.setToolTip(
            f"{self._selected_schema.name} v{self._selected_schema.version}\n{self._selected_schema_path}"
        )

    def _open_schema_editor(self) -> None:
        schema = self._selected_schema or ProtocolSchema.default()
        dialog = SchemaBrowserWindow(
            schema=schema,
            schema_path=None,
            chooser_mode=True,
            parent=self,
        )
        dialog.schema_chosen.connect(self._on_custom_schema_chosen)
        dialog.exec()

    def _on_custom_schema_chosen(self, path: str, schema: object) -> None:
        if not isinstance(schema, ProtocolSchema):
            return
        self._selected_schema = schema
        self._selected_schema_path = Path(path)
        custom_index = self.schema_combo.findData(("custom", str(self._selected_schema_path)))
        label = f"Custom: {schema.name}"
        if custom_index == -1:
            self.schema_combo.addItem(label, ("custom", str(self._selected_schema_path)))
            custom_index = self.schema_combo.count() - 1
        else:
            self.schema_combo.setItemText(custom_index, label)
        self.schema_combo.setCurrentIndex(custom_index)
        self._update_schema_tooltip()

    def _open_schema_viewer(self) -> None:
        schema = self._selected_schema or ProtocolSchema.default()
        path = self._selected_schema_path
        dialog = SchemaBrowserWindow(
            schema=schema,
            schema_path=path,
            read_only=True,
            parent=self,
        )
        dialog.exec()

    def _add_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Video Files", "", "Videos (*.mp4 *.mov *.avi)")
        if not paths:
            return
        existing = {self.video_list.item(idx).text() for idx in range(self.video_list.count())}
        added = 0
        ignored = 0
        for path in paths:
            if path in existing:
                continue
            if self.video_list.count() >= MAX_SESSION_VIDEOS:
                ignored += 1
                continue
            self.video_list.addItem(path)
            existing.add(path)
            added += 1
        if ignored:
            QMessageBox.information(
                self,
                "Video Limit Reached",
                f"Sessions support up to {MAX_SESSION_VIDEOS} videos. Extra selections were ignored.",
            )

    def _add_signals(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Signal Files",
            "",
            "Signal Files (*.csv *.h5 *.hdf5);;All Files (*)",
        )
        if not paths:
            return

        session_dir = Path(self.dir_input.text().strip()) if self.dir_input.text().strip() else None
        existing = {
            self.signal_list.item(idx).data(0)
            for idx in range(self.signal_list.count())
        }
        for raw_path in paths:
            stored_path = self._normalize_path_for_base(raw_path, session_dir) if session_dir else raw_path
            if stored_path in existing:
                continue
            config = SignalConfigDialog.configure_signal(
                signal_path=raw_path,
                stored_path=stored_path,
                parent=self,
            )
            if config is None:
                return
            self._add_signal_item(config)
            existing.add(stored_path)

    def _add_signal_item(self, config: SignalConfig) -> None:
        label = f"{config.name or Path(config.path).stem} [{config.format}]"
        widget_item = QListWidgetItem(label)
        widget_item.setToolTip(config.path)
        widget_item.setData(Qt.ItemDataRole.UserRole, config)
        self.signal_list.addItem(widget_item)

    def _normalize_path_for_base(self, raw_path: str, base_dir: Path) -> str:
        path = Path(raw_path)
        if not path.is_absolute():
            return raw_path
        try:
            return str(path.relative_to(base_dir))
        except ValueError:
            return str(path)

    def _validate_and_accept(self) -> None:
        if not self.dir_input.text().strip():
            QMessageBox.warning(self, "Missing Folder", "Choose a session folder.")
            return
        if self._selected_schema is None or self._selected_schema_path is None:
            QMessageBox.warning(self, "Missing Schema", "Choose or create a schema.")
            return
        self.accept()

    def to_result(self) -> tuple[Session, AnnotationStore]:
        """Create session + empty store based on user inputs."""
        session_dir = Path(self.dir_input.text().strip())
        name = self.name_input.text().strip() or session_dir.name

        videos: list[VideoConfig] = []
        for idx in range(self.video_list.count()):
            path = self.video_list.item(idx).text()
            role = "primary" if idx == 0 else "secondary"
            videos.append(VideoConfig(path=path, role=role))

        signals: list[SignalConfig] = []
        for idx in range(self.signal_list.count()):
            item = self.signal_list.item(idx)
            config = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(config, SignalConfig):
                signals.append(config)

        subject = None
        subject_id = self.subject_input.text().strip()
        if subject_id:
            subject = SubjectInfo(
                id=subject_id,
                condition=self.condition_input.text().strip(),
                medication_state=self.med_state_input.text().strip(),
            )

        selected_schema = self._selected_schema or ProtocolSchema.default()
        schema_path = str(self._selected_schema_path or DEFAULT_SCHEMA_PATH)

        session = create_session(
            session_dir=session_dir,
            name=name,
            videos=videos,
            signals=signals,
            schema_path=schema_path,
            schema_name=selected_schema.name if selected_schema else "",
            schema_version=selected_schema.version if selected_schema else "",
            subject=subject,
            rater=self.rater_input.text().strip(),
            provenance=SessionProvenance(origin="manual"),
        )
        save_session(session)

        store = AnnotationStore()
        store._session_id = session.id
        store._session_name = session.name
        store.save(session.session_dir / "annotations" / "annotations.json")
        return session, store

    @classmethod
    def create_session(
        cls,
        parent: QWidget | None = None,
        *,
        app_settings: AppSettings | None = None,
    ) -> tuple[Session, AnnotationStore] | None:
        dialog = cls(parent, app_settings=app_settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.to_result()
