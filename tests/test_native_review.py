from copy import deepcopy
from dataclasses import replace
import uuid

import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
import test_measurement_capture as fixtures
from rime_core.annotation_workspace import AnnotationWorkspace
from rime_core.annotations import Annotation
from rime_core.review_workspace import ReviewWorkspace, load_input, compatible
from rime_core.measurement_capture import capture_measurements, preview_measurements
from rime_core.exchange import write_document, read_document
from rime_core.record_inspection import verify_record

workspace_fixture = fixtures.workspace_fixture
app_fixture = fixtures.app_fixture
measured = fixtures.measured


@pytest.fixture
def candidates(measured, tmp_path):
    measured.data["rater"] = "Rater A"
    measured.save(tmp_path / "a.json")
    other = AnnotationWorkspace(deepcopy(measured.data))
    other.data["id"] = uuid.uuid4().hex
    other.data["rater"] = "Rater B"
    other.put_annotation(replace(other.store.get("a"), start_ms=150))
    other.save(tmp_path / "b.json")
    return [load_input(tmp_path / "a.json"), load_input(tmp_path / "b.json")]


def test_native_review_roundtrip_and_provenance(candidates, tmp_path):
    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    task = review.selection(review.input_refs("Task", "Walk"))
    event = review.selection(review.input_refs("Event", "Freeze"))
    review.save_decision(task, "input:0")
    assert preview_measurements(review.data, 2000)[2]["result"]["value"] == 0
    review.save_decision(event, "union")
    assert preview_measurements(review.data, 2000)[0]["result"]["value"] == 0.6
    review.save(tmp_path / "review.json")
    restored = ReviewWorkspace.open(review.path)
    doc = capture_measurements(restored.data, 2000)
    write_document(tmp_path / "review.rime", doc)
    doc = read_document(tmp_path / "review.rime")
    assert all(verify_record(doc, root)["matches"] for root in doc.records)
    activities = [n for n in doc.nodes.values() if "rime:AnnotationReview" in n["@type"]]
    assert activities[-1]["rime:data"]["method"] == "adjudication"
    assert len(activities[-1]["prov:used"]) >= 2
    assert any(n["rime:data"].get("review_status") == "complete" for n in doc.nodes.values())
    # Input files may change/disappear after admission; frozen provenance remains.
    for candidate in candidates:
        from pathlib import Path

        Path(candidate["path"]).unlink()
    capture_measurements(restored.data, 2000)
    restored.unresolved(event["id"])
    doc = capture_measurements(restored.data, 2000)
    assert "unresolved" in str(doc.nodes)
    assert preview_measurements(restored.data, 2000)[2]["result"]["value"] == 0


def test_compatibility_rejects_protocol_video_and_duplicate(candidates):
    with pytest.raises(ValueError, match="already"):
        compatible(candidates[0], [candidates[0]])
    wrong = deepcopy(candidates[1])
    wrong["data"]["protocol"]["version"] = "other"
    with pytest.raises(ValueError, match="protocol"):
        compatible(wrong, candidates[:1])
    wrong = deepcopy(candidates[1])
    wrong["video_sha256"] = "different"
    with pytest.raises(ValueError, match="Video 1"):
        compatible(wrong, candidates[:1])


def test_decision_replacement_mean_and_custom_are_explicit(candidates):
    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    case = review.selection(review.input_refs("Event", "Freeze"))
    with pytest.raises(ValueError, match="one selected annotation"):
        review.spans(case, "mean")
    review.save_decision(case, "custom", [[100, 200], [400, 500]])
    assert len(review.data["annotations"]) == 2
    review.save_decision(case, "no_event")
    assert review.data["annotations"] == []
    review.undo()
    assert len(review.data["annotations"]) == 2
    review.redo()
    assert review.data["annotations"] == []
    capture_measurements(review.data, 2000)


def test_single_rater_point_verification(candidates):
    candidate = deepcopy(candidates[0])
    candidate["data"]["protocol"]["lanes"].append(
        dict(name="Steps", level=3, labels=["step"], color="#aaa", lane_type="point")
    )
    from dataclasses import asdict

    candidate["data"]["annotations"].append(
        asdict(Annotation("step", "Steps", "step", 300, 300, event_type="point"))
    )
    review = ReviewWorkspace.create_review("Verify", "Reviewer", [candidate])
    case = review.selection(review.input_refs("Steps", "step"))
    review.save_decision(case, "input:0")
    doc = capture_measurements(review.data, 2000)
    assert any(n["rime:data"].get("method") == "verification" for n in doc.nodes.values())


