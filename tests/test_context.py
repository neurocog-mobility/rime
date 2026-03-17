from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rime_core import (
    AnnotationStore,
    CMFConfig,
    CMFPackage,
    ClinicalMetricSpec,
    InputBinding,
    LaneSchema,
    OutputMapping,
    ProtocolSchema,
    SessionProvenance,
    SignalConfig,
    Signal,
    VideoConfig,
    WorkingContext,
    save_session,
    create_session,
    load_session,
)


def _write_signal(path: Path, rows: str) -> None:
    path.write_text(rows, encoding="utf-8")


def test_working_context_open_loads_session_schema_annotations_and_signals(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "session",
        name="Demo",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        signals=[
            SignalConfig(
                path="imu.csv",
                name="Lumbar IMU",
                type="imu",
                format="csv",
                sampling_rate_hz=2.0,
                time_column="time",
                channels=["acc_x"],
            )
        ],
        provenance=SessionProvenance(origin="manual"),
    )
    session.schema_path = ""
    _write_signal(session.session_dir / "imu.csv", "time,acc_x\n0.0,1.0\n0.5,2.0\n")

    store = AnnotationStore()
    store._session_id = session.id
    store._session_name = session.name
    store.save(session.session_dir / "annotations" / "annotations.json")

    ctx = WorkingContext.open(session.session_dir)

    assert ctx.session is not None
    assert ctx.schema is not None
    assert ctx.rule_engine is not None
    assert ctx.store._session_id == session.id
    assert "Lumbar IMU" in ctx.signals


def test_working_context_applies_utc_session_offset(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "utc-session",
        name="UTC Demo",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        signals=[
            SignalConfig(
                path="imu.csv",
                name="Lumbar IMU",
                type="imu",
                format="csv",
                sampling_rate_hz=2.0,
                time_column="timestamp",
                time_reference="utc_epoch",
                time_unit="microseconds",
                channels=["acc_x"],
            )
        ],
    )
    session.session_start_utc = "2024-03-01T09:31:22Z"
    save_session(session)
    _write_signal(
        session.session_dir / "imu.csv",
        "timestamp,acc_x\n1709285482500000,1.0\n1709285483000000,2.0\n",
    )

    ctx = WorkingContext.open(session.session_dir)

    assert ctx.signals["Lumbar IMU"].offset_ms == 500.0
    assert ctx.signals["Lumbar IMU"].get_time_ms()[0] == 500.0


def test_working_context_warns_when_utc_signal_has_no_session_start(tmp_path: Path, caplog) -> None:
    session = create_session(
        session_dir=tmp_path / "utc-no-start",
        name="UTC Demo",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        signals=[
            SignalConfig(
                path="imu.csv",
                name="Lumbar IMU",
                type="imu",
                format="csv",
                sampling_rate_hz=2.0,
                time_column="timestamp",
                time_reference="utc_epoch",
                time_unit="microseconds",
                offset_ms=25.0,
                channels=["acc_x"],
            )
        ],
    )
    _write_signal(
        session.session_dir / "imu.csv",
        "timestamp,acc_x\n1709285482500000,1.0\n1709285483000000,2.0\n",
    )

    with caplog.at_level(logging.WARNING):
        ctx = WorkingContext.open(session.session_dir)

    assert "session_start_utc is not set" in caplog.text
    assert ctx.signals["Lumbar IMU"].offset_ms == 25.0


def test_set_source_offset_updates_signal_and_persists(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "offset-session",
        name="Offset Demo",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        signals=[
            SignalConfig(
                path="imu.csv",
                name="Lumbar IMU",
                type="imu",
                format="csv",
                sampling_rate_hz=2.0,
                time_column="time",
                offset_ms=25.0,
                channels=["acc_x"],
            )
        ],
    )
    _write_signal(session.session_dir / "imu.csv", "time,acc_x\n0.0,1.0\n0.5,2.0\n")

    ctx = WorkingContext.open(session.session_dir)
    ctx.set_source_offset("signal", "imu.csv", -40.0)

    assert ctx.session.signals[0].offset_ms == -40.0
    assert ctx.signals["Lumbar IMU"].offset_ms == -40.0
    assert load_session(session.session_dir).signals[0].offset_ms == -40.0


