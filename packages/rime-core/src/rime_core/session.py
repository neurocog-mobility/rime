"""Session model and persistence for RIME annotation sessions."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class VideoConfig:
    """Configuration for a video file in the session."""

    path: str
    name: str = ""
    role: str = "primary"
    offset_ms: float = 0.0
    fps_override: float | None = None
    sync_method: str = ""
    label: str = ""


MAX_SESSION_VIDEOS = 2

DEFAULT_PANEL_VISIBILITY: dict[str, bool] = {
    "annotation_list": True,
    "model_runner": True,
    "model_evaluation": True,
    "clinical_outcomes": True,
    "irr_panel": True,
}


def normalize_session_videos(videos: list[VideoConfig]) -> list[VideoConfig]:
    """Deduplicate, cap, and canonicalize session video slots to primary/secondary."""
    normalized: list[VideoConfig] = []
    seen_paths: set[str] = set()
    for video in videos:
        if video.path in seen_paths:
            continue
        seen_paths.add(video.path)
        role = "primary" if not normalized else "secondary"
        normalized.append(replace(video, role=role))
        if len(normalized) == MAX_SESSION_VIDEOS:
            break
    return normalized


def normalize_panel_visibility(panel_visibility: dict[str, Any] | None) -> dict[str, bool]:
    """Return a validated panel-visibility map with defaults filled in."""
    normalized = dict(DEFAULT_PANEL_VISIBILITY)
    if not isinstance(panel_visibility, dict):
        return normalized
    for key, value in panel_visibility.items():
        if key in normalized and isinstance(value, bool):
            normalized[key] = value
    return normalized


@dataclass
class SignalConfig:
    """Configuration for a signal file in the session."""

    path: str
    type: str
    format: str
    sampling_rate_hz: float
    time_column: str
    name: str = ""
    time_reference: str = "relative"
    time_unit: str = "seconds"
    offset_ms: float = 0.0
    sync_method: str = ""
    channels: list[str] = field(default_factory=list)
    display_channels: list[str] = field(default_factory=list)


@dataclass
class SubjectInfo:
    """Subject metadata."""

    id: str
    condition: str = ""
    medication_state: str = ""


@dataclass
class SessionProvenance:
    """Metadata describing how the session was created."""

    origin: str = "manual"
    source_files: list[str] = field(default_factory=list)
    tier_map: dict[str, str] = field(default_factory=dict)
    label_map: dict[str, str] = field(default_factory=dict)
    rules_applied: bool = False


@dataclass
class ModelSettings:
    """Per-model runtime settings persisted with a session."""

    params: dict[str, Any] = field(default_factory=dict)
    input_sources: dict[str, str] = field(default_factory=dict)
    input_bindings: dict[str, dict[str, str]] = field(default_factory=dict)
    output_mappings: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ClinicalMetricSpec:
    """One saved clinical metric definition."""

    name: str
    numerator: list[dict[str, str | None]] = field(default_factory=list)
    denominator_type: str = "session"
    denominator: list[dict[str, str | None]] = field(default_factory=list)


@dataclass
class Session:
    """Represents a RIME annotation session."""

    id: str
    name: str
    version: str
    created: str
    modified: str
    session_dir: Path
    primary_video: str
    schema_path: str = ""
    schema_name: str = ""
    schema_version: str = ""
    session_start_utc: str = ""
    videos: list[VideoConfig] = field(default_factory=list)
    signals: list[SignalConfig] = field(default_factory=list)
    model_paths: dict[str, str] = field(default_factory=dict)
    model_settings: dict[str, ModelSettings] = field(default_factory=dict)
    snap_points: list[float] = field(default_factory=list)
    signal_display_combined: bool = True
    panel_visibility: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_PANEL_VISIBILITY)
    )
    dock_layout_state: str = ""
    clinical_metrics: list[ClinicalMetricSpec] = field(default_factory=list)
    subject: SubjectInfo | None = None
    rater: str = ""
    provenance: SessionProvenance = field(default_factory=SessionProvenance)

    def get_video_path(self, video: VideoConfig) -> Path:
        """Resolve absolute path for a video."""
        return self.session_dir / video.path

    def get_signal_path(self, signal: SignalConfig) -> Path:
        """Resolve absolute path for a signal file."""
        return self.session_dir / signal.path

    def get_model_path(self, model_name: str) -> Path | None:
        """Resolve an absolute model package path for a persisted model entry."""
        raw_path = self.model_paths.get(model_name)
        if not raw_path:
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.session_dir / path
        return path

    def get_primary_video_path(self) -> Path:
        """Get the absolute path to the primary video."""
        return self.session_dir / self.primary_video


def create_session(
    session_dir: Path,
    name: str,
    videos: list[VideoConfig],
    signals: list[SignalConfig] | None = None,
    schema_path: str = "",
    schema_name: str = "",
    schema_version: str = "",
    subject: SubjectInfo | None = None,
    rater: str = "",
    provenance: SessionProvenance | None = None,
) -> Session:
    """Create a new session and save session.json to disk."""
    now = _utc_now_iso()
    resolved_dir = Path(session_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    normalized_videos = normalize_session_videos(videos)
    primary_video = _pick_primary_video(normalized_videos)

    session = Session(
        id=f"ses-{uuid.uuid4().hex[:8]}",
        name=name,
        version="1.0",
        created=now,
        modified=now,
        session_dir=resolved_dir,
        primary_video=primary_video,
        schema_path=schema_path,
        schema_name=schema_name,
        schema_version=schema_version,
        session_start_utc="",
        videos=normalized_videos,
        signals=list(signals or []),
        clinical_metrics=[],
        subject=subject,
        rater=rater,
        provenance=provenance or SessionProvenance(origin="manual"),
    )
    save_session(session)
    return session


def save_session(session: Session) -> None:
    """Write session metadata to session.json in the session directory."""
    session.session_dir.mkdir(parents=True, exist_ok=True)
    session.modified = _utc_now_iso()

    payload: dict[str, Any] = {
        "version": session.version,
        "id": session.id,
        "name": session.name,
        "created": session.created,
        "modified": session.modified,
        "primary_video": session.primary_video,
        "schema_path": session.schema_path,
        "schema_name": session.schema_name,
        "schema_version": session.schema_version,
        "session_start_utc": session.session_start_utc,
        "videos": [asdict(video) for video in session.videos],
        "signals": [asdict(signal) for signal in session.signals],
        "model_paths": dict(session.model_paths),
        "model_settings": {
            model_name: asdict(settings) for model_name, settings in session.model_settings.items()
        },
        "snap_points": [float(value) for value in session.snap_points],
        "signal_display_combined": bool(session.signal_display_combined),
        "panel_visibility": normalize_panel_visibility(session.panel_visibility),
        "dock_layout_state": session.dock_layout_state,
        "clinical_metrics": [asdict(metric) for metric in session.clinical_metrics],
        "rater": session.rater,
        "provenance": asdict(session.provenance),
    }
    if session.subject:
        payload["subject"] = asdict(session.subject)

    with open(session.session_dir / "session.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_session(session_path: str | Path) -> Session:
    """Load a RIME session from session.json or session directory."""
    path = Path(session_path)
    if path.is_dir():
        manifest_path = path / "session.json"
        session_dir = path
    else:
        manifest_path = path
        session_dir = path.parent

    if not manifest_path.exists():
        raise FileNotFoundError(f"Session manifest not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)

    videos = [
        VideoConfig(
            path=item["path"],
            name=item.get("name", ""),
            role=item.get("role", "primary"),
            offset_ms=item.get("offset_ms", 0.0),
            fps_override=item.get("fps_override"),
            sync_method=item.get("sync_method", ""),
            label=item.get("label", ""),
        )
        for item in data.get("videos", [])
    ]

    signals = [
        SignalConfig(
            path=item["path"],
            type=item.get("type", "unknown"),
            format=item.get("format", "csv"),
            sampling_rate_hz=item.get("sampling_rate_hz", 100.0),
            time_column=item.get("time_column", "time"),
            name=item.get("name", ""),
            time_reference=item.get("time_reference", "relative"),
            time_unit=item.get("time_unit", "seconds"),
            offset_ms=item.get("offset_ms", 0.0),
            sync_method=item.get("sync_method", ""),
            channels=item.get("channels", []),
            display_channels=item.get("display_channels", []),
        )
        for item in data.get("signals", [])
    ]
    model_settings = {
        model_name: ModelSettings(
            params=dict(item.get("params", {})),
            input_sources=dict(item.get("input_sources", {})),
            input_bindings={
                input_name: dict(mapping)
                for input_name, mapping in item.get("input_bindings", {}).items()
            },
            output_mappings=[dict(mapping) for mapping in item.get("output_mappings", [])],
        )
        for model_name, item in data.get("model_settings", {}).items()
        if isinstance(item, dict)
    }
    model_paths = {
        model_name: path
        for model_name, path in data.get("model_paths", {}).items()
        if isinstance(model_name, str) and isinstance(path, str) and path.strip()
    }
    clinical_metrics = [
        ClinicalMetricSpec(
            name=item.get("name", ""),
            numerator=[dict(spec) for spec in item.get("numerator", []) if isinstance(spec, dict)],
            denominator_type=item.get("denominator_type", "session"),
            denominator=[dict(spec) for spec in item.get("denominator", []) if isinstance(spec, dict)],
        )
        for item in data.get("clinical_metrics", [])
        if isinstance(item, dict)
    ]
    panel_visibility = normalize_panel_visibility(data.get("panel_visibility"))

    subject = None
    if "subject" in data:
        raw_subject = data.get("subject", {})
        subject = SubjectInfo(
            id=raw_subject.get("id", ""),
            condition=raw_subject.get("condition", ""),
            medication_state=raw_subject.get("medication_state", ""),
        )

    raw_provenance = data.get("provenance", {})
    provenance = SessionProvenance(
        origin=raw_provenance.get("origin", "manual"),
        source_files=raw_provenance.get("source_files", []),
        tier_map=raw_provenance.get("tier_map", {}),
        label_map=raw_provenance.get("label_map", {}),
        rules_applied=bool(raw_provenance.get("rules_applied", False)),
    )

    primary_video = data.get("primary_video", _pick_primary_video(videos))
    return Session(
        id=data.get("id", ""),
        name=data.get("name", "Untitled Session"),
        version=data.get("version", "1.0"),
        created=data.get("created", ""),
        modified=data.get("modified", ""),
        session_dir=session_dir,
        primary_video=primary_video,
        schema_path=data.get("schema_path", ""),
        schema_name=data.get("schema_name", ""),
        schema_version=data.get("schema_version", ""),
        session_start_utc=data.get("session_start_utc", ""),
        videos=videos,
        signals=signals,
        model_paths=model_paths,
        model_settings=model_settings,
        snap_points=[float(value) for value in data.get("snap_points", [])],
        signal_display_combined=bool(data.get("signal_display_combined", True)),
        panel_visibility=panel_visibility,
        dock_layout_state=data.get("dock_layout_state", ""),
        clinical_metrics=clinical_metrics,
        subject=subject,
        rater=data.get("rater", ""),
        provenance=provenance,
    )


def _pick_primary_video(videos: list[VideoConfig]) -> str:
    if not videos:
        return ""
    for video in videos:
        if video.role == "primary":
            return video.path
    return videos[0].path


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
