"""Session manifest read/write helpers."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rime_core.sessions.models import (
    ClinicalMetricSpec,
    ModelSettings,
    Session,
    SessionProvenance,
    SignalConfig,
    SubjectInfo,
    VideoConfig,
    normalize_panel_visibility,
    normalize_session_videos,
)


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

    session = Session(
        id=f"ses-{uuid.uuid4().hex[:8]}",
        name=name,
        version="1.0",
        created=now,
        modified=now,
        session_dir=resolved_dir,
        primary_video=_pick_primary_video(normalized_videos),
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
            model_name: asdict(settings)
            for model_name, settings in session.model_settings.items()
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

    videos = _load_videos(data)
    return Session(
        id=data.get("id", ""),
        name=data.get("name", "Untitled Session"),
        version=data.get("version", "1.0"),
        created=data.get("created", ""),
        modified=data.get("modified", ""),
        session_dir=session_dir,
        primary_video=data.get("primary_video", _pick_primary_video(videos)),
        schema_path=data.get("schema_path", ""),
        schema_name=data.get("schema_name", ""),
        schema_version=data.get("schema_version", ""),
        session_start_utc=data.get("session_start_utc", ""),
        videos=videos,
        signals=_load_signals(data),
        model_paths=_load_model_paths(data),
        model_settings=_load_model_settings(data),
        snap_points=[float(value) for value in data.get("snap_points", [])],
        signal_display_combined=bool(data.get("signal_display_combined", True)),
        panel_visibility=normalize_panel_visibility(data.get("panel_visibility")),
        dock_layout_state=data.get("dock_layout_state", ""),
        clinical_metrics=_load_clinical_metrics(data),
        subject=_load_subject(data),
        rater=data.get("rater", ""),
        provenance=_load_provenance(data),
    )


def _load_videos(data: dict[str, Any]) -> list[VideoConfig]:
    return [
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


def _load_signals(data: dict[str, Any]) -> list[SignalConfig]:
    return [
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
            units=dict(item.get("units", {})),
        )
        for item in data.get("signals", [])
    ]


def _load_model_settings(data: dict[str, Any]) -> dict[str, ModelSettings]:
    return {
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


def _load_model_paths(data: dict[str, Any]) -> dict[str, str]:
    return {
        model_name: path
        for model_name, path in data.get("model_paths", {}).items()
        if isinstance(model_name, str) and isinstance(path, str) and path.strip()
    }


def _load_clinical_metrics(data: dict[str, Any]) -> list[ClinicalMetricSpec]:
    return [
        ClinicalMetricSpec(
            name=item.get("name", ""),
            numerator=[dict(spec) for spec in item.get("numerator", []) if isinstance(spec, dict)],
            denominator_type=item.get("denominator_type", "session"),
            denominator=[dict(spec) for spec in item.get("denominator", []) if isinstance(spec, dict)],
        )
        for item in data.get("clinical_metrics", [])
        if isinstance(item, dict)
    ]


def _load_subject(data: dict[str, Any]) -> SubjectInfo | None:
    if "subject" not in data:
        return None
    raw_subject = data.get("subject", {})
    return SubjectInfo(
        id=raw_subject.get("id", ""),
        condition=raw_subject.get("condition", ""),
        medication_state=raw_subject.get("medication_state", ""),
    )


def _load_provenance(data: dict[str, Any]) -> SessionProvenance:
    raw_provenance = data.get("provenance", {})
    return SessionProvenance(
        origin=raw_provenance.get("origin", "manual"),
        source_files=raw_provenance.get("source_files", []),
        tier_map=raw_provenance.get("tier_map", {}),
        label_map=raw_provenance.get("label_map", {}),
        rules_applied=bool(raw_provenance.get("rules_applied", False)),
        recording_relative_timing_verified=bool(
            raw_provenance.get("recording_relative_timing_verified", False)
        ),
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
