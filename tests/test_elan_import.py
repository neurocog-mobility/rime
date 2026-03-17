from __future__ import annotations

from pathlib import Path

from rime_core.elan_import import (
    auto_map_tiers,
    extract_media_files,
    import_eaf,
    import_session_from_elan,
    normalize_label,
)
from rime_core.schema import ProtocolSchema

SAMPLE_EAF = Path(
    "sample-data/elan-sample/S006_FR_SS/Session 1 Off/"
    "C7_sub006_FR_ses01_off_stagil_front_unblur.eaf"
)


def test_auto_map_tiers() -> None:
    schema = ProtocolSchema.default()
    tiers = ["Task", "FOG", "Core", "Manifestation", "Notes"]

    result = auto_map_tiers(tiers, schema)
    mapped = {item.elan_tier: item.rime_lane for item in result}
    assert mapped == {
        "Task": None,
        "FOG": "FOG",
        "Core": "Core",
        "Manifestation": None,
        "Notes": "Notes",
    }


def test_auto_map_tiers_does_not_fuzzy_match() -> None:
    schema = ProtocolSchema.default()

    result = auto_map_tiers(["Task", "Manifestation"], schema)
    mapped = {item.elan_tier: item.rime_lane for item in result}
    assert mapped["Task"] is None
    assert mapped["Manifestation"] is None


def test_import_single_eaf() -> None:
    schema = ProtocolSchema.default()

    result = import_eaf(
        SAMPLE_EAF,
        schema,
        tier_map={
            "Task": "Tasks",
            "FOG": "FOG",
            "Core": "Core",
            "Manifestation": "Manifestations",
            "Notes": "Notes",
        },
        label_map={"Trajectory": "Walk"},
        apply_rules=False,
    )

    assert len(result.store.annotations) > 0
    assert all(ann.lane in schema.get_lane_names() for ann in result.store.annotations.values())


def test_label_normalization() -> None:
    lane_labels = ["Akinetic", "Kinetic_trembling", "Kinetic_no_trembling"]
    normalized = normalize_label("kinetic_no_trembling", lane_labels)
    assert normalized == "Kinetic_no_trembling"


def test_hierarchy_auto_population() -> None:
    schema = ProtocolSchema.default()
    result = import_eaf(
        SAMPLE_EAF,
        schema,
        tier_map={
            "Task": "Tasks",
            "FOG": "FOG",
            "Core": "Core",
            "Manifestation": "Manifestations",
            "Notes": "Notes",
        },
        label_map={"Trajectory": "Walk"},
        apply_rules=True,
    )

    fog_count = len(result.store.get_by_lane("FOG"))
    assert fog_count > 0
    assert len(result.store.get_by_lane("Core")) >= fog_count


def test_extract_media_files() -> None:
    media_files = extract_media_files(SAMPLE_EAF)
    assert media_files
    assert any(".mp4" in file.lower() for file in media_files)


def test_import_session_from_elan(tmp_path: Path) -> None:
    schema = ProtocolSchema.default()

    session, result = import_session_from_elan(
        eaf_path=SAMPLE_EAF,
        session_dir=tmp_path / "session-import",
        schema=schema,
        tier_map={
            "Task": "Tasks",
            "FOG": "FOG",
            "Core": "Core",
            "Manifestation": "Manifestations",
            "Notes": "Notes",
        },
        label_map={"Trajectory": "Walk"},
        apply_rules=True,
    )

    assert (session.session_dir / "session.json").exists()
    assert (session.session_dir / "annotations" / "annotations.json").exists()
    assert session.provenance.origin == "elan_import"
    assert len(result.store.annotations) > 0


def test_annotation_source() -> None:
    schema = ProtocolSchema.default()
    result = import_eaf(
        SAMPLE_EAF,
        schema,
        tier_map={
            "Task": "Tasks",
            "FOG": "FOG",
            "Core": "Core",
            "Manifestation": "Manifestations",
            "Notes": "Notes",
        },
        label_map={"Trajectory": "Walk"},
        apply_rules=False,
    )

    assert result.store.annotations
    assert all(ann.source == "elan_import" for ann in result.store.annotations.values())
