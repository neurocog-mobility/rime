"""One calculation basis from preview through exchange and independent inspection."""

from dataclasses import replace
import threading

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
import test_native_annotation_workspace as workspace_tests

from rime_core.annotations import Annotation
from rime_core.annotation_workspace import AnnotationWorkspace, import_annotations
from rime_core.measurement_capture import preview_measurements, capture_measurements, settings_for
from rime_core.exchange import write_document, read_document
from rime_core.record_inspection import verify_record, inspection_graph

workspace_fixture = workspace_tests.workspace
app_fixture = workspace_tests.app


@pytest.fixture
def measured(workspace_fixture):
    workspace = workspace_fixture
    schema = workspace.data["protocol"]
    schema["measurements"] = [
        dict(
            id=op,
            name=op,
            calculation=op,
            events={"lane": "Event", "label": "Freeze"},
            scope={"lane": "Task", "label": "Walk"},
        )
        for op in ("covered_duration", "percentage_coverage", "count")
    ]
    for a in [
        Annotation("scope", "Task", "Walk", 0, 1000),
        Annotation("a", "Event", "Freeze", 100, 400),
        Annotation("b", "Event", "Freeze", 300, 700),
    ]:
        workspace.put_annotation(a)
    return workspace


def test_union_duration_literal_count_and_protocol_scope(measured):
    p = preview_measurements(measured.data, 2000)
    assert [i["result"]["value"] for i in p] == [0.6, 60, 2]
    assert all(i["result"]["eligible_ms"] == 1000 for i in p)
    assert all(i["selection_ids"] == ["scope"] for i in p)
    assert all(i["result"]["contributors"] == ["a", "b"] for i in p)


def test_explicit_scope_clips_intervals_and_counts_once(measured):
    settings = settings_for(measured.data)
    settings["period"] = {"mode": "time", "start_ms": 350, "end_ms": 500}
    p = preview_measurements(measured.data, 2000, settings)
    assert [i["result"]["value"] for i in p] == [0.15, 100, 2]
    assert all(i["selection_ids"] is None for i in p)


def test_selected_scope_updates_but_deleted_selection_is_not_silently_replaced(measured):
    measured.data["measurement_settings"] = {
        "selected": ["count"],
        "period": {"mode": "annotations", "lanes": ["Task"], "all": False, "ids": ["scope"]},
    }
    measured.put_annotation(replace(measured.store.get("scope"), end_ms=200))
    assert preview_measurements(measured.data, 2000)[0]["result"]["value"] == 1
    measured.delete_annotation("scope")
    with pytest.raises(ValueError, match="removed"):
        preview_measurements(measured.data, 2000)


def test_no_task_is_undefined_not_full_video(measured):
    measured.delete_annotation("scope")
    p = preview_measurements(measured.data, 2000)
    assert all(x["result"]["value"] is None for x in p)
    assert all(x["result"]["reason"] == "empty_observation" for x in p)
    document = capture_measurements(measured.data, 2000)
    assert all(verify_record(document, root)["matches"] for root in document.records)


def test_native_export_is_fixed_and_recalculable_without_sources(measured, tmp_path):
    measured.data["rater"] = "Researcher A"
    document = capture_measurements(measured.data, 2000)
    path = tmp_path / "measurements.rime"
    write_document(path, document)
    before = path.read_bytes()
    measured.put_annotation(replace(measured.store.get("a"), end_ms=900))
    assert path.read_bytes() == before
    for source in measured.data["sources"]:
        from pathlib import Path

        Path(source["path"]).unlink()
    reopened = read_document(path)
    assert len(reopened.records) == 3
    assert all(verify_record(reopened, root)["matches"] for root in reopened.records)
    assert all(inspection_graph(reopened, root)["nodes"] for root in reopened.records)
    assert str(tmp_path) not in path.read_text()
    assert [
        n["rime:data"]["name"] for n in reopened.nodes.values() if n["@type"] == ["prov:Agent"]
    ] == ["Researcher A"]


def test_presynchronized_notes_survive_editor_save_and_record_exchange(
    measured, tmp_path, app_fixture
):
    from PySide6.QtWidgets import QPlainTextEdit
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    editor = AnnotationEditor(measured)
    editor.sources()
    source_id = measured.data["sources"][1]["config"]["id"]
    field = editor.alignment_dialog.findChild(
        QPlainTextEdit, f"synchronization_note_{source_id}"
    )
    note = "Aligned before import using hardware timestamps; checked against a tap."
    field.setPlainText(note)
    measured.save(tmp_path / "workspace.json")
    reopened = AnnotationWorkspace.open(measured.path)
    assert reopened.data["sources"][1]["config"]["offset_ms"] == 0
    assert reopened.data["sources"][1]["synchronization_note"] == note
    document = capture_measurements(reopened.data, 2000)
    path = tmp_path / "notes.rime"
    write_document(path, document)
    reopened.set_synchronization_note(source_id, "Later edit")
    captured = read_document(path)
    timings = [
        usage["rime:data"]
        for node in captured.nodes.values()
        for usage in node.get("prov:qualifiedUsage", [])
        if "alignment_validation" in usage.get("rime:data", {})
    ]
    assert timings
    assert all(t["alignment_validation"] == note for t in timings)
    assert all(t["mapping"]["offset_ms"] == 0 for t in timings)
    assert all(verify_record(captured, root)["matches"] for root in captured.records)
    editor.alignment_dialog.close()
    editor.pause()
    editor.close()
    editor.deleteLater()
    app_fixture.processEvents()