def test_review_ui_preview_save_and_live_measurements(
    app_fixture, candidates, tmp_path, monkeypatch
):
    from rime_ui.presentation.review_workspace import ReviewWindow

    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    review.save(tmp_path / "review.json")
    window = ReviewWindow(review)
    window.show()
    QTest.qWait(80)
    window.lane.setCurrentText("Task")
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("input:0"))
    assert window.editor.preview == [[0, 1000]]
    assert review.data["annotations"] == []
    window.save_decision()
    assert review.data["annotations"]
    window.lane.setCurrentText("Event")
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("union"))
    assert window.editor.preview == [[100, 700]]
    window.save_decision()
    assert window.editor.preview is None
    assert len(window.editor.lanes._lane_sources(2)) == 3
    assert window.editor.measurements.previews[0]["result"]["value"] == 0.6
    assert not window.editor.run_model_button.isVisible()
    window.edit_decision()
    window.choice.setCurrentText("Custom boundaries")
    positions = []
    window.editor.seek = positions.append
    window.bounds.cellWidget(0, 1).setValue(0.8)
    assert positions[-1] == 800
    assert window.editor.preview[0][1] == 800
    window.save_decision()
    window.save()
    assert ReviewWorkspace.open(review.path).data["annotations"] == review.data["annotations"]
    window.close()
    QTest.qWait(10)


def test_new_region_is_a_draft_until_saved(app_fixture, candidates, tmp_path):
    from rime_ui.presentation.review_workspace import ReviewWindow

    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    review.save(tmp_path / "review.json")
    window = ReviewWindow(review)
    window.lane.setCurrentText("Event")
    original = deepcopy(review.data)
    assert not hasattr(window, "counter")
    positions = []
    window.editor.seek = positions.append
    window.new_region()
    window.bounds.cellWidget(0, 0).setValue(0.8)
    window.bounds.cellWidget(0, 1).setValue(0.9)
    assert window.editor.preview == [[800, 900]]
    assert positions[-1] == 900
    assert review.data == original
    assert not window.new_decision_button.isEnabled()
    assert window.custom_controls.isHidden()
    identifier = next(a.id for a in window.editor.lanes._store.all() if a.id.startswith("input:"))
    window.editor.lanes.annotation_selected.emit(identifier)
    assert window.creating and window.editor.preview == [[800, 900]]
    window.cancel_draft()
    assert review.data == original
    assert window.editor.draft_region is None
    assert window.new_decision_button.isEnabled()
    window.new_region()
    window.bounds.cellWidget(0, 0).setValue(0.8)
    window.bounds.cellWidget(0, 1).setValue(0.7)
    assert not window.save_decision_button.isEnabled()
    window.bounds.cellWidget(0, 1).setValue(0.9)
    assert window.save_decision()
    assert review.data["annotations"][0]["start_ms"] == 800
    assert not window.has_draft()
    window.history(False)
    assert review.data == original  # One undo removes region AND decision.
    window.history(True)
    assert len(review.data["annotations"]) == 1
    window.save()
    window.close()


def test_review_navigation_resolves_pending_decisions(
    app_fixture, candidates, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox
    from rime_ui.presentation.review_workspace import ReviewWindow

    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    review.save(tmp_path / "review.json")
    window = ReviewWindow(review)
    window.lane.setCurrentText("Event")
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("union"))
    assert window.has_draft()
    identifier = next(a.id for a in window.editor.lanes._store.all() if a.id.startswith("input:"))
    window.editor.lanes.annotation_selected.emit(identifier)
    assert window.editor.preview == [[100, 700]]
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    assert window.has_draft()
    window.lane.setCurrentText("Task")
    assert window.lane.currentText() == "Event"
    assert window.has_draft()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Save)
    window.lane.setCurrentText("Task")
    assert len(review.data["annotations"]) == 1
    assert not window.has_draft()
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("input:0"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Discard)
    window.lane.setCurrentText("Event")
    assert len(review.data["annotations"]) == 1
    assert not window.has_draft()
    window.save()
    window.close()


def select_all(window):
    window.new_decision()
    for i in range(window.inputs_list.count()):
        window.inputs_list.item(i).setCheckState(Qt.CheckState.Checked)


