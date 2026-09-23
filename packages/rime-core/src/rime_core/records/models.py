"""Clinical context, recording descriptions, and working annotation sets.

Sources have identities, not machine-local paths. An annotation set owns its
protocol and intervals and references a timeline. The workspace does not own
their scientific meaning. Immutable captures use these same native objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from rime_core.annotations import AnnotationStore
from rime_core.schema import ProtocolSchema


def new_id(kind: str) -> str:
    return f"{kind}-{uuid.uuid4().hex}"


@dataclass
class ResearchContext:
    study_id: str = ""
    participant_id: str = ""
    visit_id: str = ""
    trial_id: str = ""
    condition: str = ""
    medication_state: str = ""
    bids_session_id: str = ""


@dataclass
class Timeline:
    id: str = field(default_factory=lambda: new_id("timeline"))
    origin_utc: str = ""
    recording_relative_timing_verified: bool = False


@dataclass
class VideoSource:
    id: str = field(default_factory=lambda: new_id("source"))
    file_name: str = ""
    name: str = ""
    role: str = "primary"
    offset_ms: float = 0.0
    fps_override: float | None = None
    sync_method: str = ""
    label: str = ""


@dataclass
class SignalSource:
    type: str
    format: str
    sampling_rate_hz: float
    time_column: str
    id: str = field(default_factory=lambda: new_id("source"))
    file_name: str = ""
    name: str = ""
    time_reference: str = "relative"
    time_unit: str = "seconds"
    offset_ms: float = 0.0
    sync_method: str = ""
    channels: list[str] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)


@dataclass
class RecordingCatalog:
    timeline: Timeline = field(default_factory=Timeline)
    videos: list[VideoSource] = field(default_factory=list)
    signals: list[SignalSource] = field(default_factory=list)


@dataclass
class ImportProvenance:
    origin: str = "manual"
    source_files: list[str] = field(default_factory=list)
    tier_map: dict[str, str] = field(default_factory=dict)
    label_map: dict[str, str] = field(default_factory=dict)
    rules_applied: bool = False


@dataclass
class AnnotationSet:
    timeline_id: str
    protocol: ProtocolSchema
    id: str = field(default_factory=lambda: new_id("annotations"))
    name: str = "Working annotations"
    rater: str = ""
    annotations: AnnotationStore = field(default_factory=AnnotationStore)
    provenance: ImportProvenance = field(default_factory=ImportProvenance)


@dataclass
class CalculationTemplate:
    """Editable calculation selectors; not a captured measurement."""

    name: str
    numerator: list[dict[str, str | None]] = field(default_factory=list)
    denominator_type: str = "timeline"
    denominator: list[dict[str, str | None]] = field(default_factory=list)
