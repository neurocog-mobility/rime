"""External annotation exporters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from math import ceil
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
from typing import Any

import pandas as pd

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.common.intervals import interval_iou, union_duration_ms
from rime_core.coverage import CoverageSpec, compute_coverage
from rime_core.irr import IRRResult, format_irr_value
from rime_core.sessions import Session, SignalConfig
from rime_core.signals import Signal


ExportFn = Callable[[AnnotationStore, Session, Path, bool], None]
_FFMPEG_FALLBACK_PATHS = (
    Path("/opt/homebrew/bin/ffmpeg"),
    Path("/usr/local/bin/ffmpeg"),
)
_BIDS_VERSION = "1.11.1"
_BIDS_TASK_LABEL = "fog"
_BIDS_ENTITY_RE = re.compile(r"[^A-Za-z0-9-]+")
_BIDS_SENSOR_TOKEN_RE = re.compile(r"(sensor-[A-Za-z0-9]+)", re.IGNORECASE)


class ExportError(Exception):
    """Raised when no exporter is available or an export fails."""


@dataclass(frozen=True)
class BidsSignalInput:
    """Pair a loaded signal with the config used to interpret it."""

    config: SignalConfig
    signal: Signal
    tracksys: str


@dataclass(frozen=True)
class BIDSSessionPaths:
    """Canonical BIDS paths for one exported session."""

    output_root: Path
    subject_label: str
    session_label: str
    task_label: str = _BIDS_TASK_LABEL

    @property
    def beh_dir(self) -> Path:
        return self.output_root / f"sub-{self.subject_label}" / f"ses-{self.session_label}" / "beh"

    @property
    def motion_dir(self) -> Path:
        return self.output_root / f"sub-{self.subject_label}" / f"ses-{self.session_label}" / "motion"

    @property
    def derivatives_root(self) -> Path:
        return self.output_root / "derivatives" / "rime"

    @property
    def derivatives_motion_dir(self) -> Path:
        return (
            self.derivatives_root
            / f"sub-{self.subject_label}"
            / f"ses-{self.session_label}"
            / "motion"
        )

    @property
    def events_tsv(self) -> Path:
        return self.beh_dir / self._stem("_events.tsv")

    @property
    def events_json(self) -> Path:
        return self.beh_dir / self._stem("_events.json")

    @property
    def participants_tsv(self) -> Path:
        return self.output_root / "participants.tsv"

    @property
    def participants_json(self) -> Path:
        return self.output_root / "participants.json"

    def motion_tsv(self, tracksys: str) -> Path:
        return self.motion_dir / self._stem(f"_tracksys-{tracksys}_motion.tsv")

    def motion_json(self, tracksys: str) -> Path:
        return self.motion_dir / self._stem(f"_tracksys-{tracksys}_motion.json")

    def channels_tsv(self, tracksys: str) -> Path:
        return self.motion_dir / self._stem(f"_tracksys-{tracksys}_channels.tsv")

    def channels_json(self, tracksys: str) -> Path:
        return self.motion_dir / self._stem(f"_tracksys-{tracksys}_channels.json")

    def clips_parquet(self, tracksys: str) -> Path:
        return self.derivatives_motion_dir / self._stem(
            f"_tracksys-{tracksys}_desc-clips_motion.parquet"
        )

    def clips_json(self, tracksys: str) -> Path:
        return self.derivatives_motion_dir / self._stem(
            f"_tracksys-{tracksys}_desc-clips_motion.json"
        )

    def _stem(self, suffix: str) -> str:
        return f"sub-{self.subject_label}_ses-{self.session_label}_task-{self.task_label}{suffix}"


class ExporterRegistry:
    """Dispatch annotation export by format name."""

    def __init__(self) -> None:
        self._exporters: dict[str, ExportFn] = {}

    @classmethod
    def default(cls) -> ExporterRegistry:
        registry = cls()
        registry.register("parquet", export_parquet)
        registry.register("bids", export_bids_events)
        return registry

    def register(self, format_name: str, fn: ExportFn) -> None:
        """Register an exporter for one format."""
        self._exporters[format_name.casefold()] = fn

    def supported_formats(self) -> list[str]:
        """Return registered export formats in sorted order."""
        return sorted(self._exporters)

    def export(
        self,
        format_name: str,
        store: AnnotationStore,
        session: Session,
        output_path: Path,
        include_ghost: bool = False,
    ) -> None:
        """Dispatch to the registered exporter for one format."""
        exporter = self._exporters.get(format_name.casefold())
        if exporter is None:
            raise ExportError(f"No exporter registered for format '{format_name}'")
        try:
            exporter(store, session, output_path, include_ghost)
        except ExportError:
            raise
        except Exception as exc:  # pragma: no cover - exercised via exporter tests
            raise ExportError(f"Failed to export '{format_name}' to {output_path}: {exc}") from exc


def export_parquet(
    store: AnnotationStore,
    session: Session,
    output_path: Path,
    include_ghost: bool = False,
) -> None:
    """Export annotations to benchmark-ready Parquet."""
    export_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    subject_id = session.subject.id if session.subject is not None else ""
    rows: list[dict[str, object]] = []

    for annotation in _filtered_annotations(store, include_ghost=include_ghost):
        rows.append(
            {
                "session_id": session.id,
                "subject_id": subject_id,
                "session_name": session.name,
                "annotation_id": annotation.id,
                "lane": annotation.lane,
                "label": annotation.label,
                "event_type": annotation.event_type,
                "start_ms": annotation.start_ms,
                "end_ms": annotation.end_ms,
                "duration_ms": annotation.duration_ms,
                "source": annotation.source,
                "ghost": annotation.ghost,
                "confidence": annotation.confidence,
                "export_timestamp": export_timestamp,
                "rater": session.rater,
                "human_modified": annotation.human_modified,
                "origin_confidence": annotation.origin_confidence,
                "origin_start_ms": annotation.origin_start_ms,
                "origin_end_ms": annotation.origin_end_ms,
            }
        )

    df = pd.DataFrame(
        rows,
        columns=[
            "session_id",
            "subject_id",
            "session_name",
            "annotation_id",
            "lane",
            "label",
            "event_type",
            "start_ms",
            "end_ms",
            "duration_ms",
            "source",
            "ghost",
            "confidence",
            "export_timestamp",
            "rater",
            "human_modified",
            "origin_confidence",
            "origin_start_ms",
            "origin_end_ms",
        ],
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def bids_session_paths(output_root: Path, session: Session) -> BIDSSessionPaths:
    """Return canonical BIDS paths for one session."""
    subject_id = session.subject.id if session.subject is not None else ""
    return BIDSSessionPaths(
        output_root=Path(output_root),
        subject_label=sanitize_bids_entity_value(
            _strip_bids_entity_prefix(subject_id, "sub"),
            fallback="unknown",
        ),
        session_label=sanitize_bids_entity_value(
            _strip_bids_entity_prefix(session.id, "ses"),
            fallback="session",
        ),
    )


def sanitize_bids_entity_value(value: str, *, fallback: str) -> str:
    """Normalize one BIDS entity label to alphanumeric and hyphens."""
    cleaned = value.strip().replace("_", "-").replace(" ", "-")
    cleaned = _BIDS_ENTITY_RE.sub("-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or fallback


def _strip_bids_entity_prefix(value: str, entity: str) -> str:
    prefix = f"{entity}-"
    if value.casefold().startswith(prefix.casefold()):
        return value[len(prefix) :]
    return value


def export_bids_events(
    store: AnnotationStore,
    session: Session,
    output_path: Path,
    include_ghost: bool = False,
) -> None:
    """Export annotations as a BIDS-compatible *_events.tsv file."""
    _require_bids_timing_verified(session)
    rows: list[dict[str, object]] = []
    for annotation in _filtered_annotations(store, include_ghost=include_ghost):
        rows.append(
            {
                "onset": _round_bids_seconds(annotation.start_ms),
                "duration": _round_bids_seconds(annotation.duration_ms),
                "trial_type": annotation.label,
                "rime_lane": annotation.lane,
                "rime_event_type": annotation.event_type,
                "rime_source": annotation.source,
                "rime_rater": session.rater or None,
                "rime_human_modified": annotation.human_modified,
                "rime_confidence": annotation.confidence,
                "rime_origin_onset": _optional_bids_seconds(annotation.origin_start_ms),
                "rime_origin_offset": _optional_bids_seconds(annotation.origin_end_ms),
                "rime_origin_confidence": annotation.origin_confidence,
                "rime_annotation_id": annotation.id,
            }
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "onset",
            "duration",
            "trial_type",
            "rime_lane",
            "rime_event_type",
            "rime_source",
            "rime_rater",
            "rime_human_modified",
            "rime_confidence",
            "rime_origin_onset",
            "rime_origin_offset",
            "rime_origin_confidence",
            "rime_annotation_id",
        ],
    )
    if not frame.empty:
        frame = frame.sort_values("onset", kind="stable").reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, sep="\t", index=False, na_rep="n/a")


def export_bids_events_sidecar(output_path: Path) -> None:
    """Write the *_events.json metadata sidecar."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "onset": {"Description": "Event onset in seconds from session start."},
        "duration": {"Description": "Event duration in seconds."},
        "trial_type": {
            "Description": "FOG annotation label (e.g. Active Freezing, Festination)."
        },
        "rime_lane": {"Description": "Annotation lane within the RIME timeline."},
        "rime_event_type": {
            "Description": "Annotation geometry.",
            "Levels": {
                "interval": "Start-to-end interval.",
                "point": "Instantaneous point event.",
            },
        },
        "rime_source": {
            "Description": (
                "Annotation provenance. Fixed values listed in Levels;"
                " dynamic values follow the pattern 'corrected:<model>' (Ghost Track accepted/adjusted)"
                " or 'model:<model>' (raw Ghost Track, include_ghost=true only)."
            ),
            "Levels": {
                "manual": "Created by a human rater with no model involvement.",
                "elan_import": "Imported from an ELAN .eaf file.",
                "rule:auto_create": "Generated automatically by a deterministic schema rule.",
            },
        },
        "rime_rater": {
            "Description": "Identifier of the human rater who created or accepted this annotation."
        },
        "rime_human_modified": {
            "Description": "True if boundaries were adjusted after model suggestion."
        },
        "rime_confidence": {
            "Description": "Model confidence at annotation onset, if model-assisted; n/a otherwise."
        },
        "rime_origin_onset": {
            "Description": (
                "Original model-predicted onset (seconds) before human adjustment; "
                "n/a for manual annotations."
            )
        },
        "rime_origin_offset": {
            "Description": (
                "Original model-predicted offset (seconds) before human adjustment; "
                "n/a for manual annotations."
            )
        },
        "rime_origin_confidence": {
            "Description": "Model confidence of the original prediction; n/a for manual annotations."
        },
        "rime_annotation_id": {
            "Description": "Unique annotation identifier; join key to the RIME signal clip exports."
        },
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_bids_dataset_descriptions(output_root: Path) -> int:
    """Write raw and derivative dataset_description.json files if absent."""
    output_root = Path(output_root)
    written = 0
    raw_path = output_root / "dataset_description.json"
    derivative_root = output_root / "derivatives" / "rime"
    derivative_path = derivative_root / "dataset_description.json"
    derivative_root.mkdir(parents=True, exist_ok=True)

    raw_payload = {
        "Name": "RIME annotation export",
        "BIDSVersion": _BIDS_VERSION,
        "GeneratedBy": [{"Name": "RIME", "Version": _rime_version()}],
        "DatasetType": "raw",
    }
    derivative_payload = {
        "Name": "RIME derived clips",
        "BIDSVersion": _BIDS_VERSION,
        "DatasetType": "derivative",
        "GeneratedBy": [{"Name": "RIME", "Version": _rime_version()}],
        "PipelineDescription": {"Name": "RIME", "Version": _rime_version()},
        "SourceDatasets": [{"URL": ".."}],
    }

    if _should_refresh_dataset_description(raw_path, raw_payload):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(raw_payload, indent=2), encoding="utf-8")
        written += 1

    if _should_refresh_dataset_description(derivative_path, derivative_payload):
        derivative_path.write_text(json.dumps(derivative_payload, indent=2), encoding="utf-8")
        written += 1

    return written


