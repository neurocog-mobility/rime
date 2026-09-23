"""ELAN import utilities for converting .eaf data into native annotation sets and workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import pympi

from rime_core.annotations import Annotation, AnnotationStore, generate_id
from rime_core.rule_engine import RuleEngine, SideEffect, Violation
from rime_core.schema import ProtocolSchema
from rime_core.records import VideoSource, ImportProvenance
from rime_core.workspace.models import SignalSelection


@dataclass
class TierMapping:
    """Resolved mapping from an ELAN tier to a RIME lane."""

    elan_tier: str
    rime_lane: str | None
    annotation_count: int


@dataclass
class ImportResult:
    """Complete result of importing one ELAN file."""

    store: AnnotationStore
    tier_mappings: list[TierMapping]
    label_mappings: dict[str, str]
    side_effects: list[SideEffect]
    violations: list[Violation]
    media_files: list[str]


def auto_map_tiers(eaf_tiers: list[str], schema: ProtocolSchema) -> list[TierMapping]:
    """Auto-match ELAN tiers to schema lane names using exact normalized names."""
    lane_names = schema.get_lane_names()
    normalized_lanes = {_normalize(name): name for name in lane_names}

    mappings: list[TierMapping] = []
    for tier in eaf_tiers:
        tier_key = _normalize(tier)
        mapped_lane = normalized_lanes.get(tier_key)

        mappings.append(
            TierMapping(
                elan_tier=tier,
                rime_lane=mapped_lane,
                annotation_count=0,
            )
        )

    return mappings


def normalize_label(label: str, lane_labels: list[str], label_map: dict | None = None) -> str:
    """Normalize an imported ELAN label to a lane label."""
    raw = (label or "").strip()
    if not raw:
        return ""

    if label_map and raw in label_map:
        return label_map[raw]

    if label_map:
        raw_key = _normalize(raw)
        for src, target in label_map.items():
            if _normalize(src) == raw_key:
                return target

    raw_key = _normalize(raw)
    for lane_label in lane_labels:
        if _normalize(lane_label) == raw_key:
            return lane_label

    return raw


def extract_media_files(eaf_path: Path) -> list[str]:
    """Extract linked media paths from an ELAN .eaf file."""
    eaf = pympi.Elan.Eaf(str(eaf_path))
    result: list[str] = []
    for descriptor in getattr(eaf, "media_descriptors", []):
        rel = descriptor.get("RELATIVE_MEDIA_URL", "")
        url = descriptor.get("MEDIA_URL", "")
        candidate = rel or url
        if not candidate:
            continue

        if candidate.startswith("file://"):
            parsed = urlparse(candidate)
            candidate = unquote(parsed.path)

        if candidate not in result:
            result.append(candidate)
    return result


def import_eaf(
    path: Path,
    schema: ProtocolSchema,
    tier_map: dict[str, str] | None = None,
    label_map: dict[str, str] | None = None,
    apply_rules: bool = True,
) -> ImportResult:
    """Import a single .eaf file into an annotation store."""
    eaf = pympi.Elan.Eaf(str(path))
    tier_names = list(eaf.get_tier_names())

    if tier_map is None:
        mappings = auto_map_tiers(tier_names, schema)
    else:
        mappings = []
        for tier_name in tier_names:
            mapped = tier_map.get(tier_name)
            mappings.append(
                TierMapping(
                    elan_tier=tier_name,
                    rime_lane=mapped,
                    annotation_count=0,
                )
            )

    store = AnnotationStore()
    label_mappings: dict[str, str] = {}

    for mapping in mappings:
        tier_annotations = eaf.get_annotation_data_for_tier(mapping.elan_tier)
        mapping.annotation_count = len(tier_annotations)

        if not mapping.rime_lane:
            continue

        lane_schema = schema.get_lane(mapping.rime_lane)
        lane_labels = lane_schema.labels if lane_schema else []

        for start_ms, end_ms, label in tier_annotations:
            normalized = normalize_label(label, lane_labels, label_map=label_map)
            if not normalized and len(lane_labels) == 1:
                normalized = lane_labels[0]
            label_mappings[(label or "").strip()] = normalized
            is_point_lane = schema.is_point_lane(mapping.rime_lane)

            store.add(
                Annotation(
                    id=generate_id(),
                    lane=mapping.rime_lane,
                    label=normalized,
                    start_ms=float(start_ms),
                    end_ms=float(start_ms if is_point_lane else end_ms),
                    event_type="point" if is_point_lane else "interval",
                    source="elan_import",
                    ghost=False,
                    confidence_type="not_recorded",
                )
            )

    side_effects: list[SideEffect] = []
    violations: list[Violation] = []
    if apply_rules:
        engine = RuleEngine(schema)
        side_effects, violations = engine.on_import(store)
        violations.extend(engine.validate(store))

    return ImportResult(
        store=store,
        tier_mappings=mappings,
        label_mappings=label_mappings,
        side_effects=side_effects,
        violations=violations,
        media_files=extract_media_files(path),
    )


def import_workspace_from_elan(
    eaf_path: Path,
    directory: Path,
    schema: ProtocolSchema,
    tier_map: dict[str, str] | None = None,
    label_map: dict[str, str] | None = None,
    apply_rules: bool = True,
    additional_videos: list[str] | None = None,
    additional_signals: list[SignalSelection] | None = None,
):
    """Import external EAF directly into native annotation and recording objects."""
    from rime_core.workspace.context import WorkingContext

    result = import_eaf(eaf_path, schema, tier_map, label_map, apply_rules)
    context = WorkingContext.create_workspace(
        directory, eaf_path.stem, schema=schema,
        videos=[(path, VideoSource()) for path in additional_videos or []],
        signals=additional_signals,
    )
    context.annotation_set.annotations = result.store
    context.annotation_set.name = eaf_path.stem
    context.annotation_set.provenance = ImportProvenance(
        origin="elan_import", source_files=[eaf_path.name],
        tier_map={m.elan_tier: m.rime_lane for m in result.tier_mappings if m.rime_lane},
        label_map=result.label_mappings, rules_applied=apply_rules,
    )
    context.save()
    return context, result


def _normalize(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())
