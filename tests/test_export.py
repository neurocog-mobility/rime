from __future__ import annotations
import json
from pathlib import Path
import uuid
import subprocess
import pandas as pd
import pytest
from rime_core import (
    Annotation,
    AnnotationStore,
    BidsSignalInput,
    SignalSource,
    bids_session_paths,
    export_bids_dataset,
    export_bids_events,
    export_bids_motion,
    compute_irr,
    derive_matched_episode_interval,
    ExportError,
    ExporterRegistry,
    CalculationTemplate,
    Signal,
    ResearchContext,
    VideoSource,
    WorkingContext,
    export_irr_report,
    export_matched_episode_parquet,
    export_signal_clips,
    export_video_clips,
    export_workspace_report,
)
from rime_core.io.exporters import _find_ffmpeg


def _make_store() -> AnnotationStore:
    store = AnnotationStore()
    store.add(
        Annotation(
            id="a1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=300.0,
            source="manual",
            ghost=False,
            confidence=0.9,
        )
    )
    store.add(
        Annotation(
            id="a2",
            lane="Notes",
            label="Draft",
            start_ms=400.0,
            end_ms=450.0,
            source="model:demo",
            ghost=True,
            confidence=0.4,
            confidence_type="model_probability",
        )
    )
    return store


def _make_session(tmp_path: Path):
    session = WorkingContext.create_workspace(
        directory=tmp_path / ("work-" + uuid.uuid4().hex),
        name="Export Demo",
        videos=[("video.mp4", VideoSource(role="primary"))],
        research=ResearchContext(participant_id="S001"),
    )
    session.annotation_set.rater = "AZ"
    session.research.bids_session_id = "explicit-bids-session"
    session.workspace.source_path(session.recordings.videos[0].id).touch()
    session.recordings.timeline.recording_relative_timing_verified = True
    return session


def test_exporter_registry_dispatches_parquet_and_excludes_ghosts_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured["path"] = path
        captured["index"] = index
        captured["frame"] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    registry = ExporterRegistry.default()
    session = _make_session(tmp_path)
    store = _make_store()
    output_path = tmp_path / "exports" / "annotations.parquet"
    registry.export("parquet", store, session, output_path)
    frame = captured["frame"]
    assert captured["path"] == output_path
    assert captured["index"] is False
    assert list(frame["annotation_id"]) == ["a1"]
    assert list(frame.columns) == [
        "annotation_set_id",
        "subject_id",
        "annotation_set_name",
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
        "confidence_type",
        "export_timestamp",
        "rater",
        "human_modified",
        "origin_confidence",
        "origin_start_ms",
        "origin_end_ms",
    ]
    assert frame.iloc[0]["subject_id"] == "S001"
    assert frame.iloc[0]["event_type"] == "interval"
    assert frame.iloc[0]["confidence_type"] == "human_rating"
    assert frame.iloc[0]["rater"] == "AZ"


def test_export_parquet_includes_provenance_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, pd.DataFrame] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured["frame"] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    registry = ExporterRegistry.default()
    session = _make_session(tmp_path)
    store = AnnotationStore()
    store.add(
        Annotation(
            id="model-1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=250.0,
            source="model:demo",
            confidence=0.7,
            confidence_type="model_probability",
            human_modified=True,
            origin_confidence=0.65,
            origin_start_ms=110.0,
            origin_end_ms=240.0,
        )
    )
    registry.export("parquet", store, session, tmp_path / "annotations.parquet")
    row = captured["frame"].iloc[0]
    assert bool(row["human_modified"]) is True
    assert row["confidence_type"] == "model_probability"
    assert row["origin_confidence"] == 0.65
    assert row["origin_start_ms"] == 110.0
    assert row["origin_end_ms"] == 240.0


def test_derive_matched_episode_interval_supports_export_modes() -> None:
    ann_a = Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0)
    ann_b = Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0)
    assert derive_matched_episode_interval(ann_a, ann_b, "average") == (110.0, 290.0)
    assert derive_matched_episode_interval(ann_a, ann_b, "intersection") == (120.0, 280.0)
    assert derive_matched_episode_interval(ann_a, ann_b, "union") == (100.0, 300.0)
    assert derive_matched_episode_interval(ann_a, ann_b, "rater_a") == (100.0, 300.0)
    assert derive_matched_episode_interval(ann_a, ann_b, "rater_b") == (120.0, 280.0)


