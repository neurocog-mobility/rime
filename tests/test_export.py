from __future__ import annotations

from pathlib import Path
import subprocess

import pandas as pd
import pytest

from rime_core import (
    Annotation,
    AnnotationStore,
    compute_irr,
    ExportError,
    ExporterRegistry,
    ClinicalMetricSpec,
    Signal,
    SessionProvenance,
    SubjectInfo,
    VideoConfig,
    WorkingContext,
    create_session,
    export_irr_report,
    export_signal_clips,
    export_video_clips,
    export_session_report,
)
from rime_core.export import _find_ffmpeg


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
        )
    )
    return store


def _make_session(tmp_path: Path):
    session = create_session(
        session_dir=tmp_path / "session",
        name="Export Demo",
        videos=[VideoConfig(path="video.mp4", role="primary")],
        subject=SubjectInfo(id="S001"),
        provenance=SessionProvenance(origin="manual"),
    )
    session.rater = "AZ"
    return session


def test_exporter_registry_dispatches_parquet_and_excludes_ghosts_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        "session_id",
        "subject_id",
        "session_name",
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
        "export_timestamp",
        "rater",
        "human_modified",
        "origin_confidence",
        "origin_start_ms",
        "origin_end_ms",
    ]
    assert frame.iloc[0]["subject_id"] == "S001"
    assert frame.iloc[0]["event_type"] == "interval"
    assert frame.iloc[0]["rater"] == "AZ"


def test_export_parquet_includes_provenance_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
            human_modified=True,
            origin_confidence=0.65,
            origin_start_ms=110.0,
            origin_end_ms=240.0,
        )
    )

    registry.export("parquet", store, session, tmp_path / "annotations.parquet")

    row = captured["frame"].iloc[0]
    assert bool(row["human_modified"]) is True
    assert row["origin_confidence"] == 0.65
    assert row["origin_start_ms"] == 110.0
    assert row["origin_end_ms"] == 240.0


def test_exporter_registry_can_include_ghost_annotations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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


def test_exporter_registry_raises_for_unknown_format(tmp_path: Path) -> None:
    registry = ExporterRegistry.default()

    with pytest.raises(ExportError, match="No exporter registered"):
        registry.export(
            "csv",
            _make_store(),
            _make_session(tmp_path),
            tmp_path / "annotations.csv",
        )


def test_working_context_export_uses_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_export(
        store: AnnotationStore,
        session,
        output_path: Path,
        include_ghost: bool,
    ) -> None:
        captured["annotation_ids"] = [annotation.id for annotation in store.all()]
        captured["session_id"] = session.id
        captured["output_path"] = output_path
        captured["include_ghost"] = include_ghost

    ctx = WorkingContext.create(
        session_dir=tmp_path / "ctx-session",
        name="Ctx Export",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    ctx.store = _make_store()
    ctx.exporter_registry.register("fake", fake_export)

    ctx.export("fake", tmp_path / "out.fake", include_ghost=True)

    assert captured["annotation_ids"] == ["a1", "a2"]
    assert captured["include_ghost"] is True


def test_export_signal_clips_writes_windowed_rows_and_skips_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, pd.DataFrame] = {}

    def fake_to_parquet(self: pd.DataFrame, path: Path, index: bool = False) -> None:
        captured[path.name] = self.copy()

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fake_to_parquet)
    session = _make_session(tmp_path)
    store = AnnotationStore()
    store.add(
        Annotation(
            id="fog-1",
            lane="FOG",
            label="FOG",
            start_ms=1000.0,
            end_ms=2000.0,
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

    written = export_signal_clips(
        store,
        session,
        [signal],
        tmp_path / "exports",
        padding_ms=500.0,
    )

    assert written == 1
    assert list(captured) == ["clips_imu.parquet"]
    frame = captured["clips_imu.parquet"]
    assert list(frame.columns) == ["annotation_id", "time_offset_ms", "acc_x", "acc_y"]
    assert list(frame["annotation_id"]) == ["fog-1", "fog-1", "fog-1", "fog-1", "fog-1"]
    assert list(frame["time_offset_ms"]) == [-500.0, 0.0, 500.0, 1000.0, 1500.0]
    assert list(frame["acc_x"]) == [2, 3, 4, 5, 6]


def test_export_signal_clips_splits_large_exports_by_annotation_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
            {
                "time": [0.0, 0.5, 1.0, 2.0, 2.5, 3.0, 4.0, 4.5, 5.0],
                "acc_x": list(range(9)),
            }
        ),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x"],
    )

    written = export_signal_clips(
        store,
        session,
        [signal],
        tmp_path / "exports",
        rows_per_file=4,
    )

    assert written == 2
    assert captured == ["clips_Lumbar_IMU_part001.parquet", "clips_Lumbar_IMU_part002.parquet"]


def test_export_video_clips_raises_without_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rime_core.export.shutil.which", lambda name: None)
    monkeypatch.setattr("rime_core.export.os.access", lambda path, mode: False)

    with pytest.raises(ExportError, match="ffmpeg not found on PATH"):
        export_video_clips(_make_store(), _make_session(tmp_path), tmp_path / "exports")


def test_find_ffmpeg_uses_homebrew_fallback_when_path_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rime_core.export.shutil.which", lambda name: None)
    monkeypatch.setattr("rime_core.export.os.access", lambda path, mode: str(path) == "/opt/homebrew/bin/ffmpeg")

    class _FakePath:
        def __init__(self, value: str) -> None:
            self._value = value

        def is_file(self) -> bool:
            return self._value == "/opt/homebrew/bin/ffmpeg"

        def __str__(self) -> str:
            return self._value

    monkeypatch.setattr(
        "rime_core.export._FFMPEG_FALLBACK_PATHS",
        (_FakePath("/opt/homebrew/bin/ffmpeg"), _FakePath("/usr/local/bin/ffmpeg")),
    )

    assert _find_ffmpeg() == "/opt/homebrew/bin/ffmpeg"


