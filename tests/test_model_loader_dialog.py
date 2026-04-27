from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QLabel, QTableWidget

from rime_core.cmf import CMFLoader
from rime_ui.dialogs.model_loader_dialog import ModelLoaderDialog

from test_cmf import _write_wrapper_package


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_choose_loaded_package_returns_confirmed_package(tmp_path: Path) -> None:
    _app()
    package_dir = _write_wrapper_package(tmp_path / "demo-model.rime")

    original_directory = QtWidgets.QFileDialog.getExistingDirectory
    original_exec = ModelLoaderDialog.exec

    QtWidgets.QFileDialog.getExistingDirectory = staticmethod(
        lambda *args, **kwargs: str(package_dir)
    )

    observed: dict[str, str] = {}

    def _fake_exec(self: ModelLoaderDialog) -> int:
        observed["name"] = self.package.config.name
        observed["description"] = self.package.config.description
        return ModelLoaderDialog.DialogCode.Accepted

    ModelLoaderDialog.exec = _fake_exec
    try:
        package = ModelLoaderDialog.choose_loaded_package()
    finally:
        QtWidgets.QFileDialog.getExistingDirectory = original_directory
        ModelLoaderDialog.exec = original_exec

    assert package is not None
    assert package.config.name == "DemoModel"
    assert observed == {
        "name": "DemoModel",
        "description": "Demo model description",
    }


def test_model_loader_dialog_uses_tabs_and_empty_placeholders(tmp_path: Path) -> None:
    _app()
    package_dir = _write_wrapper_package(tmp_path / "empty-model.rime")
    package = CMFLoader.load(package_dir)
    package.config.inputs = []
    package.config.outputs = []
    package.config.output_mappings = []
    package.config.parameters = []

    dialog = ModelLoaderDialog(package)

    assert dialog.minimumWidth() == 640
    assert dialog.minimumHeight() == 480
    assert dialog.tabs.count() == 5
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == [
        "Inputs",
        "Outputs",
        "Mappings",
        "Parameters",
        "Requirements",
    ]
    assert dialog.load_button.isDefault() is True

    inputs_tab = dialog.tabs.widget(0)
    placeholder = inputs_tab.findChild(QLabel)
    table = inputs_tab.findChild(QTableWidget)

    assert placeholder is not None
    assert placeholder.text() == "No declared inputs"
    assert table is not None
    assert table.isHidden() is True

    dialog.close()