def test_export_matched_episode_parquet_uses_selected_mode_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured["path"] = path
        captured["index"] = index
        captured["frame"] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    session_a = _make_session(tmp_path)
    session_a.annotation_set.name = "Session A"
    session_b = _make_session(tmp_path)
    session_b.annotation_set.name = "Session B"
    store_a = AnnotationStore()
    store_a.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0))
    store_b = AnnotationStore()
    store_b.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0))
    result = compute_irr(store_a, store_b, 1000.0, lane="FOG", frame_resolution_ms=100.0)
    output_path = tmp_path / "matched-average.parquet"
    export_matched_episode_parquet(
        result,
        session_a,
        session_b,
        output_path,
        lane="FOG",
        source_a="manual",
        source_b="manual",
        mode="average",
    )
    frame = captured["frame"]
    row = frame.iloc[0]
    assert captured["path"] == output_path
    assert captured["index"] is False
    assert row["matched_episode_mode"] == "average"
    assert row["source"] == "matched:average"
    assert row["start_ms"] == 110.0
    assert row["end_ms"] == 290.0
    assert row["annotation_a_id"] == "a1"
    assert row["annotation_b_id"] == "b1"
    assert row["annotation_set_a_name"] == "Session A"
    assert row["annotation_set_b_name"] == "Session B"
    assert row["episode_iou"] == 0.8


def test_exporter_registry_can_include_ghost_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, pd.DataFrame] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured["frame"] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    registry = ExporterRegistry.default()
    registry.export(
        "parquet",
        _make_store(),
        _make_session(tmp_path),
        tmp_path / "annotations.parquet",
        include_ghost=True,
    )
    assert list(captured["frame"]["annotation_id"]) == ["a1", "a2"]


def test_export_includes_point_event_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, pd.DataFrame] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured["frame"] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    registry = ExporterRegistry.default()
    store = AnnotationStore()
    store.add(
        Annotation(
            id="step-1",
            lane="Steps",
            label="step",
            start_ms=250.0,
            end_ms=250.0,
            event_type="point",
        )
    )
    registry.export(
        "parquet",
        store,
        _make_session(tmp_path),
        tmp_path / "point-annotations.parquet",
        include_ghost=True,
    )
    frame = captured["frame"]
    assert frame.iloc[0]["event_type"] == "point"
    assert frame.iloc[0]["duration_ms"] == 0.0


def test_exporter_registry_dispatches_bids_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_to_csv(
        self: pd.DataFrame, path: Path, sep: str = "\t", index: bool = False, na_rep: str = "n/a"
    ) -> None:
        captured["path"] = path
        captured["frame"] = self.copy()
        captured["sep"] = sep
        captured["index"] = index
        captured["na_rep"] = na_rep

    monkeypatch.setattr(pd.DataFrame, "to_csv", fake_to_csv)
    registry = ExporterRegistry.default()
    store = AnnotationStore()
    store.add(
        Annotation(
            id="late", lane="FOG", label="FOG", start_ms=2000.0, end_ms=2500.0, source="manual"
        )
    )
    store.add(
        Annotation(
            id="early", lane="FOG", label="FOG", start_ms=500.0, end_ms=500.0, event_type="point"
        )
    )
    registry.export("bids", store, _make_session(tmp_path), tmp_path / "sub-S001_events.tsv")
    frame = captured["frame"]
    assert captured["path"] == tmp_path / "sub-S001_events.tsv"
    assert captured["sep"] == "\t"
    assert captured["index"] is False
    assert captured["na_rep"] == "n/a"
    assert list(frame.columns) == [
        "onset",
        "duration",
        "trial_type",
        "rime_lane",
        "rime_event_type",
        "rime_source",
        "rime_rater",
        "rime_human_modified",
        "rime_confidence",
        "rime_confidence_type",
        "rime_origin_onset",
        "rime_origin_offset",
        "rime_origin_confidence",
        "rime_annotation_id",
    ]
    assert list(frame["rime_annotation_id"]) == ["early", "late"]
    assert list(frame["duration"]) == [0.0, 0.5]
    assert list(frame["rime_confidence_type"]) == ["human_rating", "human_rating"]