def test_set_source_offset_updates_video_and_persists(tmp_path: Path) -> None:
    session = create_session(
        session_dir=tmp_path / "video-offset-session",
        name="Video Offset Demo",
        videos=[VideoConfig(path="video.mp4", role="primary", offset_ms=0.0)],
    )

    ctx = WorkingContext.open(session.session_dir)
    ctx.set_source_offset("video", "video.mp4", 125.0)

    assert ctx.session.videos[0].offset_ms == 125.0
    assert load_session(session.session_dir).videos[0].offset_ms == 125.0


def test_create_annotation_autosaves_and_emits_store_changed(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "new-session",
        name="Demo",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    events: list[int] = []
    ctx.subscribe("store_changed", lambda store: events.append(len(store.all())))

    annotation, violations = ctx.create_annotation("FOG", "FOG", 100.0, 300.0)

    assert not violations
    assert annotation.id in ctx.store.annotations
    assert (ctx.session.session_dir / "annotations" / "annotations.json").exists()
    assert events[-1] == 3
    assert len(ctx.store.get_by_lane("Core")) == 1
    assert len(ctx.store.get_by_lane("Manifestations")) == 1


def test_accept_reject_edit_and_delete_annotation(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "workflow-session",
        name="Workflow",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Draft", 0.0, 100.0, ghost=True, confidence=0.4)

    accepted, _ = ctx.accept_ghost(annotation.id)
    assert accepted.ghost is False
    assert accepted.human_modified is False

    edited = ctx.edit_annotation(annotation.id, label="Final", confidence=1.5)
    assert edited.label == "Final"
    assert edited.confidence == 1.0
    assert edited.human_modified is False

    ctx.delete_annotation(annotation.id)
    assert ctx.store.get(annotation.id) is None


def test_editing_non_manual_annotation_marks_human_modified(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "provenance-session",
        name="Provenance",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation(
        "Notes",
        "Draft",
        0.0,
        100.0,
        source="model:demo",
        confidence=0.4,
    )
    annotation.origin_confidence = 0.4
    annotation.origin_start_ms = 0.0
    annotation.origin_end_ms = 100.0

    edited = ctx.edit_annotation(annotation.id, label="Final", confidence=0.6)

    assert edited.human_modified is True
    assert edited.origin_confidence == 0.4
    assert edited.origin_start_ms == 0.0
    assert edited.origin_end_ms == 100.0


def test_editing_manual_annotation_does_not_mark_human_modified(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "manual-provenance-session",
        name="Manual Provenance",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Draft", 0.0, 100.0)

    edited = ctx.edit_annotation(annotation.id, label="Final")

    assert edited.human_modified is False


def test_reject_ghost_removes_annotation(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "ghost-session",
        name="Ghosts",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Draft", 0.0, 100.0, ghost=True)

    ctx.reject_ghost(annotation.id)

    assert ctx.store.get(annotation.id) is None


def test_accept_ghost_raises_for_non_ghost(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "non-ghost-session",
        name="NonGhost",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Stable", 0.0, 100.0)

    with pytest.raises(ValueError, match="not a ghost"):
        ctx.accept_ghost(annotation.id)


def test_accept_reject_and_delete_raise_for_unknown_or_invalid_ids(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "errors-session",
        name="Errors",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Stable", 0.0, 100.0)

    with pytest.raises(KeyError):
        ctx.delete_annotation("missing")
    with pytest.raises(KeyError):
        ctx.accept_ghost("missing")
    with pytest.raises(KeyError):
        ctx.reject_ghost("missing")
    with pytest.raises(ValueError, match="not a ghost"):
        ctx.reject_ghost(annotation.id)


def test_edit_annotation_clamps_confidence_both_bounds(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "clamp-session",
        name="Clamp",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Draft", 0.0, 100.0, confidence=0.3)

    edited = ctx.edit_annotation(annotation.id, confidence=-0.1)
    assert edited.confidence == 0.0


def test_create_annotation_emits_violations(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "violations-session",
        name="Violations",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    seen: list[int] = []
    ctx.subscribe("violations", lambda violations: seen.append(len(violations)))

    ctx.create_annotation("Core", "Core", 0.0, 100.0)

    assert seen and seen[-1] >= 1


def test_create_annotation_uses_point_lane_metadata(tmp_path: Path) -> None:
    schema = ProtocolSchema(
        version="1.0",
        name="Point Demo",
        lanes=[
            LaneSchema(
                name="Steps",
                level=1,
                color="#fff",
                labels=["step"],
                lane_type="point",
            )
        ],
        groups=[],
        rules=[],
    )
    ctx = WorkingContext.create(
        session_dir=tmp_path / "point-session",
        name="Point Demo",
        schema=schema,
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )

    annotation, violations = ctx.create_annotation("Steps", "step", 100.0, 250.0)

    assert not violations
    assert annotation.event_type == "point"
    assert annotation.start_ms == 100.0
    assert annotation.end_ms == 100.0


def test_edit_annotation_preserves_point_event_bounds(tmp_path: Path) -> None:
    schema = ProtocolSchema(
        version="1.0",
        name="Point Demo",
        lanes=[
            LaneSchema(
                name="Steps",
                level=1,
                color="#fff",
                labels=["step"],
                lane_type="point",
            )
        ],
        groups=[],
        rules=[],
    )
    ctx = WorkingContext.create(
        session_dir=tmp_path / "edit-point-session",
        name="Edit Point Demo",
        schema=schema,
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Steps", "step", 100.0, 100.0)

    edited = ctx.edit_annotation(annotation.id, end_ms=250.0)

    assert edited.event_type == "point"
    assert edited.start_ms == 250.0
    assert edited.end_ms == 250.0


def test_run_inference_without_model_raises_error(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "no-model-session",
        name="NoModel",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    signal = Signal(
        name="imu",
        data=pd.DataFrame({"time": [0.0, 0.5], "acc_x": [1.0, 2.0], "acc_y": [3.0, 4.0]}),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x", "acc_y"],
    )

    with pytest.raises(Exception, match="No model loaded"):
        ctx.run_inference(
            [InputBinding("imu_window", signal)],
            [OutputMapping("fog_probability", "FOG", "FOG")],
        )


def test_check_signal_compatibility_and_run_inference(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "inference-session",
        name="Inference",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    signal = Signal(
        name="imu",
        data=pd.DataFrame(
            {
                "time": np.arange(50, dtype=float) / 10.0,
                "acc_x": np.linspace(0.0, 1.0, 50),
                "acc_y": np.linspace(1.0, 2.0, 50),
            }
        ),
        sampling_rate_hz=10.0,
        time_column="time",
        channels=["acc_x", "acc_y"],
    )
    ctx.signals["imu"] = signal

    class Runner:
        def __init__(self) -> None:
            self.values = [0.1, 0.2, 0.7, 0.8, 0.9, 0.2, 0.1, 0.1, 0.1]

        def predict(self, inputs):
            return {"fog_probability": np.array([self.values.pop(0)], dtype=np.float32)}

    ctx.loaded_model = CMFPackage(
        path=Path("dummy-model.rime"),
        config=CMFConfig(
            cmf_version="1.0",
            name="CompatModel",
            version="0.1.0",
            description="",
            license="",
            runtime_type="wrapper",
            runtime_entry="wrapper.py",
            inputs=[
                {
                    "name": "imu_window",
                    "type": "signal",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                }
            ],
            outputs=[
                {
                    "name": "fog_probability",
                    "type": "probability",
                    "shape": [1],
                    "labels": ["no_fog", "fog"],
                }
            ],
            inference_mode="windowed",
            window_size_ms=1000,
            stride_ms=500,
            threshold=0.5,
            parameters=[],
            labels={"events": {"FOG": {"description": "Freezing"}}},
            output_mappings=[],
        ),
        _runner=Runner(),
        _model_dir=Path("dummy-model"),
    )

    assert ctx.check_signal_compatibility("imu_window", signal) == []
    assert "missing required channels" in ctx.check_signal_compatibility(
        "imu_window",
        Signal(
            name="bad",
            data=pd.DataFrame({"time": [0.0, 0.5], "acc_x": [1.0, 2.0]}),
            sampling_rate_hz=10.0,
            time_column="time",
            channels=["acc_x"],
        ),
    )[0].lower()
    assert "sampling rate mismatch" in ctx.check_signal_compatibility(
        "imu_window",
        Signal(
            name="bad-rate",
            data=pd.DataFrame(
                {"time": np.arange(50, dtype=float) / 20.0, "acc_x": np.linspace(0, 1, 50), "acc_y": np.linspace(1, 2, 50)}
            ),
            sampling_rate_hz=20.0,
            time_column="time",
            channels=["acc_x", "acc_y"],
        ),
    )[0].lower()

    events: list[str] = []
    ctx.subscribe("store_changed", lambda store: events.append(f"store:{len(store.all())}"))
    ctx.subscribe("inference_complete", lambda result: events.append(f"inference:{len(result.annotations)}"))

    result = ctx.run_inference(
        [InputBinding("imu_window", signal)],
        [OutputMapping("fog_probability", "FOG", "FOG")],
    )

    assert len(result.annotations) == 1
    assert result.annotations[0].ghost is True
    assert events[-2:] == ["store:1", "inference:1"]


def test_multi_model_registry_supports_named_inference_and_unload(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "multi-model-session",
        name="MultiModel",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    signal = Signal(
        name="imu",
        data=pd.DataFrame(
            {
                "time": np.arange(50, dtype=float) / 10.0,
                "acc_x": np.linspace(0.0, 1.0, 50),
                "acc_y": np.linspace(1.0, 2.0, 50),
            }
        ),
        sampling_rate_hz=10.0,
        time_column="time",
        channels=["acc_x", "acc_y"],
    )
    ctx.signals["imu"] = signal

    class Runner:
        def __init__(self, values: list[float]) -> None:
            self.values = list(values)

        def predict(self, inputs):
            return {"fog_probability": np.array([self.values.pop(0)], dtype=np.float32)}

    def make_model(name: str, values: list[float]) -> CMFPackage:
        return CMFPackage(
            path=Path(f"{name}.rime"),
            config=CMFConfig(
                cmf_version="1.0",
                name=name,
                version="0.1.0",
                description="",
                license="",
                runtime_type="wrapper",
                runtime_entry="wrapper.py",
                inputs=[
                    {
                        "name": "imu_window",
                        "type": "signal",
                        "shape": [1, 10, 2],
                        "channels": ["acc_x", "acc_y"],
                        "sampling_rate_hz": 10,
                    }
                ],
                outputs=[
                    {
                        "name": "fog_probability",
                        "type": "probability",
                        "shape": [1],
                        "labels": ["no_fog", "fog"],
                    }
                ],
                inference_mode="windowed",
                window_size_ms=1000,
                stride_ms=500,
                threshold=0.5,
                parameters=[],
                labels={"events": {"FOG": {"description": "Freezing"}}},
                output_mappings=[],
            ),
            _runner=Runner(values),
            _model_dir=Path(name),
        )

    ctx.loaded_models = {
        "ModelA": make_model("ModelA", [0.1, 0.2, 0.7, 0.8, 0.9, 0.2, 0.1, 0.1, 0.1]),
        "ModelB": make_model("ModelB", [0.1] * 9),
    }

    assert ctx.check_signal_compatibility("imu_window", signal, model_name="ModelA") == []

    result = ctx.run_inference(
        [InputBinding("imu_window", signal)],
        [OutputMapping("fog_probability", "FOG", "FOG")],
        model_name="ModelA",
    )

    assert len(result.annotations) == 1
    assert result.annotations[0].source == "model:ModelA"

    ctx.unload_model("ModelA")

    assert "ModelA" not in ctx.loaded_models
    with pytest.raises(Exception, match="No model loaded"):
        ctx.run_inference(
            [InputBinding("imu_window", signal)],
            [OutputMapping("fog_probability", "FOG", "FOG")],
            model_name="ModelA",
        )


def test_context_save_round_trip_preserves_annotations(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "roundtrip-session",
        name="RoundTrip",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    annotation, _ = ctx.create_annotation("Notes", "Saved", 10.0, 20.0, confidence=0.6)
    ctx.save()

    reopened = WorkingContext.open(ctx.session.session_dir)

    loaded = reopened.store.get(annotation.id)
    assert loaded is not None
    assert loaded.label == "Saved"
    assert loaded.confidence == 0.6
    assert loaded.human_modified is False
    assert loaded.origin_confidence is None
    assert loaded.origin_start_ms is None
    assert loaded.origin_end_ms is None


def test_update_clinical_metrics_persists_to_session(tmp_path: Path) -> None:
    ctx = WorkingContext.create(
        session_dir=tmp_path / "clinical-session",
        name="Clinical",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )

    metrics = [
        ClinicalMetricSpec(
            name="%TF (session)",
            numerator=[{"lane": "FOG", "label": None}],
            denominator_type="session",
            denominator=[],
        )
    ]
    ctx.update_clinical_metrics(metrics)

    reopened = WorkingContext.open(ctx.session.session_dir)
    assert reopened.session.clinical_metrics[0].name == "%TF (session)"
