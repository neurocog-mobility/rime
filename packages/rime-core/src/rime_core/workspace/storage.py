"""Atomic persistence for the native domain and separate machine-local workspace.

Only format 0.2 is supported. No v0.1 session or prototype conversion is performed.
Snapshots are recovery states, not captured measurement revisions.
"""

from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import TYPE_CHECKING, Any

from rime_core.annotations import AnnotationStore
from rime_core.measurements import MeasurementRecord
from rime_core.records.revisions import domain_state
from rime_core.records import (
    AnnotationSet,
    CalculationTemplate,
    ImportProvenance,
    RecordingCatalog,
    ResearchContext,
    SignalSource,
    Timeline,
    VideoSource,
)
from rime_core.schema import ProtocolSchema
from rime_core.workspace.models import ModelSettings, WorkspaceSession, WorkspaceView, now

if TYPE_CHECKING:
    from rime_core.workspace.context import WorkingContext

FORMAT = "rime-workspace"
VERSION = "0.2"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cmf-save-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def scientific_state(context: WorkingContext) -> dict:
    return {
        "format": "rime-working-state",
        "version": VERSION,
        **domain_state(context.research, context.recordings, context.annotation_set),
        "calculation_templates": [asdict(item) for item in context.calculation_templates],
        "measurements": [record.to_dict() for record in context.measurements],
    }


def _validate_state(state: dict) -> None:
    if state.get("format") != "rime-working-state" or state.get("version") != VERSION:
        raise ValueError("Unsupported working-state format/version.")
    records = [MeasurementRecord.from_dict(item) for item in state["measurements"]]
    if len({r.id for r in records}) != len(records):
        raise ValueError("Duplicate measurement identities.")
    recordings = state["recordings"]
    timeline_id = recordings["timeline"]["id"]
    annotation_set = state["annotation_set"]
    if not timeline_id or annotation_set["timeline_id"] != timeline_id:
        raise ValueError("Annotation set references an unknown timeline.")
    sources = recordings["videos"] + recordings["signals"]
    ids = [source["id"] for source in sources]
    if any(not isinstance(id_, str) or not id_ for id_ in ids) or len(ids) != len(set(ids)):
        raise ValueError("Recording source identities must be nonempty and unique.")
    if len(recordings["videos"]) > 2:
        raise ValueError("The desktop supports two video views.")
    for source in sources:
        if not math.isfinite(source["offset_ms"]):
            raise ValueError("Source offset must be finite.")
    annotations = annotation_set["annotations"]
    ids = [item["id"] for item in annotations]
    if any(not id_ for id_ in ids) or len(ids) != len(set(ids)):
        raise ValueError("Annotation identities must be nonempty and unique.")
    for item in annotations:
        start, end = item["start_ms"], item["end_ms"]
        if not math.isfinite(start) or not math.isfinite(end) or start > end:
            raise ValueError("Annotation intervals must be finite and ordered.")
    if not isinstance(state["research_context"], dict) or not all(
        isinstance(value, str) for value in state["research_context"].values()
    ):
        raise ValueError("Research context values must be text.")


def save_workspace(context: WorkingContext) -> None:
    state = scientific_state(context)
    _validate_state(state)
    data = _bytes(state)
    digest = hashlib.sha256(data).hexdigest()
    relative = f"working/{digest}.json"
    workspace = context.workspace
    target = workspace.root / relative
    if not target.exists() or target.read_bytes() != data:
        _atomic_write(target, data)
    modified = now()
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "id": workspace.id,
        "name": workspace.name,
        "created": workspace.created,
        "modified": modified,
        "working_state": relative,
        "view": asdict(workspace.view),
        "source_locations": workspace.source_locations,
        "model_paths": workspace.model_paths,
        "model_settings": {name: asdict(value) for name, value in workspace.model_settings.items()},
    }
    _atomic_write(workspace.path, _bytes(manifest))
    workspace.working_state, workspace.modified = relative, modified


def load_workspace(
    path: Path | str,
) -> tuple[
    WorkspaceSession, ResearchContext, RecordingCatalog, AnnotationSet,
    list[CalculationTemplate], list[MeasurementRecord]
]:
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        path /= "workspace.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise ValueError("Unsupported workspace format/version. Create a native v0.2 workspace.")
    for key in ("id", "name", "created", "modified"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError(f"Workspace is missing {key}.")
    relative = manifest.get("working_state", "")
    if not isinstance(relative, str) or not re.fullmatch(r"working/[a-f0-9]{64}\.json", relative):
        raise ValueError("Invalid workspace working-state reference.")
    target = (path.parent / relative).resolve()
    if not target.is_relative_to(path.parent):
        raise ValueError("Working state must be inside the workspace folder.")
    raw = target.read_bytes()
    if hashlib.sha256(raw).hexdigest() != target.stem:
        raise ValueError("Working-state integrity check failed; the saved file has changed.")
    state = json.loads(raw)
    _validate_state(state)
    rec = state["recordings"]
    recordings = RecordingCatalog(
        timeline=Timeline(**rec["timeline"]),
        videos=[VideoSource(**item) for item in rec["videos"]],
        signals=[SignalSource(**item) for item in rec["signals"]],
    )
    ann = state["annotation_set"]
    annotation_set = AnnotationSet(
        id=ann["id"],
        name=ann["name"],
        timeline_id=ann["timeline_id"],
        rater=ann["rater"],
        protocol=ProtocolSchema.from_dict(ann["protocol"]),
        annotations=AnnotationStore.from_dict({"annotations": ann["annotations"]}),
        provenance=ImportProvenance(**ann["provenance"]),
    )
    for key in ("source_locations", "model_paths"):
        if not isinstance(manifest[key], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in manifest[key].items()
        ):
            raise ValueError(f"Invalid workspace {key}.")
    workspace = WorkspaceSession(
        root=path.parent,
        id=manifest["id"],
        name=manifest["name"],
        created=manifest["created"],
        modified=manifest["modified"],
        working_state=relative,
        view=WorkspaceView(**manifest["view"]),
        source_locations=manifest["source_locations"],
        model_paths=manifest["model_paths"],
        model_settings={k: ModelSettings(**v) for k, v in manifest["model_settings"].items()},
    )
    return (
        workspace,
        ResearchContext(**state["research_context"]),
        recordings,
        annotation_set,
        [CalculationTemplate(**item) for item in state["calculation_templates"]],
        [MeasurementRecord.from_dict(item) for item in state["measurements"]],
    )


def copy_workspace(context: WorkingContext, destination: Path | str) -> WorkingContext:
    from rime_core.workspace.context import WorkingContext

    destination = Path(destination).expanduser().resolve()
    require_empty_destination(destination)
    workspace = copy.deepcopy(context.workspace)
    original = context.workspace
    workspace.root, workspace.id = destination, WorkspaceSession(destination, original.name).id
    workspace.created, workspace.working_state = now(), ""
    workspace.source_locations = {
        key: str(original.source_path(key)) for key in original.source_locations
    }
    workspace.model_paths = {key: str(original.model_path(key)) for key in original.model_paths}
    copied = WorkingContext(
        workspace=workspace,
        research=copy.deepcopy(context.research),
        recordings=copy.deepcopy(context.recordings),
        annotation_set=copy.deepcopy(context.annotation_set),
        calculation_templates=copy.deepcopy(context.calculation_templates),
        measurements=list(context.measurements),
        loader_registry=context.loader_registry,
    )
    copied.save()
    return WorkingContext.open(workspace.path, loader_registry=context.loader_registry)


def require_empty_destination(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("Choose an empty folder for the new workspace.")