def test_export_video_clips_runs_ffmpeg_for_interval_annotations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool, stdout, stderr) -> None:
        calls.append(cmd)

    monkeypatch.setattr("rime_core.export.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("rime_core.export.subprocess.run", fake_run)
    session = _make_session(tmp_path)
    session.videos = [
        VideoConfig(path="video.mp4", role="primary", offset_ms=100.0),
        VideoConfig(path="side.mp4", role="side", offset_ms=0.0),
    ]
    store = AnnotationStore()
    store.add(
        Annotation(
            id="fog-1",
            lane="FOG",
            label="FOG",
            start_ms=1000.0,
            end_ms=2000.0,
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
        )
    )

    written = export_video_clips(
        store,
        session,
        tmp_path / "exports",
        padding_ms=500.0,
        video_role="all",
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
        str(session.session_dir / "video.mp4"),
    ]
    assert calls[0][-2:] == ["copy", str(tmp_path / "exports" / "clips_video" / "primary_fog-1_FOG_1000ms.mp4")]
    assert calls[1][-1] == str(tmp_path / "exports" / "clips_video" / "side_fog-1_FOG_1000ms.mp4")


def test_export_video_clips_wraps_ffmpeg_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], check: bool, stdout, stderr) -> None:
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr("rime_core.export.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("rime_core.export.subprocess.run", fake_run)
    session = _make_session(tmp_path)
    store = AnnotationStore()
    store.add(
        Annotation(
            id="fog-1",
            lane="FOG",
            label="FOG",
            start_ms=1000.0,
            end_ms=2000.0,
        )
    )

    with pytest.raises(ExportError, match="ffmpeg failed for annotation 'fog-1'"):
        export_video_clips(store, session, tmp_path / "exports")


def test_export_session_report_writes_annotation_summary_and_clinical_metrics(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    session.rater = "AZ"
    session.clinical_metrics = [
        ClinicalMetricSpec(
            name="%TF (session)",
            numerator=[{"lane": "FOG", "label": None}],
            denominator_type="session",
            denominator=[],
        )
    ]
    output_path = tmp_path / "report.tsv"

    export_session_report(_make_store(), session, output_path, duration_ms=1000.0)

    content = output_path.read_text(encoding="utf-8")
    assert "# RIME Session Report" in content
    assert "# Rater:\tAZ" in content
    assert "Lane\tLabel\tEpisodes\tTotal_ms\tMean_ms\tPct_of_session" in content
    assert "FOG\t(all)\t1\t200\t200\t20.0" in content
    assert "Metric\tValue_pct\tNumerator_ms\tNumerator_episodes\tDenominator_ms\tDenominator_episodes" in content
    assert "%TF (session)\t20.0\t200\t1\t1000\t—" in content


def test_export_session_report_uses_union_for_summary_percentages(tmp_path: Path) -> None:
    session = _make_session(tmp_path)
    output_path = tmp_path / "overlap-report.tsv"
    store = AnnotationStore()
    store.add(
        Annotation(
            id="walk-1",
            lane="Tasks",
            label="Walk",
            start_ms=0.0,
            end_ms=800.0,
            source="manual",
        )
    )
    store.add(
        Annotation(
            id="walk-2",
            lane="Tasks",
            label="Walk",
            start_ms=400.0,
            end_ms=1000.0,
            source="manual",
        )
    )

    export_session_report(store, session, output_path, duration_ms=1000.0)

    content = output_path.read_text(encoding="utf-8")
    assert "Tasks\t(all)\t2\t1000\t500\t100.0" in content
    assert "Tasks\tWalk\t2\t1000\t500\t100.0" in content


def test_export_irr_report_writes_summary_and_per_label_sections(tmp_path: Path) -> None:
    session_a = _make_session(tmp_path)
    session_a.name = "Session A"
    session_a.rater = "AZ"
    session_b = _make_session(tmp_path)
    session_b.name = "Session B"
    session_b.rater = "MK"
    store_a = AnnotationStore()
    store_a.add(Annotation(id="a1", lane="FOG", label="FOG", start_ms=100.0, end_ms=300.0))
    store_b = AnnotationStore()
    store_b.add(Annotation(id="b1", lane="FOG", label="FOG", start_ms=120.0, end_ms=280.0))
    result = compute_irr(store_a, store_b, 1000.0, lane="FOG", frame_resolution_ms=100.0)
    output_path = tmp_path / "irr.tsv"

    export_irr_report(result, session_a, session_b, output_path, lane="FOG")

    content = output_path.read_text(encoding="utf-8")
    assert "# RIME IRR Report" in content
    assert "# Session A:\tSession A  (Rater: AZ)" in content
    assert "# Session B:\tSession B  (Rater: MK)" in content
    assert "# Lane:\tFOG" in content
    assert "# Source A:\t(all accepted sources)" in content
    assert "# Source B:\t(all accepted sources)" in content
    assert "Metric\tValue" in content
    assert "Matched episodes\t1" in content
    assert "Label\tκ\t% Agreement\tEpisode IoU\tMatched\tA-only\tB-only" in content
    assert "FOG\t1.00\t100.0\t0.80\t1\t0\t0" in content
