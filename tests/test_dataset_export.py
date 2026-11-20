from copy import deepcopy
from dataclasses import asdict
import json

import pandas as pd
import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtTest import QTest

import test_native_review as review_tests
from rime_core.annotations import Annotation
from rime_core.dataset_export import export_workspace_dataset
from rime_core.review_workspace import ReviewWorkspace
from rime_ui.presentation.dataset_export import DatasetExportDialog

workspace_fixture = review_tests.workspace_fixture
app_fixture = review_tests.app_fixture
measured = review_tests.measured
candidates = review_tests.candidates


@pytest.mark.parametrize("review", [False, True])
def test_export_only_retained_annotations(measured, candidates, tmp_path, review):
    workspace = measured
    if review:
        workspace = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
        case = workspace.selection(workspace.input_refs("Event", "Freeze"))
        workspace.save_decision(case, "union")
        # Task annotations remain unresolved and must not appear in the dataset.
    else:
        workspace.data["suggestion_runs"] = [dict(
            id="run", kind="rule", name="Suggestions", suggestions=[dict(
                annotation=asdict(Annotation("pending", "Event", "Freeze", 800, 900)),
                decision="pending",
            )],
        )]
    before = deepcopy(workspace.data)
    destination = tmp_path / "dataset"
    destination.mkdir()  # Both new and existing empty folders are supported.
    count = export_workspace_dataset(
        workspace.data, destination, "01", "02", timing_verified=True,
    )
    events = pd.read_csv(next(destination.rglob("*_events.tsv")), sep="\t")
    assert set(events.rime_annotation_id) == {a["id"] for a in workspace.data["annotations"]}
    assert "pending" not in set(events.rime_annotation_id)
    assert count == len([p for p in destination.rglob("*") if p.is_file()])
    assert not list(destination.rglob("*_motion.tsv"))
    assert workspace.data == before
    with pytest.raises(ValueError, match="empty"):
        export_workspace_dataset(workspace.data, destination, "01", "02", timing_verified=True)


def test_signal_export_preserves_alignment_and_clip_samples(measured, tmp_path):
    source = next(s for s in measured.data["sources"] if s["kind"] == "signal")
    source["config"]["offset_ms"] = 150
    source["synchronization_note"] = "Aligned to Video 1"
    destination = tmp_path / "dataset"
    export_workspace_dataset(
        measured.data, destination, "01", "01", timing_verified=True,
        export_motion=True, export_clips=True,
    )
    motion = pd.read_csv(next(destination.rglob("*_motion.tsv")), sep="\t", header=None)
    assert motion.iloc[:, 0].tolist() == [0, 1, 0]
    sidecar = json.loads(next(destination.glob("sub-*/ses-*/motion/*_motion.json")).read_text())
    registration = sidecar["RIMETimelineRegistration"]
    assert registration["EffectiveOffsetSeconds"] == 0.15
    assert registration["SynchronizationMethod"] == "Aligned to Video 1"
    clips = pd.read_parquet(next(destination.rglob("*.parquet")))
    assert clips.loc[clips.annotation_id == "a", "time_offset"].tolist() == [0.05, 0.15, 0.25]


def test_failed_export_leaves_no_partial_dataset(measured, tmp_path, monkeypatch):
    import rime_core.dataset_export as module

    destination = tmp_path / "dataset"
    def fail(store, context, signals, staging, **options):
        staging.mkdir()
        (staging / "partial.tsv").write_text("partial")
        raise OSError("disk full")
    monkeypatch.setattr(module, "export_bids_dataset", fail)
    with pytest.raises(OSError, match="disk full"):
        export_workspace_dataset(measured.data, destination, "01", "01", timing_verified=True)
    assert not destination.exists()
    assert not list(tmp_path.glob(".rime-export-*"))


def test_export_validates_metadata_timing_and_sampling(measured, tmp_path):
    destination = tmp_path / "dataset"
    with pytest.raises(ValueError, match="Participant"):
        export_workspace_dataset(measured.data, destination, "", "01", timing_verified=True)
    with pytest.raises(ValueError, match="Confirm"):
        export_workspace_dataset(measured.data, destination, "01", "01")
    source = next(s for s in measured.data["sources"] if s["kind"] == "signal")
    source["config"]["sampling_rate_hz"] = 20
    with pytest.raises(ValueError, match="regularly sampled"):
        export_workspace_dataset(
            measured.data, destination, "01", "01", timing_verified=True, export_motion=True,
        )
    assert not destination.exists()


def test_dialog_exports_snapshot_in_background(measured, tmp_path, app_fixture):
    measured.data["research_context"] = {"participant": "sub-01", "visit": "ses-02"}
    dialog = DatasetExportDialog(measured)
    dialog.location.setText(str(tmp_path / "dataset"))
    dialog.show()
    dialog.start_export()
    assert "Confirm" in dialog.status.text()
    assert not dialog.busy
    dialog.timing.setChecked(True)
    dialog.start_export()
    assert dialog.busy
    dialog.reject()
    assert dialog.isVisible()
    timer = QElapsedTimer()
    timer.start()
    while dialog.busy and timer.elapsed() < 5000:
        QTest.qWait(10)
    assert not dialog.busy
    assert dialog.status.text().startswith("Exported")
    assert (tmp_path / "dataset" / "sub-01" / "ses-02").is_dir()
    dialog.close()
    dialog.deleteLater()


@pytest.mark.parametrize("review", [False, True])
def test_export_menu_opens_shared_dialog(
    measured, candidates, tmp_path, app_fixture, monkeypatch, review,
):
    from rime_ui.presentation.window import RimeWindow
    from rime_ui.presentation.review_workspace import ReviewWindow

    opened = []
    monkeypatch.setattr(DatasetExportDialog, "exec", lambda self: opened.append(self.snapshot))
    workspace = measured
    if review:
        workspace = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
        workspace.save(tmp_path / "review.json")
        window = ReviewWindow(workspace)
    else:
        workspace.save(tmp_path / "workspace.json")
        window = RimeWindow()
        assert not window.export_action.isEnabled()
        assert window.open_workspace_path(workspace.path)
    file_menu = window.menuBar().actions()[0].menu()
    action = next(a for a in file_menu.actions() if a.text() == "Export dataset…")
    assert action.isEnabled()
    action.trigger()
    assert opened[0]["id"] == workspace.data["id"]
    window.close()
    window.deleteLater()