def write_bids_participants(output_root: Path, session: Session) -> int:
    """Write or update participants.tsv and participants.json for the exported subject."""
    output_root = Path(output_root)
    paths = bids_session_paths(output_root, session)
    participant_id = f"sub-{paths.subject_label}"
    condition = session.subject.condition if session.subject is not None else None

    frame = pd.DataFrame(
        [{"participant_id": participant_id, "condition": condition}],
        columns=["participant_id", "condition"],
    )
    written = 0

    if paths.participants_tsv.exists():
        existing = pd.read_csv(paths.participants_tsv, sep="\t")
        existing = existing[existing["participant_id"] != participant_id]
        frame = pd.concat([existing, frame], ignore_index=True)

    frame = frame.sort_values("participant_id", kind="stable").reset_index(drop=True)
    paths.participants_tsv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(paths.participants_tsv, sep="\t", index=False, na_rep="n/a")
    written += 1

    participants_json = {
        "participant_id": {
            "Description": "Participant identifier of the form sub-<label>."
        },
        "condition": {
            "Description": "Participant condition or cohort label as stored in the RIME session."
        },
    }
    paths.participants_json.write_text(json.dumps(participants_json, indent=2), encoding="utf-8")
    written += 1
    return written


def build_bids_signal_inputs(session: Session, signals: list[Signal]) -> list[BidsSignalInput]:
    """Pair loaded signals with persisted signal configs for BIDS export."""
    if not signals:
        return []

    matches = _match_signal_configs(session.signals, signals)
    if not matches:
        raise ExportError("Could not match any loaded signals to session signal configs.")
    if len(matches) != len(signals):
        matched_names = {id(signal) for _, signal in matches}
        unmatched = [signal.name or "signal" for signal in signals if id(signal) not in matched_names]
        raise ExportError(
            "Could not match every loaded signal to a session config: " + ", ".join(unmatched)
        )

    raw_tracksys = [_preferred_tracksys_label(config, signal) for config, signal in matches]
    unique_tracksys = _unique_bids_labels(raw_tracksys, fallback="signal")
    return [
        BidsSignalInput(config=config, signal=signal, tracksys=tracksys)
        for (config, signal), tracksys in zip(matches, unique_tracksys, strict=False)
    ]


