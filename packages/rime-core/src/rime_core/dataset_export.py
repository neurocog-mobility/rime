"""Export the retained annotations and optional signals of one native workspace."""

from dataclasses import dataclass
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import numpy as np

from .annotation_workspace import AnnotationWorkspace
from .review_workspace import ReviewWorkspace
from .io.exporters import export_bids_dataset
from .loaders import SignalLoaderRegistry
from .records import AnnotationSet, RecordingCatalog, ResearchContext, SignalSource, Timeline


@dataclass
class _ExportContext:
    """The scientific objects consumed by the existing dataset writers."""

    research: ResearchContext
    recordings: RecordingCatalog
    annotation_set: AnnotationSet


def validate_export(destination, participant, session, timing_verified):
    if not str(destination).strip():
        raise ValueError("Choose an export folder.")
    for name, value in (("Participant", participant), ("Session", session)):
        if not re.fullmatch(r"[A-Za-z0-9]+", value):
            raise ValueError(f"{name} ID must contain only letters and numbers (without a prefix).")
    if not timing_verified:
        raise ValueError("Confirm that annotation and signal timing is aligned to Video 1.")
    path = Path(destination).expanduser()
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise ValueError("Choose a new or empty export folder.")
    return path


def export_workspace_dataset(
    data, destination, participant, session, *, timing_verified=False,
    export_motion=False, export_clips=False,
):
    """Write a detached workspace snapshot; publish only a fully written dataset."""
    path = validate_export(destination, participant, session, timing_verified)
    workspace_type = (
        ReviewWorkspace if data.get("format") == ReviewWorkspace.format else AnnotationWorkspace
    )
    workspace = workspace_type(data)
    configs = [SignalSource(**s["config"]) for s in data["sources"] if s["kind"] == "signal"]
    recordings = RecordingCatalog(
        timeline=Timeline(recording_relative_timing_verified=True), signals=configs,
    )
    context = _ExportContext(
        research=ResearchContext(
            participant_id=participant, bids_session_id=session,
            condition=data["research_context"].get("condition", ""),
        ),
        recordings=recordings,
        annotation_set=AnnotationSet(
            timeline_id=recordings.timeline.id, protocol=workspace.schema,
            annotations=workspace.store, rater=data.get("rater", ""),
        ),
    )
    signals = []
    if export_motion or export_clips:
        registry = SignalLoaderRegistry.default()
        sources = {s["config"]["id"]: s for s in data["sources"]}
        for config in configs:
            source = sources[config.id]
            config.sync_method = source.get("synchronization_note") or config.sync_method
            signal = registry.load(Path(source["path"]), config)
            signal.source_id = config.id
            if not np.isfinite(signal.sampling_rate_hz) or signal.sampling_rate_hz <= 0:
                raise ValueError(f"Invalid sampling rate for {signal.name}.")
            times = signal.get_time_ms()
            if not len(times) or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
                raise ValueError(f"Signal {signal.name} needs finite, increasing timestamps.")
            # Motion TSVs encode time by sample index and frequency, not a time column.
            if export_motion and not np.allclose(
                times, np.arange(len(times)) * 1000 / signal.sampling_rate_hz + signal.offset_ms,
                rtol=0, atol=0.1,
            ):
                raise ValueError(
                    f"Signal {signal.name} is not regularly sampled at its configured rate. "
                    "Correct the sampling rate or export signal clips only."
                )
            signals.append(signal)
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".rime-export-", dir=path.parent) as temporary:
        staging = Path(temporary) / "dataset"
        count = export_bids_dataset(
            workspace.store, context, signals, staging,
            export_motion=export_motion, export_clips=export_clips,
        )
        validate_export(path, participant, session, timing_verified)
        staging.rename(path)
    return count
