"""Native shell navigation must never display precomputed prototype state."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QFileDialog
from rime_ui.presentation.window import RimeWindow
import test_native_annotation_workspace as native

app = native.app
workspace = native.workspace


@pytest.fixture
def window(app):
    widget = RimeWindow()
    widget.show()
    yield widget
    for record in list(widget.record_windows):
        record.close()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_start_has_no_prototype_or_local_examples(window):
    assert window.pages.currentWidget() is window.start_page
    assert not hasattr(window, "annotations")
    assert not hasattr(window, "measurement_bar")
    assert not window.save_action.isEnabled()
    assert not any("preview" in a.text().lower() for a in window.menuBar().actions())


def test_cancel_record_open_preserves_native_workspace(window, workspace, tmp_path, monkeypatch):
    workspace.save(tmp_path / "workspace.json")
    assert window.open_workspace_path(workspace.path)
    editor = window.editor
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    assert window.open_document() is None
    assert window.pages.currentWidget() is editor
    window.go_home()
    assert window.annotation_action.isEnabled()
    window.annotation_action.trigger()
    assert window.pages.currentWidget() is editor
    window.save_workspace()
    assert not workspace.dirty


def test_setup_fits_content_and_restores_workspace_size(window, workspace, tmp_path, app):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea

    assert window.width() < 700
    assert window.height() < 350
    window.prepare()
    QTest.qWait(50)
    area = window.prepare_page.findChild(QScrollArea)
    assert area.verticalScrollBar().maximum() == 0
    assert window.height() < 600
    window.prepare_next()
    QTest.qWait(50)
    window.setup_pages.setCurrentIndex(0)
    QTest.qWait(50)
    assert area.verticalScrollBar().maximum() == 0
    workspace.save(tmp_path / "workspace.json")
    assert window.open_workspace_path(workspace.path)
    window.resize(1100, 700)
    QTest.qWait(50)
    window.go_home()
    QTest.qWait(50)
    assert window.width() < 700
    assert window.height() < 350
    window.navigate("annotations")
    QTest.qWait(50)
    assert window.size().width() == 1100
    assert window.size().height() == 700
