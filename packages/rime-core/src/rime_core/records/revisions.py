"""Immutable captures of native annotation, context, and recording objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

from rime_core.annotations import AnnotationStore
from rime_core.records.models import (
    AnnotationSet, RecordingCatalog, ResearchContext, SignalSource, Timeline, VideoSource,
    ImportProvenance,
)
from rime_core.schema import ProtocolSchema


def domain_state(research: ResearchContext, recordings: RecordingCatalog,
                 annotations: AnnotationSet) -> dict:
    """One serialization for working objects and pinned revisions; no local paths."""
    return {
        "research_context": asdict(research),
        "recordings": asdict(recordings),
        "annotation_set": {
            "id": annotations.id, "name": annotations.name,
            "timeline_id": annotations.timeline_id, "rater": annotations.rater,
            "protocol": annotations.protocol.to_dict(),
            "provenance": asdict(annotations.provenance),
            "annotations": annotations.annotations.to_dict()["annotations"],
        },
    }


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_domain(data: dict) -> None:
    if set(data) != {"research_context", "recordings", "annotation_set"}:
        raise ValueError("Invalid revision contents.")
    research = ResearchContext(**data["research_context"])
    if not all(isinstance(value, str) for value in asdict(research).values()):
        raise ValueError("Research context must contain text.")
    rec = data["recordings"]
    timeline = Timeline(**rec["timeline"])
    sources = [VideoSource(**s) for s in rec["videos"]]
    sources += [SignalSource(**s) for s in rec["signals"]]
    ids = [s.id for s in sources]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid source identities.")
    if any(not math.isfinite(s.offset_ms) for s in sources):
        raise ValueError("Source offsets must be finite.")
    ann = data["annotation_set"]
    if not ann["id"] or not timeline.id or ann["timeline_id"] != timeline.id:
        raise ValueError("Annotation revision references an unknown timeline.")
    protocol = ProtocolSchema.from_dict(ann["protocol"])
    ImportProvenance(**ann["provenance"])
    ids = [a["id"] for a in ann["annotations"]]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid annotation identities.")
    store = AnnotationStore.from_dict({"annotations": ann["annotations"]})
    for a in store.all():
        if (not math.isfinite(a.start_ms) or not math.isfinite(a.end_ms)
                or a.end_ms < a.start_ms):
            raise ValueError("Annotation boundaries must be finite and ordered.")
        if protocol.get_lane(a.lane) is None:
            raise ValueError(f"Annotation references unknown lane: {a.lane}")


@dataclass(frozen=True)
class CapturedRevision:
    """Content-addressed native objects; access returns a detached value.

    Canonical JSON is an internal immutable backing store, not another domain
    model. The serialized document contains ordinary native domain objects.
    """

    _json: str

    def __post_init__(self) -> None:
        validate_domain(json.loads(self._json))

    @classmethod
    def capture(cls, research: ResearchContext, recordings: RecordingCatalog,
                annotations: AnnotationSet) -> CapturedRevision:
        return cls(canonical(domain_state(research, recordings, annotations)))

    @property
    def id(self) -> str:
        return "revision-" + hashlib.sha256(self._json.encode()).hexdigest()

    def domain(self) -> dict:
        return json.loads(self._json)

    @property
    def annotation_revision_id(self) -> str:
        annotations = canonical(self.domain()["annotation_set"])
        return "annotations-" + hashlib.sha256(annotations.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {"id": self.id, **self.domain()}

    @classmethod
    def from_dict(cls, data: dict) -> CapturedRevision:
        revision = cls(canonical({k: v for k, v in data.items() if k != "id"}))
        if revision.id != data["id"]:
            raise ValueError("Captured revision integrity check failed.")
        return revision