def export_bids_motion(
    session: Session,
    signal_inputs: list[BidsSignalInput],
    output_root: Path,
) -> int:
    """Export full-session signals as BIDS motion recordings."""
    _require_bids_timing_verified(session)
    if not signal_inputs:
        return 0

    paths = bids_session_paths(Path(output_root), session)
    file_count = 0
    for item in signal_inputs:
        rows = _motion_channel_rows(item)
        columns = [row["name"] for row in rows]
        data = {name: _motion_column_values(item, name) for name in columns}
        frame = pd.DataFrame(data, columns=columns)

        motion_path = paths.motion_tsv(item.tracksys)
        channels_path = paths.channels_tsv(item.tracksys)
        sidecar_path = paths.motion_json(item.tracksys)
        motion_path.parent.mkdir(parents=True, exist_ok=True)

        frame.to_csv(
            motion_path,
            sep="\t",
            index=False,
            header=False,
            na_rep="n/a",
            float_format="%.6f",
        )
        export_bids_channels(item, channels_path)
        sidecar_path.write_text(
            json.dumps(_motion_sidecar(item, rows), indent=2),
            encoding="utf-8",
        )
        file_count += 3
    return file_count


def export_bids_channels(item: BidsSignalInput, output_path: Path) -> None:
    """Write *_channels.tsv for one BIDS motion file."""
    rows = _motion_channel_rows(item)
    frame = pd.DataFrame(
        rows,
        columns=["name", "component", "type", "tracked_point", "units"],
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, sep="\t", index=False, na_rep="n/a")


