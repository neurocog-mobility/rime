"""External annotation exporters."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from math import ceil
import os
from pathlib import Path
import shutil
import subprocess

import pandas as pd

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.coverage import CoverageSpec, compute_coverage
from rime_core.irr import IRRResult, format_irr_value
from rime_core.session import Session
from rime_core.signals import Signal


ExportFn = Callable[[AnnotationStore, Session, Path, bool], None]
_FFMPEG_FALLBACK_PATHS = (
    Path("/opt/homebrew/bin/ffmpeg"),
    Path("/usr/local/bin/ffmpeg"),
)


class ExportError(Exception):
    """Raised when no exporter is available or an export fails."""


class ExporterRegistry:
    """Dispatch annotation export by format name."""

    def __init__(self) -> None:
        self._exporters: dict[str, ExportFn] = {}

    @classmethod
    def default(cls) -> ExporterRegistry:
        registry = cls()
        registry.register("parquet", export_parquet)
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
        f"% Agreement\t{format_irr_value(result.percent_agreement, percent=True)}",
        f"Episode IoU (mean)\t{format_irr_value(result.frame_iou)}",
        f"Matched episodes\t{len(result.matched_episodes)}",
        f"Unmatched (A only)\t{len(result.unmatched_a)}",
        f"Unmatched (B only)\t{len(result.unmatched_b)}",
        "",
        "Label\tκ\t% Agreement\tEpisode IoU\tMatched\tA-only\tB-only",
    ]
    for label in sorted(result.per_label):
        item = result.per_label[label]
        lines.append(
            "\t".join(
                [
                    item.label,
                    format_irr_value(item.cohens_kappa),
                    format_irr_value(item.percent_agreement, percent=True),
                    format_irr_value(item.episode_iou),
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
    total_ms = _union_duration_ms(
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


def _union_duration_ms(intervals: list[tuple[float, float]]) -> float:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return float(sum(end - start for start, end in merged))


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