def test_disjoint_inputs_can_be_grouped_and_overlaps_split(candidates, tmp_path):
    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    assert review.data["review_cases"] == []
    refs = review.input_refs("Event", "Freeze")
    # One annotation from each source, including nonoverlapping ones.
    refs = [
        next(r for r in refs if r["index"] == 0 and r["annotation"] == "a"),
        next(r for r in refs if r["index"] == 1 and r["annotation"] == "b"),
    ]
    case = review.selection(refs)
    review.save_decision(case, "custom", [[100, 700]])
    assert len(review.input_refs("Event", "Freeze", unresolved=True)) == 2
    assert len(review.data["annotations"]) == 1
    overlapping = review.selection(refs[:1])
    review.save_decision(overlapping, "no_event")
    assert set(review.shared_input_warnings()) == {case["id"], overlapping["id"]}
    review.unresolved(overlapping["id"])
    assert review.shared_input_warnings() == {}
    # Reopen releases selected inputs, allowing any new grouping.
    review.unresolved(case["id"])
    for ref in refs:
        review.save_decision(review.selection([ref]), "input:" + str(ref["index"]))
    assert len(review.data["annotations"]) == 2
    review.save(tmp_path / "review.json")
    restored = ReviewWorkspace.open(review.path)
    assert restored.data == review.data
    capture_measurements(restored.data, 2000)


def test_saved_decision_selection_can_be_revised(app_fixture, candidates, tmp_path):
    from rime_ui.presentation.review_workspace import ReviewWindow

    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    review.save(tmp_path / "review.json")
    window = ReviewWindow(review)
    window.lane.setCurrentText("Event")
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("union"))
    assert window.save_decision()
    assert len(review.input_refs(unresolved=True)) == 2
    window.edit_decision()
    window.inputs_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert window.save_decision()
    assert len(review.input_refs(unresolved=True)) == 3
    assert len(review.data["review_cases"]) == 1
    window.remove_decision()
    assert len(review.input_refs(unresolved=True)) == 6
    assert review.data["annotations"] == []
    window.save()
    window.close()


def test_shared_input_markers_include_no_output_decisions(app_fixture, candidates, tmp_path):
    from rime_ui.presentation.review_workspace import ReviewWindow
    from PySide6.QtWidgets import QPushButton

    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    review.save(tmp_path / "review.json")
    window = ReviewWindow(review)
    window.lane.setCurrentText("Event")
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("union"))
    window.save_decision()
    first = window.editing_id
    select_all(window)
    window.choice.setCurrentIndex(window.choice.findData("no_event"))
    window.save_decision()
    assert len(review.shared_input_warnings()) == 2
    assert capture_measurements(review.data, 2000).records
    assert all(window.saved_decisions.item(i).text().startswith("⚠") for i in range(2))
    assert "Decision 2" in window.saved_decisions.item(0).toolTip()
    assert set(window.editor.lanes.annotation_warnings) == {
        a["id"] for a in review.data["annotations"]
    }
    assert not window.inputs_list.isEnabled()  # Select to inspect, Edit to change.
    assert not any(
        b.text() in ("Previous", "Next", "Finish review", "Reopen decision")
        for b in window.findChildren(QPushButton)
        if not window.editor.isAncestorOf(b)
    )
    window.remove_decision()
    assert review.shared_input_warnings() == {}
    assert window.editor.lanes.annotation_warnings == {}
    window.load_decision(first)
    window.edit_decision()
    assert window.inputs_list.isEnabled()
    window.cancel_draft()
    window.save()
    doc = capture_measurements(review.data, 2000)
    assert doc.records
    window.close()


def test_review_uses_shared_playback_without_editing_inputs(app_fixture, candidates, tmp_path):
    from PySide6.QtCore import QPoint
    from rime_ui.presentation.review_workspace import ReviewWindow

    review = ReviewWorkspace.create_review("Review", "Reviewer", candidates)
    review.save(tmp_path / "review.json")
    before = deepcopy(review.data)
    window = ReviewWindow(review)
    window.resize(1100, 700)
    window.show()
    QTest.qWait(100)
    editor = window.editor
    assert editor.overview.parent() is editor.lanes
    assert editor.overview.isVisible()
    assert not editor.add_button.isVisible()
    assert not editor.lanes._primary_track_editable()
    assert window.size().width() == 1100
    panel = window.new_button.parentWidget()
    assert window.new_button.geometry().right() < panel.width()
    QTest.mouseClick(editor.lanes, Qt.MouseButton.LeftButton,
                     pos=QPoint(round(editor.lanes._time_to_x(500)), 8))
    assert editor.lanes._current_position_ms == pytest.approx(500, abs=10)
    assert review.data["review_inputs"] == before["review_inputs"]
    assert review.data["annotations"] == before["annotations"]
    window.close()