def export_bids_signal_clips(
    store: AnnotationStore,
    session: Session,
    signal_inputs: list[BidsSignalInput],
    output_root: Path,
    *,
    padding_ms: float = 0.0,
    include_ghost: bool = False,
    lanes: list[str] | None = None,
) -> int:
    """Export one derivative clips Parquet and JSON sidecar per signal."""
    _require_bids_timing_verified(session)
    annotations = _filtered_annotations(
        store,
        include_ghost=include_ghost,
        lanes=lanes,
        include_points=False,
    )
    if not annotations or not signal_inputs:
        return 0

    paths = bids_session_paths(Path(output_root), session)
    file_count = 0
    for item in signal_inputs:
        frame = _build_signal_clip_frame(item.signal, annotations, padding_ms=padding_ms)
        if not frame.empty:
            frame = frame.rename(columns={"time_offset_ms": "time_offset"})
            frame["time_offset"] = frame["time_offset"].map(_round_bids_seconds)
        else:
            frame = pd.DataFrame(columns=["annotation_id", "time_offset", *item.signal.channels])

        parquet_path = paths.clips_parquet(item.tracksys)
        sidecar_path = paths.clips_json(item.tracksys)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(parquet_path, index=False)
        sidecar_path.write_text(
            json.dumps(_clips_sidecar(item, padding_ms=padding_ms), indent=2),
            encoding="utf-8",
        )
        file_count += 2
    return file_count


def export_bids_dataset(
    store: AnnotationStore,
    session: Session,
    signals: list[Signal],
    output_root: Path | str,
    *,
    padding_ms: float = 0.0,
    include_ghost: bool = False,
    lanes: list[str] | None = None,
    export_motion: bool = True,
    export_clips: bool = True,
) -> int:
    """Export one session as a BIDS root with optional derivative clips."""
    _require_bids_timing_verified(session)
    output_root = Path(output_root)
    paths = bids_session_paths(output_root, session)
    file_count = write_bids_dataset_descriptions(output_root)
    file_count += write_bids_participants(output_root, session)
    export_bids_events(store, session, paths.events_tsv, include_ghost=include_ghost)
    export_bids_events_sidecar(paths.events_json)
    file_count += 2

    signal_inputs: list[BidsSignalInput] = []
    if signals and (export_motion or export_clips):
        signal_inputs = build_bids_signal_inputs(session, signals)
    if export_motion:
        file_count += export_bids_motion(session, signal_inputs, output_root)
    if export_clips:
        file_count += export_bids_signal_clips(
            store,
            session,
            signal_inputs,
            output_root,
            padding_ms=padding_ms,
            include_ghost=include_ghost,
            lanes=lanes,
        )
    return file_count


def _match_signal_configs(
    configs: list[SignalConfig],
    signals: list[Signal],
) -> list[tuple[SignalConfig, Signal]]:
    matched: list[tuple[SignalConfig, Signal]] = []
    used_signal_indexes: set[int] = set()

    for candidate_names in (
        lambda config: [config.name] if config.name else [],
        lambda config: [Path(config.path).stem],
    ):
        for config in configs:
            if any(existing[0] is config for existing in matched):
                continue
            names = [name for name in candidate_names(config) if name]
            for index, signal in enumerate(signals):
                if index in used_signal_indexes:
                    continue
                if signal.name in names:
                    matched.append((config, signal))
                    used_signal_indexes.add(index)
                    break

    remaining_configs = [config for config in configs if not any(existing[0] is config for existing in matched)]
    remaining_signals = [
        (index, signal) for index, signal in enumerate(signals) if index not in used_signal_indexes
    ]
    if len(remaining_configs) == len(remaining_signals):
        for config, (_, signal) in zip(remaining_configs, remaining_signals, strict=False):
            matched.append((config, signal))
    return matched


def _unique_bids_labels(values: list[str], *, fallback: str) -> list[str]:
    used: dict[str, int] = {}
    labels: list[str] = []
    for value in values:
        base = sanitize_bids_entity_value(value, fallback=fallback)
        count = used.get(base, 0) + 1
        used[base] = count
        labels.append(base if count == 1 else f"{base}-{count}")
    return labels


def _preferred_tracksys_label(config: SignalConfig, signal: Signal) -> str:
    candidates = [config.name, Path(config.path).stem, signal.name]
    for candidate in candidates:
        if not candidate:
            continue
        sensor_match = _BIDS_SENSOR_TOKEN_RE.search(candidate)
        if sensor_match is not None:
            return sensor_match.group(1).lower()
    for candidate in candidates:
        if candidate and len(candidate.strip()) <= 32:
            return candidate
    return Path(config.path).stem or signal.name or "signal"


def _motion_channel_rows(item: BidsSignalInput) -> list[dict[str, str]]:
    tracked_point = item.config.name or item.tracksys
    rows: list[dict[str, str]] = []
    for channel in item.config.channels or item.signal.channels:
        channel_type = _infer_motion_channel_type(channel)
        rows.append(
            {
                "name": channel,
                "component": _infer_motion_component(channel),
                "type": channel_type,
                "tracked_point": tracked_point,
                "units": _infer_motion_units(item.config, channel, channel_type),
            }
        )
    return rows


def _motion_column_values(item: BidsSignalInput, channel_name: str):
    return item.signal.get_channel(channel_name)