def test_import_branch_and_final_edits_retained_without_claiming_adjudication(measured, tmp_path):
    import pympi

    measured.data["annotations"] = []
    eaf = pympi.Elan.Eaf()
    eaf.add_tier("Task")
    eaf.add_annotation("Task", 0, 1000, "Walk")
    eaf.add_tier("Event")
    eaf.add_annotation("Event", 100, 400, "Freeze")
    path = tmp_path / "input.eaf"
    eaf.to_file(str(path))
    import_annotations(measured, path, {"Task": "Task", "Event": "Event"})
    original = capture_measurements(measured.data, 2000)
    assert not any("rime:AnnotationReview" in n["@type"] for n in original.nodes.values())
    event = next(a for a in measured.store.all() if a.lane == "Event")
    measured.put_annotation(replace(event, end_ms=600))
    edited = capture_measurements(measured.data, 2000)
    sets = [n["rime:data"] for n in edited.nodes.values() if "rime:AnnotationSet" in n["@type"]]
    assert len(sets) == 2
    assert {next(a["end_ms"] for a in s["annotations"] if a["lane"] == "Event") for s in sets} == {
        400,
        600,
    }
    review = next(
        n["rime:data"] for n in edited.nodes.values() if "rime:AnnotationReview" in n["@type"]
    )
    assert review["method"] == "verification"
    assert "no independent verification" in review["metadata"]["description"]
    assert {d["action"] for d in review["decisions"]} == {"accept", "modify"}
    assert "complete" not in {s["review_status"] for s in sets}
    assert all(verify_record(edited, root)["matches"] for root in edited.records)


def test_ui_configuration_persists_and_no_record_is_created_implicitly(
    measured, tmp_path, app_fixture
):
    app = app_fixture
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_ui.presentation.live_measurements import MeasurementConfiguration

    measured.save(tmp_path / "workspace.json")
    editor = AnnotationEditor(measured)
    editor.set_duration(2000)
    assert len(editor.measurements.previews) == 3
    config = MeasurementConfiguration(measured, 2000)
    config.mode.setCurrentIndex(1)
    config.start.setValue(0.35)
    config.end.setValue(0.5)
    measured.change(lambda d: d.update(measurement_settings=config.settings()))
    editor.measurements.refresh()
    assert editor.measurements.previews[0]["result"]["value"] == 0.15
    editor.save()
    assert AnnotationWorkspace.open(measured.path).data["measurement_settings"] == config.settings()
    assert not list(tmp_path.glob("*.rime"))
    config.close()
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_configuration_shrinks_when_optional_fields_are_hidden(measured, app_fixture):
    from PySide6.QtTest import QTest
    from rime_ui.presentation.live_measurements import MeasurementConfiguration

    config = MeasurementConfiguration(measured, 2000)
    config.show()
    QTest.qWait(50)
    compact_height = config.height()
    config.mode.setCurrentIndex(1)
    QTest.qWait(50)
    assert config.height() > compact_height
    config.start.setValue(0.35)
    config.mode.setCurrentIndex(2)
    config.all.setChecked(False)
    for lane in config.lanes.values():
        lane.setChecked(True)
    QTest.qWait(50)
    assert config.item_scroll.isVisible()
    config.all.setChecked(True)
    QTest.qWait(50)
    assert config.item_scroll.isHidden()
    config.mode.setCurrentIndex(0)
    QTest.qWait(50)
    assert config.height() == compact_height
    assert config.start.value() == 0.35
    config.close()
    config.deleteLater()
    app_fixture.processEvents()


def test_export_captures_click_time_state_while_editing_continues(
    measured, tmp_path, app_fixture, monkeypatch
):
    from rime_ui.presentation.annotation_editor import AnnotationEditor
    from rime_ui.presentation import live_measurements

    app = app_fixture

    editor = AnnotationEditor(measured)
    editor.set_duration(2000)
    ready = threading.Event()
    release = threading.Event()
    original = live_measurements.capture_measurements

    def held(data, duration):
        ready.set()
        assert release.wait(5)
        return original(data, duration)

    monkeypatch.setattr(live_measurements, "capture_measurements", held)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[-1]))
    path = tmp_path / "captured.rime"
    assert editor.measurements.export_path(path)
    assert ready.wait(3)
    measured.delete_annotation("b")
    release.set()
    for _ in range(500):
        QTest.qWait(10)
        if not editor.measurements.busy:
            break
    assert not editor.measurements.busy and not errors
    document = read_document(path)
    values = [document.nodes[root]["rime:data"]["value"] for root in document.records]
    assert values == [0.6, 60, 2]
    assert preview_measurements(measured.data, 2000)[-1]["result"]["value"] == 1
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()
