from copy import deepcopy
from dataclasses import replace
import json

import pytest
from PySide6.QtTest import QTest
import test_measurement_capture as capture_tests
from rime_core.cmf import CMFLoader
from rime_core.suggestions import execute, admit, pending, decide, assist
from rime_core.measurement_capture import capture_measurements, preview_measurements
from rime_core.annotation_workspace import AnnotationWorkspace
from rime_core.records import SignalSource
from rime_core.annotations import Annotation
from rime_core.record_inspection import verify_record

workspace_fixture = capture_tests.workspace_fixture
app_fixture = capture_tests.app_fixture
measured = capture_tests.measured


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "example.cmf"
    root.mkdir()
    (root / "labels.json").write_text("{}")
    (root / "config.json").write_text(
        json.dumps(
            dict(
                cmf_version="1.1",
                name="Deterministic test",
                version="1",
                runtime={"type": "wrapper", "entry": "wrapper.py"},
                inputs=[{"name": "input", "type": "signal", "channels": ["value"]}],
                outputs=[{"name": "events", "type": "interval"}],
                inference={"mode": "whole_signal", "threshold": 0.5},
                parameters=[],
                output_mappings=[{"output_name": "events", "lane": "Event", "label": "Freeze"}],
            )
        )
    )
    (root / "wrapper.py").write_text(
        'import numpy as np\nclass CMFModel:\n def predict(self, inputs, params):\n  return {"events": np.array([[10,40],[60,90],[110,140]])}\n'
    )
    return CMFLoader.load(root)


def run(package, workspace):
    source = workspace.data["sources"][1]
    config = SignalSource(**source["config"])
    return execute(
        package,
        deepcopy(workspace.data),
        [{"name": "input", "source": config.id, "channels": {"value": "value"}}],
        [{"output_name": "events", "lane": "Event", "label": "Freeze"}],
        {},
        [0, 200],
    )


def test_run_review_resume_export(measured, package, tmp_path):
    before = preview_measurements(measured.data, 2000)
    result = run(package, measured)
    admit(measured, result)
    assert len(pending(measured.data)) == 3
    assert preview_measurements(measured.data, 2000) == before
    ids = [i["annotation"]["id"] for _, i in pending(measured.data)]
    decide(measured, ids[0], "accept")
    second = Annotation(**pending(measured.data)[0][1]["annotation"])
    decide(measured, ids[1], "modify", replace(second, end_ms=100))
    measured.save(tmp_path / "workspace.json")
    restored = AnnotationWorkspace.open(measured.path)
    assert len(pending(restored.data)) == 1
    doc = capture_measurements(restored.data, 2000)
    assert all(verify_record(doc, root)["matches"] for root in doc.records)
    reviews = [n["rime:data"] for n in doc.nodes.values() if "rime:AnnotationReview" in n["@type"]]
    actions = [d["action"] for r in reviews for d in r["decisions"]]
    assert "modify" in actions and "unresolved" in actions
    decide(restored, ids[2], "reject_remaining")
    doc = capture_measurements(restored.data, 2000)
    assert "reject_remaining" in str(doc.nodes)
    assert str(tmp_path) not in str(doc.nodes)
    assert any(n["rime:data"].get("status") == "proposed" for n in doc.nodes.values())


def test_bad_output_admission_is_atomic(measured, package):
    result = run(package, measured)
    result["suggestions"][0]["annotation"]["label"] = "invalid"
    before = deepcopy(measured.data)
    with pytest.raises(ValueError):
        admit(measured, result)
    assert measured.data == before


def test_native_review_ui(app_fixture, measured, package):
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_ui.presentation.suggestions import RunConfiguration

    editor = AnnotationEditor(measured)
    editor.set_duration(2000)
    config = RunConfiguration(editor, package)
    config.end.setValue(0.2)
    config.submit()
    assert config.result() == 1
    editor.suggestions.run(package, *config.arguments)
    for _ in range(500):
        QTest.qWait(20)
        if not editor.suggestions.busy:
            break
    assert len(pending(measured.data)) == 3
    editor.suggestions.move(1)
    editor.suggestions.decision("accept")
    assert len(pending(measured.data)) == 2
    assert len(measured.data["annotations"]) == 4
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


def test_protocol_assistance_is_pending(measured):
    measured.data["protocol"]["rules"] = [
        {
            "trigger": "create",
            "on_lane": "Event",
            "action": "auto_create",
            "target_lane": "Task",
            "target_label": "Walk",
            "ghost": True,
        }
    ]
    item = Annotation("new", "Event", "Freeze", 1100, 1200)
    measured.put_annotation(item)
    assist(measured, item)
    assert len(pending(measured.data)) == 1
    assert measured.store.get(pending(measured.data)[0][1]["annotation"]["id"]) is None