def _motion_sidecar(item: BidsSignalInput, rows: list[dict[str, str]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["type"]] = counts.get(row["type"], 0) + 1

    payload: dict[str, Any] = {
        "TaskName": _BIDS_TASK_LABEL,
        "TaskDescription": "Freezing of gait annotation session.",
        "SamplingFrequency": float(item.signal.sampling_rate_hz),
        "TrackingSystemName": item.config.name or item.tracksys,
        "MotionChannelCount": len(rows),
        "TrackedPointsCount": 1,
        "MissingValues": "n/a",
    }
    count_field_map = {
        "ACCEL": "ACCELChannelCount",
        "ANGACCEL": "ANGACCELChannelCount",
        "GYRO": "GYROChannelCount",
        "JNTANG": "JNTANGChannelCount",
        "LATENCY": "LATENCYChannelCount",
        "MAGN": "MAGNChannelCount",
        "MISC": "MISCChannelCount",
        "ORNT": "ORNTChannelCount",
        "POS": "POSChannelCount",
        "VEL": "VELChannelCount",
    }
    for channel_type, field_name in count_field_map.items():
        if channel_type in counts:
            payload[field_name] = counts[channel_type]
    return payload


def _clips_sidecar(item: BidsSignalInput, *, padding_ms: float) -> dict[str, Any]:
    return {
        "SamplingFrequency": float(item.signal.sampling_rate_hz),
        "TaskName": _BIDS_TASK_LABEL,
        "Description": (
            "Annotation-aligned signal clips. Each row is one sample from a windowed segment "
            "centred on an annotation event. Join on annotation_id to the events.tsv export "
            "via the rime_annotation_id column."
        ),
        "PaddingSeconds": _round_bids_seconds(padding_ms),
        "TrackedPointsCount": 1,
        "TrackingSystemName": item.config.name or item.tracksys,
    }


def _infer_motion_channel_type(channel_name: str) -> str:
    prefix = channel_name.casefold().split("_", 1)[0]
    if prefix == "acc":
        return "ACCEL"
    if prefix in {"angacc", "angaccel"}:
        return "ANGACCEL"
    if prefix in {"gyr", "gyro"}:
        return "GYRO"
    if prefix in {"jntang", "jointangle"}:
        return "JNTANG"
    if prefix == "latency":
        return "LATENCY"
    if prefix in {"mag", "magn"}:
        return "MAGN"
    if prefix in {"ornt", "quat"}:
        return "ORNT"
    if prefix in {"pos", "position"}:
        return "POS"
    if prefix in {"vel", "velocity"}:
        return "VEL"
    return "MISC"


def _infer_motion_component(channel_name: str) -> str:
    suffix = channel_name.casefold().split("_")[-1]
    if suffix in {"x", "y", "z", "quat_x", "quat_y", "quat_z", "quat_w"}:
        return suffix
    if suffix in {"qx", "qy", "qz", "qw"}:
        return f"quat_{suffix[1:]}"
    if "quat_w" in channel_name.casefold():
        return "quat_w"
    if "quat_x" in channel_name.casefold():
        return "quat_x"
    if "quat_y" in channel_name.casefold():
        return "quat_y"
    if "quat_z" in channel_name.casefold():
        return "quat_z"
    return "x"


def _infer_motion_units(config: SignalConfig, channel_name: str, channel_type: str) -> str:
    if channel_name in config.units and config.units[channel_name]:
        return config.units[channel_name]
    if channel_type == "ACCEL":
        return "m/s^2"
    if channel_type in {"ANGACCEL"}:
        return "rad/s^2"
    if channel_type == "GYRO":
        return "rad/s"
    if channel_type == "JNTANG":
        return "rad"
    if channel_type == "LATENCY":
        return "s"
    if channel_type == "MAGN":
        return "T"
    if channel_type == "ORNT":
        return "n/a"
    if channel_type == "POS":
        return "m"
    if channel_type == "VEL":
        return "m/s"
    return "n/a"


def _round_bids_seconds(value_ms: float | int) -> float:
    return round(float(value_ms) / 1000.0, 4)


def _optional_bids_seconds(value_ms: float | int | None) -> float | None:
    if value_ms is None:
        return None
    return _round_bids_seconds(value_ms)


def _require_bids_timing_verified(session: Session) -> None:
    if session.provenance.recording_relative_timing_verified:
        return
    raise ExportError(
        "BIDS export requires verified recording-relative annotation timing for this session."
    )


def _rime_version() -> str:
    try:
        return package_version("neurocog-rime-core")
    except PackageNotFoundError:
        pyproject_path = Path(__file__).resolve().parents[3] / "pyproject.toml"
        try:
            with pyproject_path.open("rb") as handle:
                payload = tomllib.load(handle)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            return "unknown"
        return str(payload.get("project", {}).get("version", "unknown"))


def _should_refresh_dataset_description(path: Path, expected: dict[str, Any]) -> bool:
    if not path.exists():
        return True
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if existing.get("BIDSVersion") != expected.get("BIDSVersion"):
        return True
    if existing.get("DatasetType") != expected.get("DatasetType"):
        return True
    existing_generated = existing.get("GeneratedBy", [])
    expected_generated = expected.get("GeneratedBy", [])
    if existing_generated != expected_generated:
        return True
    if expected.get("PipelineDescription") and existing.get("PipelineDescription") != expected.get(
        "PipelineDescription"
    ):
        return True
    return False


def derive_matched_episode_interval(
    ann_a: Annotation,
    ann_b: Annotation,
    mode: str,
) -> tuple[float, float] | None:
    """Derive one interval from a matched annotation pair."""
    if mode == "average":
        return (
            (ann_a.start_ms + ann_b.start_ms) / 2.0,
            (ann_a.end_ms + ann_b.end_ms) / 2.0,
        )
    if mode == "intersection":
        start_ms = max(ann_a.start_ms, ann_b.start_ms)
        end_ms = min(ann_a.end_ms, ann_b.end_ms)
        return (start_ms, end_ms) if start_ms < end_ms else None
    if mode == "union":
        return (
            min(ann_a.start_ms, ann_b.start_ms),
            max(ann_a.end_ms, ann_b.end_ms),
        )
    if mode == "rater_a":
        return ann_a.start_ms, ann_a.end_ms
    if mode == "rater_b":
        return ann_b.start_ms, ann_b.end_ms
    raise ValueError(f"Unsupported matched-episode mode: {mode}")


def export_matched_episode_parquet(
    result: IRRResult,
    session_a: Session,
    session_b: Session,
    output_path: Path | str,
    *,
    lane: str | None = None,
    source_a: str | None = None,
    source_b: str | None = None,
    mode: str,
) -> None:
    """Export matched pairs as one derived row per pair using the selected mode."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    export_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    subject_id = session_a.subject.id if session_a.subject is not None else ""
    rows: list[dict[str, object]] = []

    for ann_a, ann_b in result.matched_episodes:
        interval = derive_matched_episode_interval(ann_a, ann_b, mode)
        if interval is None:
            continue
        start_ms, end_ms = interval
        rows.append(
            {
                "subject_id": subject_id,
                "lane_filter": lane,
                "source_a_filter": source_a,
                "source_b_filter": source_b,
                "matched_episode_mode": mode,
                "session_a_id": session_a.id,
                "session_a_name": session_a.name,
                "annotation_a_id": ann_a.id,
                "rater_a": session_a.rater,
                "rater_a_start_ms": ann_a.start_ms,
                "rater_a_end_ms": ann_a.end_ms,
                "session_b_id": session_b.id,
                "session_b_name": session_b.name,
                "annotation_b_id": ann_b.id,
                "rater_b": session_b.rater,
                "rater_b_start_ms": ann_b.start_ms,
                "rater_b_end_ms": ann_b.end_ms,
                "lane": ann_a.lane,
                "label": ann_a.label,
                "event_type": ann_a.event_type,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
                "source": f"matched:{mode}",
                "onset_agreement_ms": abs(ann_a.start_ms - ann_b.start_ms),
                "offset_agreement_ms": abs(ann_a.end_ms - ann_b.end_ms),
                "episode_iou": interval_iou(
                    ann_a.start_ms,
                    ann_a.end_ms,
                    ann_b.start_ms,
                    ann_b.end_ms,
                ),
                "export_timestamp": export_timestamp,
            }
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "subject_id",
            "lane_filter",
            "source_a_filter",
            "source_b_filter",
            "matched_episode_mode",
            "session_a_id",
            "session_a_name",
            "annotation_a_id",
            "rater_a",
            "rater_a_start_ms",
            "rater_a_end_ms",
            "session_b_id",
            "session_b_name",
            "annotation_b_id",
            "rater_b",
            "rater_b_start_ms",
            "rater_b_end_ms",
            "lane",
            "label",
            "event_type",
            "start_ms",
            "end_ms",
            "duration_ms",
            "source",
            "onset_agreement_ms",
            "offset_agreement_ms",
            "episode_iou",
            "export_timestamp",
        ],
    )
    frame.to_parquet(output, index=False)


def export_signal_clips(
    store: AnnotationStore,
    session: Session,
    signals: list[Signal],
    output_dir: Path | str,
    *,
    padding_ms: float = 0.0,
    include_ghost: bool = False,
    lanes: list[str] | None = None,
    rows_per_file: int = 1_000_000,
) -> int:
    """Export windowed signal clips aligned to annotation onset."""
    del session  # reserved for future metadata-driven naming
    output_root = Path(output_dir)
    annotations = _filtered_annotations(
        store,
        include_ghost=include_ghost,
        lanes=lanes,
        include_points=False,
    )
    if not annotations or not signals:
        return 0

    output_root.mkdir(parents=True, exist_ok=True)
    file_count = 0
    used_names: dict[str, int] = {}

    for signal in signals:
        signal_name = _unique_signal_name(signal.name or "signal", used_names)
        chunk_size = _signal_clip_chunk_size(
            annotations,
            signal.sampling_rate_hz,
            padding_ms=padding_ms,
            rows_per_file=rows_per_file,
        )
        for chunk_index, chunk in enumerate(_chunked(annotations, chunk_size), start=1):
            frame = _build_signal_clip_frame(signal, chunk, padding_ms=padding_ms)
            suffix = (
                ".parquet"
                if chunk_size >= len(annotations)
                else f"_part{chunk_index:03d}.parquet"
            )
            frame.to_parquet(output_root / f"clips_{signal_name}{suffix}", index=False)
            file_count += 1

    return file_count


def export_video_clips(
    store: AnnotationStore,
    session: Session,
    output_dir: Path | str,
    *,
    padding_ms: float = 500.0,
    include_ghost: bool = False,
    lanes: list[str] | None = None,
    video_role: str = "primary",
) -> int:
    """Export video segments aligned to annotations via ffmpeg."""
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        raise ExportError("ffmpeg not found on PATH - install ffmpeg to export video clips.")

    annotations = _filtered_annotations(
        store,
        include_ghost=include_ghost,
        lanes=lanes,
        include_points=False,
    )
    if not annotations:
        return 0

    videos = _resolve_export_videos(session, video_role)
    if not videos:
        return 0

    clip_dir = Path(output_dir) / "clips_video"
    clip_dir.mkdir(parents=True, exist_ok=True)

    file_count = 0
    for video in videos:
        video_path = session.get_video_path(video)
        for annotation in annotations:
            start_s = max(0.0, (annotation.start_ms - padding_ms - video.offset_ms) / 1000.0)
            end_s = (annotation.end_ms + padding_ms - video.offset_ms) / 1000.0
            if end_s <= start_s:
                continue

            prefix = f"{_safe_stem(video.role)}_" if video_role == "all" else ""
            label = _safe_stem(annotation.label)
            start_text = f"{int(round(annotation.start_ms))}ms"
            output_path = clip_dir / f"{prefix}{annotation.id}_{label}_{start_text}.mp4"
            try:
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-ss",
                        f"{start_s:.3f}",
                        "-to",
                        f"{end_s:.3f}",
                        "-i",
                        str(video_path),
                        "-c",
                        "copy",
                        str(output_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError as exc:
                raise ExportError(
                    f"ffmpeg failed for annotation '{annotation.id}' on video '{video_path}'"
                ) from exc
            file_count += 1

    return file_count


def export_session_report(
    store: AnnotationStore,
    session: Session,
    output_path: Path | str,
    *,
    duration_ms: float,
) -> None:
    """Export a TSV session report with annotation summary and clinical metrics."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    subject_id = session.subject.id if session.subject is not None else ""
    condition = session.subject.condition if session.subject is not None else ""
    duration_text = _format_duration(duration_ms)

    lines = [
        "# RIME Session Report",
        f"# Session:\t{session.name}",
        f"# Rater:\t{session.rater}",
        f"# Subject:\t{subject_id}",
        f"# Condition:\t{condition}",
        f"# Duration:\t{duration_text} ({duration_ms:,.0f} ms)",
        f"# Generated:\t{generated}",
        "",
        "Lane\tLabel\tEpisodes\tTotal_ms\tMean_ms\tPct_of_session",
    ]

    for row in _annotation_summary_rows(store, duration_ms):
        lines.append("\t".join(row))

    lines.extend(
        [
            "",
            "Metric\tValue_pct\tNumerator_ms\tNumerator_episodes\tDenominator_ms\tDenominator_episodes",
        ]
    )

    for metric in session.clinical_metrics:
        numerator_specs = [CoverageSpec(**spec) for spec in metric.numerator]
        denominator_specs = (
            None
            if metric.denominator_type == "session"
            else [CoverageSpec(**spec) for spec in metric.denominator]
        )
        result = compute_coverage(
            store,
            numerator_specs,
            denominator=denominator_specs,
            session_duration_ms=duration_ms,
        )
        denominator_episodes = (
            "—" if result.denominator_episodes < 0 else str(result.denominator_episodes)
        )
        value_pct = "—" if result.denominator_ms <= 0 else f"{result.percent:.1f}"
        lines.append(
            "\t".join(
                [
                    metric.name,
                    value_pct,
                    f"{result.numerator_ms:.0f}",
                    str(result.numerator_episodes),
                    f"{result.denominator_ms:.0f}",
                    denominator_episodes,
                ]
            )
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_irr_report(
    result: IRRResult,
    session_a: Session,
    session_b: Session,
    output_path: Path | str,
    *,
    lane: str | None = None,
    source_a: str | None = None,
    source_b: str | None = None,
) -> None:
    """Export an IRR TSV report."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lane_text = lane if lane is not None else "(all lanes)"
    rater_a = session_a.rater or "(no rater)"
    rater_b = session_b.rater or "(no rater)"
    n_matched = len(result.matched_episodes)
    n_unmatched_a = len(result.unmatched_a)
    n_unmatched_b = len(result.unmatched_b)
    total_a = n_matched + n_unmatched_a
    total_b = n_matched + n_unmatched_b
    denom = max(total_a, total_b)
    match_rate = n_matched / denom if denom > 0 else float("nan")
    lines = [
        "# RIME IRR Report",
        f"# Session A:\t{session_a.name}  (Rater: {rater_a})",
        f"# Session B:\t{session_b.name}  (Rater: {rater_b})",
        f"# Lane:\t{lane_text}",
        f"# Source A:\t{source_a or '(all accepted sources)'}",
        f"# Source B:\t{source_b or '(all accepted sources)'}",
        f"# Generated:\t{generated}",
        "",
        "Metric\tValue",
        f"Cohen's κ\t{format_irr_value(result.cohens_kappa)}",
        f"Match rate\t{format_irr_value(match_rate, percent=True)}%",
        f"Set IoU\t{format_irr_value(result.set_iou, percent=True)}%",
        f"Matched episodes\t{n_matched}",
        f"Unmatched (A only)\t{n_unmatched_a}",
        f"Unmatched (B only)\t{n_unmatched_b}",
        "",
        "Label\tκ\tMatch rate\tSet IoU\tMatched\tA-only\tB-only",
    ]
    for label in sorted(result.per_label):
        item = result.per_label[label]
        total_a = item.matched + item.unmatched_a
        total_b = item.matched + item.unmatched_b
        denom = max(total_a, total_b)
        match_rate = item.matched / denom if denom > 0 else float("nan")
        lines.append(
            "\t".join(
                [
                    item.label,
                    format_irr_value(item.cohens_kappa),
                    f"{format_irr_value(match_rate, percent=True)}%",
                    f"{format_irr_value(item.set_iou, percent=True)}%",
                    str(item.matched),
                    str(item.unmatched_a),
                    str(item.unmatched_b),
                ]
            )
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _annotation_summary_rows(
    store: AnnotationStore,
    duration_ms: float,
) -> list[list[str]]:
    rows: list[list[str]] = []
    annotations = [annotation for annotation in store.all() if not annotation.ghost]
    lanes = sorted({annotation.lane for annotation in annotations})
    for lane in lanes:
        lane_annotations = [annotation for annotation in annotations if annotation.lane == lane]
        rows.append(_summary_row(lane, "(all)", lane_annotations, duration_ms))
        labels = sorted({annotation.label for annotation in lane_annotations})
        for label in labels:
            label_annotations = [annotation for annotation in lane_annotations if annotation.label == label]
            rows.append(_summary_row(lane, label, label_annotations, duration_ms))
    return rows


def _summary_row(
    lane: str,
    label: str,
    annotations,
    duration_ms: float,
) -> list[str]:
    total_ms = union_duration_ms(
        [
            (annotation.start_ms, annotation.end_ms)
            for annotation in annotations
            if annotation.event_type != "point"
        ]
    )
    episodes = len(annotations)
    mean_ms = 0.0 if episodes == 0 else total_ms / episodes
    pct = 0.0 if duration_ms <= 0 else (total_ms / duration_ms) * 100.0
    return [
        lane,
        label,
        str(episodes),
        f"{total_ms:.0f}",
        f"{mean_ms:.0f}",
        f"{pct:.1f}",
    ]


def _format_duration(duration_ms: float) -> str:
    total_seconds = max(0, int(round(duration_ms / 1000.0)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds:02d}s"


def _resolve_export_videos(session: Session, video_role: str):
    if video_role == "primary":
        return [video for video in session.videos if video.path == session.primary_video][:1]
    if video_role == "all":
        return list(session.videos)
    raise ExportError(f"Unsupported video export role '{video_role}'")


def _find_ffmpeg() -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    for candidate in _FFMPEG_FALLBACK_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _filtered_annotations(
    store: AnnotationStore,
    *,
    include_ghost: bool = False,
    lanes: list[str] | None = None,
    include_points: bool = True,
) -> list[Annotation]:
    lane_filter = {lane.casefold() for lane in lanes} if lanes else None
    annotations: list[Annotation] = []
    for annotation in store.all():
        if annotation.ghost and not include_ghost:
            continue
        if lane_filter is not None and annotation.lane.casefold() not in lane_filter:
            continue
        if not include_points and annotation.event_type == "point":
            continue
        annotations.append(annotation)
    return annotations


def _signal_clip_chunk_size(
    annotations: list[Annotation],
    sampling_rate_hz: float,
    *,
    padding_ms: float,
    rows_per_file: int,
) -> int:
    if rows_per_file <= 0:
        return len(annotations)

    estimated_rows = sum(
        max(0, round((annotation.duration_ms + (2.0 * padding_ms)) * sampling_rate_hz / 1000.0))
        for annotation in annotations
    )
    if estimated_rows <= rows_per_file:
        return len(annotations)

    chunk_count = max(1, ceil(estimated_rows / rows_per_file))
    return max(1, ceil(len(annotations) / chunk_count))


def _build_signal_clip_frame(
    signal: Signal,
    annotations: list[Annotation],
    *,
    padding_ms: float,
) -> pd.DataFrame:
    time_ms = signal.get_time_ms()
    channel_data = {channel: signal.get_channel(channel) for channel in signal.channels}
    frames: list[pd.DataFrame] = []

    for annotation in annotations:
        start_ms = annotation.start_ms - padding_ms
        end_ms = annotation.end_ms + padding_ms
        mask = (time_ms >= start_ms) & (time_ms <= end_ms)
        if not mask.any():
            continue
        clip: dict[str, object] = {
            "annotation_id": [annotation.id] * int(mask.sum()),
            "time_offset_ms": time_ms[mask] - annotation.start_ms,
        }
        for channel in signal.channels:
            clip[channel] = channel_data[channel][mask]
        frames.append(pd.DataFrame(clip))

    if not frames:
        return pd.DataFrame(columns=["annotation_id", "time_offset_ms", *signal.channels])
    return pd.concat(frames, ignore_index=True)


def _unique_signal_name(base_name: str, used_names: dict[str, int]) -> str:
    stem = _safe_stem(base_name)
    if stem not in used_names:
        used_names[stem] = 1
        return stem
    used_names[stem] += 1
    return f"{stem}_{used_names[stem]:02d}"


def _safe_stem(name: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in name.strip())
    return cleaned.strip("_") or "signal"


def _chunked(items: list[Annotation], chunk_size: int) -> list[list[Annotation]]:
    if chunk_size <= 0:
        return [items]
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]
