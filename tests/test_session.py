from __future__ import annotations

import json
from pathlib import Path

from rime_core.session import (
    ClinicalMetricSpec,
    DEFAULT_PANEL_VISIBILITY,
    ModelSettings,
    SessionProvenance,
    SignalConfig,
    SubjectInfo,
    VideoConfig,
    create_session,
    load_session,
    save_session,
)


def test_create_session(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "new-session",
        name="My Session",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        rater="AZ",
        provenance=SessionProvenance(origin="manual"),
    )

    manifest = session.session_dir / "session.json"
    assert manifest.exists()

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["name"] == "My Session"
    assert data["rater"] == "AZ"
    assert data["provenance"]["origin"] == "manual"


def test_create_session_caps_and_relabels_videos_to_two_slots(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "capped-session",
        name="Capped",
        videos=[
            VideoConfig(path="third.mp4", role="secondary"),
            VideoConfig(path="first.mp4", role="side"),
            VideoConfig(path="second.mp4", role="primary"),
            VideoConfig(path="first.mp4", role="primary"),
        ],
    )

    assert [video.path for video in session.videos] == ["third.mp4", "first.mp4"]
    assert [video.role for video in session.videos] == ["primary", "secondary"]
    assert session.primary_video == "third.mp4"


def test_save_load_roundtrip(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "roundtrip",
        name="Imported Session",
        videos=[VideoConfig(path="video.mp4", name="Front", role="primary", fps_override=29.97)],
        signals=[
            SignalConfig(
                path="imu.csv",
                name="Lumbar IMU",
                type="imu",
                format="csv",
                sampling_rate_hz=100.0,
                time_column="timestamp",
                time_reference="utc_epoch",
                time_unit="microseconds",
                offset_ms=125.0,
                sync_method="utc",
                channels=["acc_x", "acc_y"],
                display_channels=["acc_y"],
            )
        ],
        subject=SubjectInfo(id="S001", condition="PD", medication_state="off"),
        rater="MK",
        provenance=SessionProvenance(
            origin="elan_import",
            source_files=["test.eaf"],
            tier_map={"Task": "Tasks"},
            label_map={"Trajectory": "Walk"},
            rules_applied=True,
        ),
    )
    session.session_start_utc = "2024-03-01T09:31:22Z"
    session.schema_path = "/tmp/fog-coa.json"
    session.schema_name = "FOG-COA"
    session.schema_version = "1.1"
    session.model_settings["Walking Classifier"] = ModelSettings(
        params={"threshold": 0.7},
        input_sources={"left_ankle": "Lumbar IMU"},
        input_bindings={"left_ankle": {"leftankle_ax": "acc_x"}},
        output_mappings=[{"output_name": "walking_probability", "lane": "Tasks", "label": "Walk"}],
    )
    session.model_paths["Walking Classifier"] = "models/walking.rime"
    session.panel_visibility["clinical_outcomes"] = False
    session.panel_visibility["model_runner"] = False
    session.dock_layout_state = "dock-state-token"
    session.clinical_metrics = [
        ClinicalMetricSpec(
            name="%TF (session)",
            numerator=[{"lane": "FOG", "label": None}],
            denominator_type="session",
            denominator=[],
        )
    ]

    save_session(session)
    loaded = load_session(session.session_dir)

    assert loaded.name == session.name
    assert loaded.provenance.origin == "elan_import"
    assert loaded.provenance.tier_map == {"Task": "Tasks"}
    assert loaded.provenance.rules_applied is True
    assert loaded.subject is not None
    assert loaded.subject.id == "S001"
    assert loaded.rater == "MK"
    assert loaded.schema_path == "/tmp/fog-coa.json"
    assert loaded.schema_name == "FOG-COA"
    assert loaded.schema_version == "1.1"
    assert loaded.session_start_utc == "2024-03-01T09:31:22Z"
    assert loaded.videos[0].name == "Front"
    assert loaded.videos[0].fps_override == 29.97
    assert loaded.signals[0].name == "Lumbar IMU"
    assert loaded.signals[0].time_reference == "utc_epoch"
    assert loaded.signals[0].time_unit == "microseconds"
    assert loaded.signals[0].sync_method == "utc"
    assert loaded.signals[0].channels == ["acc_x", "acc_y"]
    assert loaded.signals[0].display_channels == ["acc_y"]
    assert loaded.model_paths == {"Walking Classifier": "models/walking.rime"}
    assert loaded.get_model_path("Walking Classifier") == session.session_dir / "models/walking.rime"
    assert loaded.model_settings["Walking Classifier"].params == {"threshold": 0.7}
    assert loaded.model_settings["Walking Classifier"].input_sources == {
        "left_ankle": "Lumbar IMU"
    }
    assert loaded.model_settings["Walking Classifier"].input_bindings == {
        "left_ankle": {"leftankle_ax": "acc_x"}
    }
    assert loaded.panel_visibility["clinical_outcomes"] is False
    assert loaded.panel_visibility["model_runner"] is False
    assert loaded.panel_visibility["annotation_list"] is True
    assert loaded.dock_layout_state == "dock-state-token"
    assert loaded.clinical_metrics[0].name == "%TF (session)"
    assert loaded.clinical_metrics[0].numerator == [{"lane": "FOG", "label": None}]
    assert loaded.clinical_metrics[0].denominator_type == "session"


def test_load_session_defaults_missing_rater_to_empty_string(tmp_path: Path) -> None:
    session_dir = tmp_path / "legacy-session"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "id": "ses-legacy",
                "name": "Legacy Session",
                "created": "2026-01-01T00:00:00Z",
                "modified": "2026-01-01T00:00:00Z",
                "primary_video": "",
                "videos": [],
                "signals": [],
                "model_settings": {},
                "provenance": {"origin": "manual"},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_session(session_dir)

    assert loaded.rater == ""
    assert loaded.schema_name == ""
    assert loaded.schema_version == ""
    assert loaded.clinical_metrics == []
    assert loaded.panel_visibility == DEFAULT_PANEL_VISIBILITY
    assert loaded.dock_layout_state == ""