def test_signal_offset_changes_proposal_times(measured, package):
    source = measured.data["sources"][1]
    measured.set_offset(source["config"]["id"], 50)
    result = run(package, measured)
    assert result["execution"]["time_range"] == [50, 200]
    assert result["suggestions"][0]["annotation"]["start_ms"] == 60
    assert result["sources"][0]["source"]["config"]["offset_ms"] == 50


def test_annotation_pilot_fits_small_window_with_pending_suggestions(
    measured, package, tmp_path, app_fixture
):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QPushButton
    from rime_ui.presentation.window import RimeWindow

    admit(measured, run(package, measured))
    measured.save(tmp_path / "workspace.json")
    window = RimeWindow()
    assert window.open_workspace_path(measured.path)
    window.show()
    window.resize(1320, 860)
    QTest.qWait(100)
    window.resize(1100, 700)
    QTest.qWait(100)
    editor = window.editor
    assert window.width() == 1100 and window.height() == 700
    assert editor.suggestions.strip.isVisible()
    assert editor.signals.height() >= editor.signals.minimumSizeHint().height()
    signal_bottom = editor.signals.mapTo(editor, QPoint(0, editor.signals.height())).y()
    assert signal_bottom < editor.play.mapTo(editor, QPoint(0, 0)).y()
    for tile, caption, value in editor.measurements.tiles.values():
        assert caption.height() >= caption.fontMetrics().height()
        assert value.height() >= value.fontMetrics().height()
        assert value.geometry().bottom() < tile.height()
    for control in editor.findChildren(QPushButton):
        if control.isVisible():
            bounds = QRect(control.mapTo(editor, QPoint(0, 0)), control.size())
            assert editor.rect().contains(bounds), control.text()
    editor.pause()
    window.close()
    window.deleteLater()
    app_fixture.processEvents()


def test_computational_capture_retains_synchronization_notes_at_execution(measured, package):
    source_id = measured.data["sources"][1]["config"]["id"]
    measured.set_synchronization_note(source_id, "Pre-aligned using acquisition timestamps")
    result = run(package, measured)
    admit(measured, result)
    decide(measured, pending(measured.data)[0][1]["annotation"]["id"], "accept")
    measured.set_synchronization_note(source_id, "Updated after execution")
    document = capture_measurements(measured.data, 2000)
    computational = [
        node for node in document.nodes.values()
        if node.get("rime:data", {}).get("method") == "computational"
    ]
    assert computational
    notes = [
        usage["rime:data"]["alignment_validation"]
        for node in computational
        for usage in node["prov:qualifiedUsage"]
        if "alignment_validation" in usage.get("rime:data", {})
    ]
    assert notes == ["Pre-aligned using acquisition timestamps"]


def test_model_cut_retains_one_proposal_to_two_outputs(app_fixture, measured, package):
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    result = run(package, measured)
    admit(measured, result)
    identifier = result["suggestions"][0]["annotation"]["id"]
    decide(measured, identifier, "accept")
    editor = AnnotationEditor(measured)
    editor.lanes.select_annotation(identifier)
    editor.player.get_position_ms = lambda: 25
    editor.cut()
    doc = capture_measurements(measured.data, 2000)
    decisions = [
        d
        for n in doc.nodes.values()
        if "rime:AnnotationReview" in n["@type"]
        for d in n["rime:data"]["decisions"]
    ]
    assert any(d["action"] == "modify" and len(d["outputs"]) == 2 for d in decisions)
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


def test_modify_stays_pending_until_panel_accept(app_fixture, measured, package, tmp_path):
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    result = run(package, measured)
    admit(measured, result)
    original = deepcopy(result["suggestions"][0]["annotation"])
    identifier = original["id"]
    before = preview_measurements(measured.data, 2000)
    editor = AnnotationEditor(measured)
    editor.suggestions.select(identifier)
    # Exercise the actual Modify callback without driving a modal dialog.
    editor.annotation_dialog = lambda annotation, commit: commit(replace(annotation, end_ms=55))
    editor.suggestions.modify()
    editor.refresh()
    assert measured.store.get(identifier) is None
    assert preview_measurements(measured.data, 2000) == before
    assert editor.suggestions.current().end_ms == 55
    assert pending(measured.data)[0][1]["annotation"] == original
    editor.lanes.ghost_accept_requested.emit(identifier)
    assert measured.store.get(identifier) is None
    measured.save(tmp_path / "pending.json")
    restored = AnnotationWorkspace.open(measured.path)
    assert pending(restored.data)[0][1]["draft"]["end_ms"] == 55
    capture_measurements(restored.data, 2000)
    editor.suggestions.decision("accept")
    assert measured.store.get(identifier).end_ms == 55
    assert measured.data["suggestion_runs"][0]["suggestions"][0]["decision"] == "modify"
    capture_measurements(measured.data, 2000)
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


