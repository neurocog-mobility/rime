from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import shutil

import pytest

from rime_core import (
    CalculationTemplate,
    ProtocolSchema,
    ResearchContext,
    SignalSource,
    VideoSource,
    WorkingContext,
)
from rime_core.workspace import storage
from rime_core.workspace.models import SignalSelection


def _state(context):
    return json.loads((context.workspace.root / context.workspace.working_state).read_text())


def test_native_objects_save_without_outcome_or_session(tmp_path):
    context = WorkingContext.create_workspace(
        tmp_path / "work", "Trial", research=ResearchContext(study_id="S", participant_id="P")
    )
    annotation, _ = context.create_annotation("FOG", "FOG", 1000, 2000)
    reopened = WorkingContext.open(context.workspace.path)
    assert reopened.store.get(annotation.id).end_ms == 2000
    assert reopened.research.participant_id == "P"
    assert reopened.annotation_set.timeline_id == reopened.recordings.timeline.id
    assert reopened.workspace.id != reopened.annotation_set.id
    assert _state(reopened)["measurements"] == []
    assert not hasattr(reopened, "session")
    assert not (context.workspace.root / "session.json").exists()
    assert "annotations" not in asdict(context.workspace)


def test_source_locations_and_view_preferences_stay_outside_scientific_state(tmp_path):
    signal = tmp_path / "imu.csv"
    signal.write_text("time,ax\n0,1\n0.5,2\n")
    context = WorkingContext.create_workspace(
        tmp_path / "work",
        "Trial",
        signals=[
            SignalSelection(
                str(signal),
                SignalSource("imu", "csv", 2, "time", name="Shin", channels=["ax"]),
                ["ax"],
            )
        ],
        videos=[(tmp_path / "view.mp4", VideoSource(offset_ms=125))],
    )
    source = context.recordings.signals[0]
    raw = json.dumps(_state(context))
    assert str(tmp_path) not in raw
    assert "source_locations" not in raw and "display_channels" not in raw
    assert "samples" not in raw
    assert context.workspace.source_path(source.id) == signal
    assert context.signals[source.id].get_time_ms().tolist() == [0, 500]
    reopened = WorkingContext.open(context.workspace.path)
    assert reopened.recordings.signals[0].id == source.id
    assert reopened.workspace.view.display_channels[source.id] == ["ax"]


def test_same_named_sources_have_distinct_identity(tmp_path):
    context = WorkingContext.create_workspace(tmp_path / "work", "Duplicates")
    for name in ["left", "right"]:
        path = tmp_path / f"{name}.csv"
        path.write_text("time,ax\n0,1\n1,2\n")
        context.add_signal(path, SignalSource("imu", "csv", 1, "time", name="IMU"))
    context.save()
    reopened = WorkingContext.open(context.workspace.path)
    assert len(reopened.signals) == 2
    assert len(set(reopened.signals)) == 2


def test_protocol_survives_original_file_removal(tmp_path):
    schema = ProtocolSchema.default()
    path = schema.save(tmp_path / "protocol.json")
    context = WorkingContext.create_workspace(
        tmp_path / "work", "Protocol", schema=ProtocolSchema.load(path)
    )
    path.unlink()
    assert WorkingContext.open(context.workspace.path).schema.to_dict() == schema.to_dict()


def test_missing_recordings_do_not_prevent_annotation_work(tmp_path):
    context = WorkingContext.create_workspace(
        tmp_path / "work", "Missing", videos=[("missing.mp4", VideoSource())]
    )
    annotation, _ = context.create_annotation("FOG", "FOG", 1, 2)
    reopened = WorkingContext.open(context.workspace.path)
    reopened.edit_annotation(annotation.id, end_ms=3)
    assert WorkingContext.open(context.workspace.path).store.get(annotation.id).end_ms == 3


def test_failed_manifest_commit_keeps_previous_complete_state(tmp_path, monkeypatch):
    context = WorkingContext.create_workspace(tmp_path / "work", "Atomic")
    annotation, _ = context.create_annotation("FOG", "FOG", 1, 2)
    before = context.workspace.path.read_bytes()
    write = storage._atomic_write

    def fail(path, data):
        if path.name == "workspace.json":
            raise OSError("simulated disk failure")
        write(path, data)

    monkeypatch.setattr(storage, "_atomic_write", fail)
    with pytest.raises(OSError):
        context.edit_annotation(annotation.id, end_ms=3)
    assert context.workspace.path.read_bytes() == before
    assert WorkingContext.open(context.workspace.path).store.get(annotation.id).end_ms == 2


def test_view_or_local_location_change_does_not_change_scientific_snapshot(tmp_path):
    context = WorkingContext.create_workspace(
        tmp_path / "work", "Views", videos=[("view.mp4", VideoSource())]
    )
    before = context.workspace.working_state
    context.workspace.view.snap_points = [15.5]
    context.workspace.source_locations[context.recordings.videos[0].id] = str(
        tmp_path / "renamed.mp4"
    )
    context.save()
    assert context.workspace.working_state == before
    assert WorkingContext.open(context.workspace.path).workspace.view.snap_points == [15.5]


