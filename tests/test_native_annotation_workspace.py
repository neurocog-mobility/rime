"""Editable workspace persistence and evidence alignment, without record adapters."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from rime_core.annotation_workspace import AnnotationWorkspace, source_entry, import_annotations
from rime_core.annotations import Annotation
from rime_core.records import VideoSource, SignalSource
from rime_core.schema import ProtocolSchema


@pytest.fixture
def workspace(tmp_path):
    import cv2
    import numpy as np

    video = tmp_path / "video.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 64))
    for _ in range(20):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    csv = tmp_path / "signal.csv"
    csv.write_text("time,value\n0,0\n0.1,1\n0.2,0\n")
    schema = ProtocolSchema.from_dict(
        {
            "version": "1",
            "name": "Test",
            "lanes": [
                {"name": "Task", "level": 1, "labels": ["Walk"], "color": "#444444"},
                {"name": "Event", "level": 2, "labels": ["Freeze"], "color": "#aa4444"},
            ],
            "rules": [],
            "groups": [],
        }
    )
    return AnnotationWorkspace.create(
        "Trial",
        schema,
        [source_entry(video, VideoSource(label="Video 1"), "video")],
        [
            source_entry(
                csv,
                SignalSource(
                    type="imu",
                    format="csv",
                    sampling_rate_hz=10,
                    time_column="time",
                    channels=["value"],
                ),
                "signal",
            )
        ],
    )


def test_save_edit_resume_undo_and_fixed_import(workspace, tmp_path):
    w = workspace
    a = Annotation("event", "Event", "Freeze", 100, 300)
    w.put_annotation(a)
    w.save(tmp_path / "workspace.json")
    assert not w.dirty
    w.put_annotation(replace(a, end_ms=450))
    assert w.dirty
    assert AnnotationWorkspace.open(w.path).store.get("event").end_ms == 300
    w.undo()
    assert not w.dirty
    w.redo()
    assert w.store.get("event").end_ms == 450
    w.save()
    assert AnnotationWorkspace.open(w.path).data == w.data
    assert not any(key in w.data for key in ("measurements", "records", "model_settings"))


def test_invalid_edit_and_primary_offset_are_atomic(workspace):
    before = deepcopy(workspace.data)
    with pytest.raises(ValueError):
        workspace.put_annotation(Annotation("x", "Event", "wrong", 0, 100))
    assert workspace.data == before
    with pytest.raises(ValueError):
        workspace.set_offset(workspace.data["sources"][0]["config"]["id"], 1000)
    assert workspace.data == before
    with pytest.raises(ValueError):
        workspace.change(lambda d: d.update(sources=[]))
    assert workspace.data == before


def test_save_failure_preserves_previous_file(workspace, tmp_path, monkeypatch):
    workspace.save(tmp_path / "workspace.json")
    before = workspace.path.read_bytes()
    workspace.put_annotation(Annotation("x", "Event", "Freeze", 0, 100))
    monkeypatch.setattr(
        "rime_core.annotation_workspace.os.replace",
        lambda *a: (_ for _ in ()).throw(OSError("disk")),
    )
    with pytest.raises(OSError):
        workspace.save()
    assert workspace.path.read_bytes() == before
    assert workspace.dirty


def test_eaf_boundaries_retained_and_edit_does_not_rewrite_import(workspace, tmp_path):
    import pympi

    eaf = pympi.Elan.Eaf()
    eaf.add_tier("Events")
    eaf.add_annotation("Events", 100, 300, "Freeze")
    path = tmp_path / "annotations.eaf"
    eaf.to_file(str(path))
    original = path.read_bytes()
    assert import_annotations(workspace, path, {"Events": "Event"}) == 1
    a = workspace.store.all()[0]
    workspace.put_annotation(replace(a, end_ms=500))
    assert workspace.data["imports"][0]["annotations"][0]["end_ms"] == 300
    assert path.read_bytes() == original


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_real_editor_signal_mapping_and_resume(workspace, tmp_path, app, monkeypatch):
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    workspace.save(tmp_path / "workspace.json")
    editor = AnnotationEditor(workspace)
    editor.set_duration(2000)
    workspace.put_annotation(Annotation("x", "Event", "Freeze", 100, 300))
    editor.refresh()
    original = deepcopy(workspace.data["annotations"])
    source = workspace.data["sources"][1]["config"]["id"]
    workspace.set_offset(source, 750)
    editor.refresh()
    assert editor.loaded_signals[source].get_time_ms().tolist() == [750, 850, 950]
    assert workspace.data["annotations"] == original
    editor.save()
    reopened = AnnotationWorkspace.open(workspace.path)
    assert reopened.data["sources"][1]["config"]["offset_ms"] == 750
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_open_failure_does_not_replace_working_editor(workspace, tmp_path, app, monkeypatch):
    from rime_ui.presentation.window import RimeWindow

    workspace.save(tmp_path / "workspace.json")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    window = RimeWindow()
    assert window.open_workspace_path(workspace.path)
    editor = window.editor
    invalid = tmp_path / "bad.json"
    invalid.write_text(json.dumps({"format": "old-session"}))
    assert not window.open_workspace_path(invalid)
    assert window.editor is editor
    assert window.pages.currentWidget() is editor
    window.close()
    window.deleteLater()
    app.processEvents()


def test_secondary_video_uses_inverse_mapping(app):
    from types import SimpleNamespace
    from rime_ui.widgets.multi_view_player import MultiViewPlayer

    positions = []
    player = MultiViewPlayer()
    player._panes = [
        SimpleNamespace(),
        SimpleNamespace(offset_ms=250, player=SimpleNamespace(setPosition=positions.append)),
    ]
    player._sync_secondaries(1000)
    assert positions == [750]
    player._panes = []
    player.deleteLater()


@pytest.mark.parametrize("align", [False, True])
def test_prepare_creates_real_workspace(workspace, tmp_path, app, monkeypatch, align):
    from rime_ui.presentation.window import RimeWindow
    from PySide6.QtWidgets import QPlainTextEdit

    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[-1]))
    window = RimeWindow()
    window.pending_sources = workspace.data["sources"]
    window.refresh_source_list()
    source_id = window.pending_sources[1]["config"]["id"]
    note = "Synchronized before import using hardware timestamps."
    window.setup_sync_notes.findChild(
        QPlainTextEdit, f"setup_synchronization_note_{source_id}"
    ).setPlainText(note)
    window.refresh_source_list()
    assert window.setup_sync_notes.findChild(
        QPlainTextEdit, f"setup_synchronization_note_{source_id}"
    ).toPlainText() == note
    window.protocols = [workspace.schema]
    window.protocol_field.setCurrentIndex(0)
    window.name_field.setText("Created trial")
    window.location_field.setText(str(tmp_path / "created"))
    window.align_choice.setChecked(align)
    window.create_workspace()
    assert not errors
    assert window.editor is not None
    path = tmp_path / "created" / "workspace.json"
    assert AnnotationWorkspace.open(path).data["name"] == "Created trial"
    assert AnnotationWorkspace.open(path).data["sources"][1]["synchronization_note"] == note
    if align:
        assert window.editor.alignment_dialog.findChild(
            QPlainTextEdit, f"synchronization_note_{source_id}"
        ).toPlainText() == note
        window.editor.alignment_dialog.close()
    assert window.pages.currentWidget() is window.editor
    assert not window.editor.workspace.dirty
    window.close()
    window.deleteLater()
    app.processEvents()


def test_secondary_view_holds_outside_recording_then_resumes(app):
    from types import SimpleNamespace
    from PySide6.QtMultimedia import QMediaPlayer
    from rime_ui.widgets.multi_view_player import MultiViewPlayer

    playing = QMediaPlayer.PlaybackState.PlayingState
    paused = QMediaPlayer.PlaybackState.PausedState
    state = {"value": playing}
    positions, visibility, labels = [], [], []
    secondary = SimpleNamespace(
        duration=lambda: 2000,
        playbackState=lambda: state["value"],
        pause=lambda: state.update(value=paused),
        play=lambda: state.update(value=playing),
        setPosition=positions.append,
    )
    widget = MultiViewPlayer()
    widget._panes = [
        SimpleNamespace(player=SimpleNamespace(playbackState=lambda: playing)),
        SimpleNamespace(
            player=secondary,
            offset_ms=500,
            _config=VideoSource(label="Video 2"),
            video_widget=SimpleNamespace(setVisible=visibility.append),
            _label=SimpleNamespace(setText=labels.append),
        ),
    ]
    widget._update_secondary_coverage(0)
    assert state["value"] == paused and visibility[-1] is False
    widget._update_secondary_coverage(600)
    assert positions == [100] and state["value"] == playing and visibility[-1] is True
    widget._update_secondary_coverage(700)
    assert positions == [100]  # no per-frame seek during normal playback
    widget._panes = []
    widget.deleteLater()


def test_signal_and_annotation_time_axes_align_after_layout(workspace, app):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtTest import QTest
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    editor = AnnotationEditor(workspace)
    editor.resize(1320, 860)
    editor.show()
    QTest.qWait(200)
    editor.set_duration(20000)
    for width, height, time_range in [(1320, 860, (0, 20000)), (1100, 700, (0, 20000)), (1100, 700, (4500, 10500))]:
        editor.resize(width, height)
        # Rebuilding plots and adding a scrollbar must preserve the coordinate system.
        workspace.data["protocol"]["lanes"] += [
            {"name": f"Extra {len(workspace.schema.lanes) + 1}", "level": len(workspace.schema.lanes) + 1,
             "labels": ["Event"], "color": "#444444"}
        ]
        editor.refresh()
        editor.view_range(*time_range)
        QTest.qWait(100)
        graphics = editor.signals.graphics_widget
        box = editor.signals._plots[0].getViewBox()
        start, end = time_range
        for time_ms in [start, (start + end) / 2, end]:
            signal_x = graphics.mapTo(editor, QPoint()).x() + box.mapViewToScene(QPointF(time_ms / 1000, 0)).x()
            annotation_x = editor.lanes.mapTo(editor, QPoint()).x() + editor.lanes._time_to_x(time_ms)
            assert abs(signal_x - annotation_x) < 1
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_annotation_height_follows_tracks_until_manually_resized(workspace, app):
    from PySide6.QtTest import QTest
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    editor = AnnotationEditor(workspace)
    editor.resize(1320, 860)
    editor.show()
    QTest.qWait(200)
    initial_height = editor.annotations_panel.height()
    original = deepcopy(workspace.data["protocol"])
    for index in range(3, 9):
        workspace.data["protocol"]["lanes"].append(
            {"name": f"Extra {index}", "level": index, "labels": ["Event"], "color": "#444444"}
        )
    editor.refresh()
    QTest.qWait(100)
    assert editor.annotations_panel.height() > initial_height
    editor.workspace_splitter.moveSplitter(editor.recordings_panel.height() - 20, 1)
    manual_height = editor.annotations_panel.height()
    workspace.data["protocol"] = original
    editor.refresh()
    QTest.qWait(100)
    assert editor.annotations_panel.height() == manual_height
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_add_action_opens_editable_interval_without_committing(workspace, app, monkeypatch):
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    editor = AnnotationEditor(workspace)
    editor.set_duration(2000)
    annotations = []
    monkeypatch.setattr(editor, "annotation_dialog", annotations.append)
    monkeypatch.setattr(editor.player, "get_position_ms", lambda: 1500)
    editor.add_at_playhead(2)
    annotation = annotations[0]
    assert (annotation.lane, annotation.start_ms, annotation.end_ms) == ("Event", 1500, 2000)
    assert workspace.store.all() == []
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()


def test_merged_playback_zoom_updates_signal_and_annotation_range(workspace, app):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    from rime_ui.presentation.annotation_editor import AnnotationEditor

    editor = AnnotationEditor(workspace)
    editor.resize(1100, 700)
    editor.show()
    QTest.qWait(200)
    editor.set_duration(20000)
    overview = editor.overview
    assert overview.parentWidget() is editor.lanes and overview.isVisible()
    assert overview.width() == editor.lanes.width() - editor.lanes._label_width
    before = deepcopy(workspace.data["annotations"])
    rect = overview._strip_rect()
    y = rect.center().y()
    start = QPoint(round(overview._time_to_x(20000, rect)) - 2, y)
    end = QPoint(round(overview._time_to_x(10000, rect)), y)
    QTest.mousePress(overview, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(overview, end)
    QTest.mouseRelease(overview, Qt.MouseButton.LeftButton, pos=end)
    QTest.qWait(50)
    view = editor.lanes.get_view_range()
    assert view == overview.get_view_range()
    assert 9900 < view[1] < 10100
    graphics = editor.signals.graphics_widget
    box = editor.signals._plots[0].getViewBox()
    for time_ms in (view[0], sum(view) / 2, view[1]):
        signal_x = graphics.mapTo(editor, QPoint()).x() + box.mapViewToScene(QPointF(time_ms / 1000, 0)).x()
        annotation_x = editor.lanes.mapTo(editor, QPoint()).x() + editor.lanes._time_to_x(time_ms)
        assert abs(signal_x - annotation_x) < 1
    QTest.mouseClick(editor.lanes._zoom_fit, Qt.MouseButton.LeftButton)
    assert editor.lanes.get_view_range() == overview.get_view_range() == (0, 20000)
    assert workspace.data["annotations"] == before
    editor.pause()
    editor.close()
    editor.deleteLater()
    app.processEvents()