@pytest.mark.parametrize("choice", ["Continue review", "Accept remaining", "Reject remaining"])
def test_finish_review_choices(app_fixture, measured, package, monkeypatch, choice):
    from PySide6.QtWidgets import QMessageBox
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_core.suggestions import revise

    admit(measured, run(package, measured))
    items = list(pending(measured.data))
    first = Annotation(**items[0][1]["annotation"])
    revise(measured, first.id, replace(first, end_ms=55))
    before = len(measured.data["annotations"])
    editor = AnnotationEditor(measured)

    def click(box):
        assert {button.text() for button in box.buttons()} == {
            "Continue review",
            "Accept remaining",
            "Reject remaining",
        }
        assert box.defaultButton().text() == "Continue review"
        next(button for button in box.buttons() if button.text() == choice).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", click)
    editor.suggestions.finish()
    if choice == "Continue review":
        assert len(pending(measured.data)) == 3
        assert len(measured.data["annotations"]) == before
    else:
        assert not pending(measured.data)
        if choice == "Accept remaining":
            assert len(measured.data["annotations"]) == before + 3
            assert measured.store.get(first.id).end_ms == 55
        else:
            assert len(measured.data["annotations"]) == before
            assert all(
                item["decision"] == "reject_remaining"
                for item in measured.data["suggestion_runs"][0]["suggestions"]
            )
        capture_measurements(measured.data, 2000)
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


def test_incompatible_model_explains_missing_lane_without_changing_protocol(app_fixture, measured):
    from pathlib import Path
    from PySide6.QtWidgets import QPushButton, QLabel
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_ui.presentation.suggestions import RunConfiguration

    before = deepcopy(measured.data)
    editor = AnnotationEditor(measured)
    package = CMFLoader.load(Path("models/step-detector.cmf"))
    dialog = RunConfiguration(editor, package)
    _, lane, label = dialog.outputs[0]
    assert lane.count() == 0
    assert not lane.isEnabled() and not label.isEnabled()
    buttons = dialog.findChildren(QPushButton)
    assert not next(b for b in buttons if b.text() == "Run").isEnabled()
    assert not any(b.text().startswith("Add ") for b in buttons)
    assert any(
        "step_times" in message.text() and "requires a point lane" in message.text()
        for message in dialog.findChildren(QLabel)
    )
    assert measured.data == before
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


def test_package_summary_blocks_incompatible_output_before_accept(app_fixture, measured, package):
    from pathlib import Path
    from PySide6.QtWidgets import QLabel
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_ui.presentation.suggestions import package_summary

    editor = AnnotationEditor(measured)
    incompatible = package_summary(editor, CMFLoader.load(Path("models/step-detector.cmf")))
    assert incompatible.load_button.text() == "Accept"
    assert not incompatible.load_button.isEnabled()
    assert any(
        "step_times" in label.text() and "point lane" in label.text()
        for label in incompatible.findChildren(QLabel)
    )
    compatible = package_summary(editor, package)
    assert compatible.load_button.isEnabled()
    assert package._runner is None
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


def test_suggestion_sublane_and_loop_roi(app_fixture, measured, package):
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_core.suggestions import revise

    admit(measured, run(package, measured))
    editor = AnnotationEditor(measured)
    level = measured.schema.get_lane("Event").level
    lanes = editor.lanes
    assert lanes._lane_sources(level) == ["manual", "suggestions"]
    assert lanes._sub_row_y(level, "suggestions") > lanes._sub_row_y(level, "manual")
    assert lanes._primary_row_source("model:example") == "manual"
    identifier = editor.suggestions.selected
    item = editor.suggestions.current()
    revise(measured, identifier, replace(item, end_ms=55))
    editor.refresh()
    lanes.select_annotation(identifier)
    loops = []
    editor.player.set_loop = lambda start, end: loops.append((start, end))
    editor.loop.setChecked(True)
    assert editor.loop.isChecked()
    assert loops[-1] == (item.start_ms, 55)
    editor.loop.setChecked(False)
    assert lanes.get_loop_region() is None
    assert editor.overview._loop_start_ms is None
    assert editor.overview._loop_end_ms is None
    for _, proposal in list(pending(measured.data)):
        decide(measured, proposal["annotation"]["id"], "accept")
    editor.refresh()
    assert lanes._lane_sources(level) == ["manual"]
    assert not editor.suggestions.strip.isVisible()
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)


def test_annotation_selection_seeks_but_refresh_does_not(app_fixture, measured, package):
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_core.suggestions import revise

    admit(measured, run(package, measured))
    editor = AnnotationEditor(measured)
    positions = []
    editor.seek = positions.append
    editor.lanes.select_annotation("a")
    assert positions[-1] == measured.store.get("a").start_ms
    proposal = editor.suggestions.current()
    revise(measured, proposal.id, replace(proposal, start_ms=15))
    editor.refresh()
    editor.lanes.select_annotation(proposal.id)
    assert positions[-1] == 15
    positions.clear()
    editor.refresh()
    assert positions == []
    editor.pause()
    editor.deleteLater()
    QTest.qWait(10)