def test_export_bids_events_sidecar_documents_rule_auto_create(tmp_path: Path) -> None:
    from rime_core import export_bids_events_sidecar

    output_path = tmp_path / "sub-S001_events.json"
    export_bids_events_sidecar(output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert "rule:auto_create" in payload["rime_source"]["Levels"]
    assert payload["rime_confidence_type"]["Levels"]["model_probability"]


def test_export_bids_events_blocks_when_timing_not_verified(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.recordings.timeline.recording_relative_timing_verified = False
    with pytest.raises(ExportError, match="recording-relative annotation timing"):
        export_bids_events(_make_store(), session, tmp_path / "events.tsv")


def test_export_bids_dataset_writes_raw_and_derivative_layout(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.research.bids_session_id = "ses-session_01"
    session.research = ResearchContext(
        participant_id="sub-Subject 01", condition="PD", bids_session_id="ses-session_01"
    )
    session.recordings.signals = [
        SignalSource(
            file_name="device-C7_sub-001_group-FR_ses-01_state-on_task-stwalk_sensor-15488.csv",
            name="device-C7_sub-001_group-FR_ses-01_state-on_task-stwalk_sensor-15488",
            type="imu",
            format="csv",
            sampling_rate_hz=2.0,
            time_column="time",
            channels=["acc_x", "acc_y"],
        )
    ]
    store = AnnotationStore()
    store.add(
        Annotation(
            id="fog-1", lane="FOG", label="FOG", start_ms=1000.0, end_ms=2000.0, source="manual"
        )
    )
    store.add(
        Annotation(
            id="step-1",
            lane="Steps",
            label="step",
            start_ms=1500.0,
            end_ms=1500.0,
            event_type="point",
            source="manual",
        )
    )
    signal = Signal(
        name="imu",
        data=pd.DataFrame(
            {"time": [0.0, 0.5, 1.0, 1.5, 2.0], "acc_x": [1, 2, 3, 4, 5], "acc_y": [5, 4, 3, 2, 1]}
        ),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x", "acc_y"],
    )
    signal.source_id = session.recordings.signals[0].id
    written = export_bids_dataset(store, session, [signal], tmp_path / "bids", padding_ms=500.0)
    paths = bids_session_paths(tmp_path / "bids", session)
    assert written >= 12
    assert (tmp_path / "bids" / "dataset_description.json").exists()
    assert (tmp_path / "bids" / "derivatives" / "rime" / "dataset_description.json").exists()
    assert (tmp_path / "bids" / "participants.tsv").exists()
    assert (tmp_path / "bids" / "participants.json").exists()
    assert paths.events_tsv.exists()
    assert paths.events_json.exists()
    assert paths.events_tsv.as_posix().endswith(
        "sub-Subject-01/ses-session-01/beh/sub-Subject-01_ses-session-01_task-fog_events.tsv"
    )
    assert paths.motion_tsv("sensor-15488").exists()
    assert paths.motion_json("sensor-15488").exists()
    assert paths.channels_tsv("sensor-15488").exists()
    assert paths.channels_json("sensor-15488").exists()
    assert paths.clips_parquet("sensor-15488").exists()
    assert paths.clips_json("sensor-15488").exists()
    events = pd.read_csv(paths.events_tsv, sep="\t")
    assert list(events["rime_annotation_id"]) == ["fog-1", "step-1"]
    assert list(events["duration"]) == [1.0, 0.0]
    dataset_description = json.loads(
        (tmp_path / "bids" / "dataset_description.json").read_text(encoding="utf-8")
    )
    from importlib.metadata import version

    assert dataset_description["GeneratedBy"][0]["Version"] == version("neurocog-rime-core")
    participants = pd.read_csv(tmp_path / "bids" / "participants.tsv", sep="\t")
    assert list(participants.columns) == ["participant_id", "condition"]
    assert participants.iloc[0]["participant_id"] == "sub-Subject-01"
    assert participants.iloc[0]["condition"] == "PD"
    motion_text = paths.motion_tsv("sensor-15488").read_text(encoding="utf-8").splitlines()
    assert motion_text[0] == "1\t5"
    channels = pd.read_csv(paths.channels_tsv("sensor-15488"), sep="\t")
    assert list(channels.columns) == [
        "name",
        "component",
        "type",
        "tracked_point",
        "units",
        "reference_frame",
    ]
    assert list(channels["type"]) == ["ACCEL", "ACCEL"]
    assert list(channels["reference_frame"]) == ["source", "source"]
    clips = pd.read_parquet(paths.clips_parquet("sensor-15488"))
    assert list(clips.columns) == ["annotation_id", "time_offset", "acc_x", "acc_y"]
    assert set(clips["annotation_id"]) == {"fog-1"}


def test_export_bids_motion_writes_headerless_tsv_and_channels(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.recordings.signals = [
        SignalSource(
            file_name="imu.csv",
            name="Lumbar IMU",
            type="imu",
            format="csv",
            sampling_rate_hz=2.0,
            time_column="time",
            channels=["acc_x", "gyro_z"],
        )
    ]
    signal = Signal(
        name="imu",
        data=pd.DataFrame({"time": [0.0, 0.5], "acc_x": [1.0, 2.0], "gyro_z": [0.1, 0.2]}),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x", "gyro_z"],
    )
    written = export_bids_motion(
        session,
        [BidsSignalInput(session.recordings.signals[0], signal, "Lumbar-IMU")],
        tmp_path / "bids",
    )
    paths = bids_session_paths(tmp_path / "bids", session)
    assert written == 4
    assert (
        paths.motion_tsv("Lumbar-IMU").read_text(encoding="utf-8").splitlines()[0]
        == "1.000000\t0.100000"
    )
    channels = pd.read_csv(paths.channels_tsv("Lumbar-IMU"), sep="\t")
    assert list(channels["type"]) == ["ACCEL", "GYRO"]
    assert list(channels["reference_frame"]) == ["source", "source"]
    channels_sidecar = json.loads(paths.channels_json("Lumbar-IMU").read_text(encoding="utf-8"))
    source_frame = channels_sidecar["reference_frame"]["Levels"]["source"]
    assert "orientation" in source_frame["Description"]


def test_export_bids_motion_records_effective_session_time_registration(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.recordings.signals = [
        SignalSource(
            file_name="imu.csv",
            name="Lumbar IMU",
            type="imu",
            format="csv",
            sampling_rate_hz=2.0,
            time_column="time",
            time_reference="relative",
            time_unit="seconds",
            offset_ms=125.0,
            sync_method="manual_offset",
            channels=["acc_x"],
        )
    ]
    signal = Signal(
        name="imu",
        data=pd.DataFrame({"time": [0.0, 0.5], "acc_x": [1.0, 2.0]}),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x"],
        offset_ms=125.0,
        time_reference="relative",
        time_unit="seconds",
    )
    export_bids_motion(
        session,
        [BidsSignalInput(session.recordings.signals[0], signal, "Lumbar-IMU")],
        tmp_path / "bids",
    )
    paths = bids_session_paths(tmp_path / "bids", session)
    sidecar = json.loads(paths.motion_json("Lumbar-IMU").read_text(encoding="utf-8"))
    registration = sidecar["RIMETimelineRegistration"]
    assert registration["EffectiveOffsetSeconds"] == 0.125
    assert registration["SynchronizationMethod"] == "manual_offset"
    assert registration["SourceTimeReference"] == "relative"
    assert registration["SourceTimeUnit"] == "seconds"
    reconstructed_times = [
        sample_index / sidecar["SamplingFrequency"] + registration["EffectiveOffsetSeconds"]
        for sample_index in range(2)
    ]
    assert reconstructed_times == [0.125, 0.625]


def test_exporter_registry_raises_for_unknown_format(tmp_path: Path) -> None:
    registry = ExporterRegistry.default()
    with pytest.raises(ExportError, match="No exporter registered"):
        registry.export("csv", _make_store(), _make_session(tmp_path), tmp_path / "annotations.csv")


def test_working_context_export_uses_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_export(
        store: AnnotationStore, session, output_path: Path, include_ghost: bool
    ) -> None:
        captured["annotation_ids"] = [annotation.id for annotation in store.all()]
        captured["annotation_set_id"] = session.annotation_set.id
        captured["output_path"] = output_path
        captured["include_ghost"] = include_ghost

    ctx = WorkingContext.create_workspace(
        directory=tmp_path / "ctx-session",
        name="Ctx Export",
        videos=[("video.mp4", VideoSource(role="primary"))],
    )
    ctx.annotation_set.annotations = _make_store()
    ctx.exporter_registry.register("fake", fake_export)
    ctx.export("fake", tmp_path / "out.fake", include_ghost=True)
    assert captured["annotation_ids"] == ["a1", "a2"]
    assert captured["include_ghost"] is True


def test_export_signal_clips_writes_windowed_rows_and_skips_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, pd.DataFrame] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured[path.name] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    session = _make_session(tmp_path)
    for video in session.recordings.videos:
        path = session.workspace.root / video.file_name
        path.touch()
        session.workspace.source_locations[video.id] = str(path)
    store = AnnotationStore()
    store.add(Annotation(id="fog-1", lane="FOG", label="FOG", start_ms=1000.0, end_ms=2000.0))
    store.add(
        Annotation(
            id="step-1",
            lane="Steps",
            label="step",
            start_ms=1500.0,
            end_ms=1500.0,
            event_type="point",
        )
    )
    signal = Signal(
        name="imu",
        data=pd.DataFrame(
            {
                "time": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
                "acc_x": [1, 2, 3, 4, 5, 6],
                "acc_y": [6, 5, 4, 3, 2, 1],
            }
        ),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x", "acc_y"],
    )
    written = export_signal_clips(store, session, [signal], tmp_path / "exports", padding_ms=500.0)
    assert written == 1
    assert list(captured) == ["clips_imu.parquet"]
    frame = captured["clips_imu.parquet"]
    assert list(frame.columns) == ["annotation_id", "time_offset_ms", "acc_x", "acc_y"]
    assert list(frame["annotation_id"]) == ["fog-1", "fog-1", "fog-1", "fog-1", "fog-1"]
    assert list(frame["time_offset_ms"]) == [-500.0, 0.0, 500.0, 1000.0, 1500.0]
    assert list(frame["acc_x"]) == [2, 3, 4, 5, 6]


def test_export_signal_clips_splits_large_exports_by_annotation_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured.append(path.name)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    session = _make_session(tmp_path)
    store = AnnotationStore()
    for index in range(3):
        store.add(
            Annotation(
                id=f"fog-{index}",
                lane="FOG",
                label="FOG",
                start_ms=float(index * 2000),
                end_ms=float(index * 2000 + 1000),
            )
        )
    signal = Signal(
        name="Lumbar IMU",
        data=pd.DataFrame(
            {"time": [0.0, 0.5, 1.0, 2.0, 2.5, 3.0, 4.0, 4.5, 5.0], "acc_x": list(range(9))}
        ),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x"],
    )
    written = export_signal_clips(store, session, [signal], tmp_path / "exports", rows_per_file=4)
    assert written == 2
    assert captured == ["clips_Lumbar_IMU_part001.parquet", "clips_Lumbar_IMU_part002.parquet"]


def test_export_video_clips_raises_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rime_core.io.exporters.shutil.which", lambda name: None)
    monkeypatch.setattr("rime_core.io.exporters.os.access", lambda path, mode: False)
    with pytest.raises(ExportError, match="ffmpeg not found on PATH"):
        export_video_clips(_make_store(), _make_session(tmp_path), tmp_path / "exports")


def test_find_ffmpeg_uses_homebrew_fallback_when_path_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rime_core.io.exporters.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "rime_core.io.exporters.os.access",
        lambda path, mode: str(path) == "/opt/homebrew/bin/ffmpeg",
    )

    class _FakePath:
        def __init__(self, value: str) -> None:
            self._value = value

        def is_file(self) -> bool:
            return self._value == "/opt/homebrew/bin/ffmpeg"

        def __str__(self) -> str:
            return self._value

    monkeypatch.setattr(
        "rime_core.io.exporters._FFMPEG_FALLBACK_PATHS",
        (_FakePath("/opt/homebrew/bin/ffmpeg"), _FakePath("/usr/local/bin/ffmpeg")),
    )
    assert _find_ffmpeg() == "/opt/homebrew/bin/ffmpeg"


def test_export_video_clips_runs_ffmpeg_for_interval_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, stdout, stderr) -> None:
        calls.append(cmd)

    monkeypatch.setattr("rime_core.io.exporters.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("rime_core.io.exporters.subprocess.run", fake_run)
    session = _make_session(tmp_path)
    session.recordings.videos = [
        VideoSource(file_name="video.mp4", role="primary", offset_ms=100.0),
        VideoSource(file_name="side.mp4", role="side", offset_ms=0.0),
    ]
    for video in session.recordings.videos:
        path = session.workspace.root / video.file_name
        path.touch()
        session.workspace.source_locations[video.id] = str(path)
    store = AnnotationStore()
    store.add(Annotation(id="fog-1", lane="FOG", label="FOG", start_ms=1000.0, end_ms=2000.0))
    store.add(
        Annotation(
            id="step-1",
            lane="Steps",
            label="step",
            start_ms=1500.0,
            end_ms=1500.0,
            event_type="point",
        )
    )
    written = export_video_clips(
        store, session, tmp_path / "exports", padding_ms=500.0, video_role="all"
    )
    assert written == 2
    assert len(calls) == 2
    assert calls[0][:8] == [
        "/usr/bin/ffmpeg",
        "-y",
        "-ss",
        "0.400",
        "-to",
        "2.400",
        "-i",
        str(session.workspace.root / "video.mp4"),
    ]
    assert calls[0][-2:] == [
        "copy",
        str(tmp_path / "exports" / "clips_video" / "primary_fog-1_FOG_1000ms.mp4"),
    ]
    assert calls[1][-1] == str(tmp_path / "exports" / "clips_video" / "side_fog-1_FOG_1000ms.mp4")


def test_export_video_clips_wraps_ffmpeg_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def fake_run(cmd: list[str], check: bool, stdout, stderr) -> None:
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr("rime_core.io.exporters.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("rime_core.io.exporters.subprocess.run", fake_run)
    session = _make_session(tmp_path)
    for video in session.recordings.videos:
        path = session.workspace.root / video.file_name
        path.touch()
        session.workspace.source_locations[video.id] = str(path)
    store = AnnotationStore()
    store.add(Annotation(id="fog-1", lane="FOG", label="FOG", start_ms=1000.0, end_ms=2000.0))
    with pytest.raises(ExportError, match="ffmpeg failed for annotation 'fog-1'"):
        export_video_clips(store, session, tmp_path / "exports")


def test_export_session_report_writes_annotation_summary_and_clinical_metrics(
    tmp_path: Path,
) -> None:
    session = _make_session(tmp_path)
    session.annotation_set.rater = "AZ"
    session.research.bids_session_id = "explicit-bids-session"
    session.workspace.source_path(session.recordings.videos[0].id).touch()
    session.calculation_templates = [
        CalculationTemplate(
            name="%TF (session)",
            numerator=[{"lane": "FOG", "label": None}],
            denominator_type="timeline",
            denominator=[],
        )
    ]
    output_path = tmp_path / "report.tsv"
    export_workspace_report(_make_store(), session, output_path, duration_ms=1000.0)
    content = output_path.read_text(encoding="utf-8")
    assert "# RIME Workspace Report" in content
    assert "# Rater:\tAZ" in content
    assert "Lane\tLabel\tEpisodes\tTotal_ms\tMean_ms\tPct_of_session" in content
    assert "FOG\t(all)\t1\t200\t200\t20.0" in content
    assert (
        "Metric\tValue_pct\tNumerator_ms\tNumerator_episodes\tDenominator_ms\tDenominator_episodes"
        in content
    )
    assert "%TF (session)\t20.0\t200\t1\t1000\t—" in content


def test_export_session_report_uses_union_for_summary_percentages(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    output_path = tmp_path / "overlap-report.tsv"
    store = AnnotationStore()
    store.add(
        Annotation(
            id="walk-1", lane="Tasks", label="Walk", start_ms=0.0, end_ms=800.0, source="manual"
        )
    )
    store.add(
        Annotation(
            id="walk-2", lane="Tasks", label="Walk", start_ms=400.0, end_ms=1000.0, source="manual"
        )
    )
    export_workspace_report(store, session, output_path, duration_ms=1000.0)
    content = output_path.read_text(encoding="utf-8")
    assert "Tasks\t(all)\t2\t1000\t500\t100.0" in content
    assert "Tasks\tWalk\t2\t1000\t500\t100.0" in content


def test_export_irr_report_writes_summary_and_per_label_sections(tmp_path: Path) -> None:
    session_a = _make_session(tmp_path)
    session_a.annotation_set.name = "Session A"
    session_a.annotation_set.rater = "AZ"
    session_b = _make_session(tmp_path)
    session_b.annotation_set.name = "Session B"
    session_b.annotation_set.rater = "MK"
    store_a = AnnotationStore()
    store_a.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0))
    store_b = AnnotationStore()
    store_b.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0))
    result = compute_irr(store_a, store_b, 1000.0, lane="FOG", frame_resolution_ms=100.0)
    output_path = tmp_path / "irr.tsv"
    export_irr_report(result, session_a, session_b, output_path, lane="FOG")
    content = output_path.read_text(encoding="utf-8")
    assert "# RIME IRR Report" in content
    assert "# Annotation set A:\tSession A  (Rater: AZ)" in content
    assert "# Annotation set B:\tSession B  (Rater: MK)" in content
    assert "# Lane:\tFOG" in content
    assert "# Source A:\t(all accepted sources)" in content
    assert "# Source B:\t(all accepted sources)" in content
    assert "Metric\tValue" in content
    assert "Match rate\t100.0%" in content
    assert "Matched episodes\t1" in content
    assert "Set IoU\t80.0%" in content
    assert "Label\tκ\tMatch rate\tSet IoU\tMatched\tA-only\tB-only" in content
    assert "FOG\t1.00\t100.0%\t80.0%\t1\t0\t0" in content


def test_export_irr_report_writes_undefined_kappa_for_empty_annotation_sets(tmp_path: Path) -> None:
    session_a = _make_session(tmp_path)
    session_b = _make_session(tmp_path)
    result = compute_irr(
        AnnotationStore(), AnnotationStore(), 1000.0, lane="FOG", frame_resolution_ms=100.0
    )
    output_path = tmp_path / "empty-irr.tsv"
    export_irr_report(result, session_a, session_b, output_path, lane="FOG")
    content = output_path.read_text(encoding="utf-8")
    assert "Cohen's κ\t—" in content


def test_signal_export_resolves_identity_even_with_duplicate_names(tmp_path):
    from rime_core.io.exporters import build_bids_signal_inputs

    context = WorkingContext.create_workspace(tmp_path / "work", "Identity")
    left = SignalSource("imu", "csv", 1, "time", name="IMU", units={"ax": "g"})
    right = SignalSource("imu", "csv", 1, "time", name="IMU", units={"ax": "m/s2"})
    context.recordings.signals = [left, right]

    def loaded(source):
        return Signal(
            "IMU",
            pd.DataFrame({"time": [0, 1], "ax": [1, 2]}),
            1,
            "time",
            ["ax"],
            source_id=source.id,
        )

    pairs = build_bids_signal_inputs(context, [loaded(right), loaded(left)])
    assert [pair.config.id for pair in pairs] == [right.id, left.id]
    assert pairs[0].config.units["ax"] == "m/s2"
    unidentified = loaded(left)
    unidentified.source_id = ""
    with pytest.raises(ExportError, match="match"):
        build_bids_signal_inputs(context, [unidentified])
