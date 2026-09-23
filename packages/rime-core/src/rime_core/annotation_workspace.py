"""Editable annotation work, independent of immutable RIME measurement documents.

A workspace retains a protocol, external sources, imported starting states and
current annotations. Playback/undo actions are not scientific activities.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import os
import tempfile
import uuid

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.records import SignalSource, VideoSource
from rime_core.schema import ProtocolSchema

FORMAT = "rime-annotation-workspace"
VERSION = "0.3"


class AnnotationWorkspace:
    format = FORMAT
    version = VERSION

    def __init__(self, data: dict, path: Path | None = None):
        self.data = deepcopy(data)
        self.path = path
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self.validate()
        self._saved = deepcopy(self.data) if path else None

    @classmethod
    def create(cls, name, protocol, videos, signals=(), context=None, imports=()):
        return cls(
            {
                "format": FORMAT,
                "version": VERSION,
                "id": uuid.uuid4().hex,
                "name": name,
                "protocol": protocol.to_dict(),
                "research_context": context or {},
                "sources": [*videos, *signals],
                "imports": list(imports),
                "annotations": [],
                "rater": "",
                "view": {},
            }
        )

    @classmethod
    def open(cls, path):
        path = Path(path).resolve()
        if path.is_dir():
            path /= "workspace.json"
        data = json.loads(path.read_text())
        for entry in _path_entries(data):
            source = Path(entry["path"]).expanduser()
            entry["path"] = str((path.parent / source).resolve())
        return cls(data, path)

    @property
    def schema(self):
        return ProtocolSchema.from_dict(self.data["protocol"])

    @property
    def store(self):
        result = AnnotationStore()
        for item in self.data["annotations"]:
            result.add(Annotation(**item))
        return result

    @property
    def dirty(self):
        return self.data != self._saved

    def validate(self):
        d = self.data
        if d.get("format") != self.format or d.get("version") != self.version:
            raise ValueError("This is not a current annotation workspace.")
        if not isinstance(d.get("name"), str) or not d["name"].strip():
            raise ValueError("Enter a workspace name.")
        schema = self.schema
        sources = d["sources"]
        if len({s["config"]["id"] for s in sources}) != len(sources):
            raise ValueError("Source identifiers must be unique.")
        videos = [s for s in sources if s["kind"] == "video"]
        if not 1 <= len(videos) <= 2 or videos[0]["config"]["offset_ms"] != 0:
            raise ValueError("Video 1 is required and its offset must be zero.")
        for source in sources:
            if not isinstance(source.get("synchronization_note", ""), str):
                raise ValueError("Synchronization notes must be text.")
            if source["kind"] not in ("video", "signal"):
                raise ValueError("Unknown source type.")
            config = (VideoSource if source["kind"] == "video" else SignalSource)(
                **source["config"]
            )
            if not math.isfinite(config.offset_ms):
                raise ValueError("Offsets must be finite.")
            if not isinstance(source["path"], str) or not source["path"]:
                raise ValueError("Every source needs a location.")
        seen = set()
        for annotation in self.store.all():
            lane = schema.get_lane(annotation.lane)
            if lane is None or annotation.label not in lane.labels:
                raise ValueError(
                    f"Label {annotation.label!r} is not defined in lane {annotation.lane!r}."
                )
            if not all(
                math.isfinite(t) and t >= 0 for t in (annotation.start_ms, annotation.end_ms)
            ):
                raise ValueError("Annotation boundaries must be finite and non-negative.")
            point = schema.is_point_lane(annotation.lane)
            if (point and annotation.start_ms != annotation.end_ms) or (
                not point and annotation.end_ms <= annotation.start_ms
            ):
                raise ValueError("Annotation boundaries do not match the lane's event type.")
            if annotation.event_type != ("point" if point else "interval") or annotation.ghost:
                raise ValueError("Working annotations must be committed events of the lane's type.")
            seen.add(annotation.id)
        proposal_ids = set()
        for run in d.get("suggestion_runs", []):
            if run.get("kind") not in ("model", "rule"):
                raise ValueError("Unknown suggestion origin.")
            for item in run["suggestions"]:
                if item["decision"] not in (
                    "pending",
                    "accept",
                    "modify",
                    "reject",
                    "reject_remaining",
                ):
                    raise ValueError("Unknown suggestion decision.")
                a = Annotation(**item["annotation"])
                lane = schema.get_lane(a.lane)
                if not lane or a.label not in lane.labels or a.event_type != lane.lane_type:
                    raise ValueError("Suggestion is not defined by this protocol.")
                if not all(math.isfinite(t) and t >= 0 for t in (a.start_ms, a.end_ms)):
                    raise ValueError("Invalid suggestion boundaries.")
                if (a.event_type == "point" and a.start_ms != a.end_ms) or (
                    a.event_type != "point" and a.start_ms >= a.end_ms
                ):
                    raise ValueError("Invalid suggestion extent.")
                if a.id in proposal_ids or (
                    a.id in seen and item["decision"] not in ("accept", "modify")
                ):
                    raise ValueError("Suggestion identity conflicts with retained annotations.")
                proposal_ids.add(a.id)
        if len(seen) != len(d["annotations"]):
            raise ValueError("Annotation identifiers must be unique.")

    def change(self, function):
        before = deepcopy(self.data)
        try:
            function(self.data)
            self.validate()
        except Exception:
            self.data = before
            raise
        if self.data != before:
            self._undo.append(before)
            self._redo.clear()

    def put_annotation(self, annotation):
        def update(d):
            d["annotations"] = [a for a in d["annotations"] if a["id"] != annotation.id]
            d["annotations"].append(asdict(annotation))

        self.change(update)

    def delete_annotation(self, identifier):
        self.change(
            lambda d: d.update(annotations=[a for a in d["annotations"] if a["id"] != identifier])
        )

    def set_offset(self, identifier, milliseconds):
        def update(d):
            source = next(s for s in d["sources"] if s["config"]["id"] == identifier)
            source["config"]["offset_ms"] = float(milliseconds)
            source["config"]["sync_method"] = "manual_constant_offset"

        self.change(update)

    def set_synchronization_note(self, identifier, note):
        def update(d):
            source = next(s for s in d["sources"] if s["config"]["id"] == identifier)
            source["synchronization_note"] = note.strip()

        self.change(update)

    def undo(self):
        if self._undo:
            self._redo.append(deepcopy(self.data))
            self.data = self._undo.pop()

    def redo(self):
        if self._redo:
            self._undo.append(deepcopy(self.data))
            self.data = self._redo.pop()

    def save(self, path=None):
        self.validate()
        destination = Path(path or self.path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        saved = deepcopy(self.data)
        for entry in _path_entries(saved):
            try:
                entry["path"] = Path(os.path.relpath(entry["path"], destination.parent)).as_posix()
            except ValueError:  # Windows sources on another drive remain absolute.
                pass
        payload = json.dumps(saved, indent=2, allow_nan=False) + "\n"
        fd, temporary = tempfile.mkstemp(
            prefix=".workspace-", suffix=".json", dir=destination.parent
        )
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.path = destination
        self._saved = deepcopy(self.data)


def _path_entries(data):
    """Local file references only; never rewrite retained scientific node data."""
    yield from data.get("sources", [])
    yield from data.get("imports", [])
    for retained in data.get("review_evidence", []):
        yield retained["source"]
    for run in data.get("suggestion_runs", []):
        for retained in run.get("sources", []):
            yield retained["source"]


def source_entry(path, config, kind):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"Source not found: {path}")
    return {"kind": kind, "path": str(path), "config": asdict(config)}


def import_annotations(workspace, path, tier_map, label_map=None):
    """Preserve the selected EAF intervals without applying automatic rules."""
    from rime_core.elan_import import import_eaf

    path = Path(path).resolve()
    result = import_eaf(
        path, workspace.schema, tier_map=tier_map, label_map=label_map, apply_rules=False
    )
    annotations = [asdict(a) for a in result.store.all()]
    retained = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "tier_map": tier_map,
        "label_map": result.label_mappings,
        "annotations": annotations,
    }

    def update(d):
        d["imports"].append(retained)
        d["annotations"].extend(deepcopy(annotations))

    workspace.change(update)
    return len(annotations)