def test_workspace_copy_preserves_source_and_annotation_identity_but_edits_independently(tmp_path):
    context = WorkingContext.create_workspace(
        tmp_path / "first", "Copy", videos=[("view.mp4", VideoSource())]
    )
    annotation, _ = context.create_annotation("FOG", "FOG", 1, 2)
    copied = context.save_workspace_copy(tmp_path / "second")
    assert copied.workspace.id != context.workspace.id
    assert copied.annotation_set.id == context.annotation_set.id
    assert copied.recordings == context.recordings
    assert copied.workspace.source_path(
        copied.recordings.videos[0].id
    ) == context.workspace.source_path(context.recordings.videos[0].id)
    copied.edit_annotation(annotation.id, end_ms=5)
    assert WorkingContext.open(context.workspace.path).store.get(annotation.id).end_ms == 2
    assert WorkingContext.open(copied.workspace.path).store.get(annotation.id).end_ms == 5


def test_moved_workspace_reopens(tmp_path):
    context = WorkingContext.create_workspace(tmp_path / "first", "Move")
    context.create_annotation("FOG", "FOG", 1, 2)
    shutil.move(context.workspace.root, tmp_path / "moved")
    assert len(WorkingContext.open(tmp_path / "moved").store.all()) == 3


@pytest.mark.parametrize("version", ["0.1", "unsupported"])
def test_old_or_unknown_workspace_formats_are_rejected(tmp_path, version):
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps({"format": "rime-workspace", "version": version}))
    with pytest.raises(ValueError, match="Unsupported workspace"):
        WorkingContext.open(path)


def test_session_json_is_rejected_without_conversion(tmp_path):
    path = tmp_path / "session.json"
    path.write_text('{"version":"1.0","name":"Old session"}')
    with pytest.raises(ValueError, match="Unsupported workspace"):
        WorkingContext.open(path)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("damage", ["missing", "corrupt", "escape", "timeline", "duplicate"])
def test_invalid_saved_state_fails_explicitly(tmp_path, damage):
    context = WorkingContext.create_workspace(
        tmp_path / "work", "Invalid", videos=[("view.mp4", VideoSource())]
    )
    path = context.workspace.root / context.workspace.working_state
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_text("{}")
    else:
        manifest = json.loads(context.workspace.path.read_text())
        if damage == "escape":
            manifest["working_state"] = "../outside.json"
        else:
            state = _state(context)
            if damage == "timeline":
                state["annotation_set"]["timeline_id"] = "unknown"
            else:
                state["recordings"]["videos"] *= 2
            raw = json.dumps(state).encode()
            target = (
                context.workspace.root / "working" / (hashlib.sha256(raw).hexdigest() + ".json")
            )
            target.write_bytes(raw)
            manifest["working_state"] = str(target.relative_to(context.workspace.root))
        context.workspace.path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        WorkingContext.open(context.workspace.path)


def test_nonempty_destination_refused(tmp_path):
    (tmp_path / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="empty folder"):
        WorkingContext.create_workspace(tmp_path, "No overwrite")
    assert (tmp_path / "keep.txt").read_text() == "keep"


def test_templates_are_not_saved_measurements(tmp_path):
    context = WorkingContext.create_workspace(tmp_path / "work", "Templates")
    context.update_clinical_metrics([CalculationTemplate("FOG", numerator=[{"lane": "FOG"}])])
    reopened = WorkingContext.open(context.workspace.path)
    assert reopened.calculation_templates[0].name == "FOG"
    assert _state(reopened)["measurements"] == []


def test_utc_alignment_and_manual_offsets_preserve_annotation_times(tmp_path):
    path = tmp_path / "imu.csv"
    path.write_text("time,ax\n1709285482500000,1\n1709285483000000,2\n")
    context = WorkingContext.create_workspace(
        tmp_path / "work",
        "Alignment",
        signals=[
            SignalSelection(
                str(path),
                SignalSource(
                    "imu", "csv", 2, "time", time_reference="utc_epoch", time_unit="microseconds"
                ),
            )
        ],
        videos=[("view.mp4", VideoSource())],
    )
    context.recordings.timeline.origin_utc = "2024-03-01T09:31:22Z"
    annotation, _ = context.create_annotation("FOG", "FOG", 1000, 2000)
    source = context.recordings.signals[0]
    context.set_source_offset("signal", source.id, 125)
    context.set_source_offset("video", context.recordings.videos[0].id, -250)
    reopened = WorkingContext.open(context.workspace.path)
    assert reopened.signals[source.id].get_time_ms().tolist() == [625, 1125]
    assert reopened.store.get(annotation.id).start_ms == 1000
    assert reopened.recordings.videos[0].offset_ms == -250
    assert reopened.recordings.signals[0].sync_method == "manual"
