"""Session value types and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


MAX_SESSION_VIDEOS = 2

DEFAULT_PANEL_VISIBILITY: dict[str, bool] = {
    "annotation_list": True,
    "model_runner": True,
    "model_evaluation": True,
    "clinical_outcomes": True,
    "irr_panel": True,
}


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
    units: dict[str, str] = field(default_factory=dict)


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
    recording_relative_timing_verified: bool = False


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
