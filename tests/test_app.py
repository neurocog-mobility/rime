"""Startup routes native records separately from editable workspaces."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from rime_ui import app as app_module


@pytest.mark.parametrize(
    "arguments",
    [
        ["--model", "procedure.cmf"],
        ["--compare", "workspace.json"],
        ["--preview-screen", "annotations"],
    ],
)
def test_rejects_removed_cli_options(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        app_module._parse_args(arguments)
    assert error.value.code == 2
    assert "desktop controls" in capsys.readouterr().err


def test_start_routes_to_native_shell(monkeypatch):
    calls = []

    class FakeApp:
        def __init__(self, args):
            pass

        def setApplicationName(self, name):
            pass

        def setApplicationDisplayName(self, name):
            pass

        def setOrganizationName(self, name):
            pass

        def exec(self):
            return 0

    class FakeWindow:
        def show(self):
            calls.append("show")

    monkeypatch.setattr(app_module, "QApplication", FakeApp)
    monkeypatch.setattr(app_module, "RimeWindow", FakeWindow)
    assert app_module.main([]) == 0
    assert calls == ["show"]


def test_open_routes_to_native_inspector(monkeypatch):
    from rime_ui.presentation import records

    calls = []

    class App:
        def __init__(self, args):
            pass

        def setApplicationName(self, name):
            pass

        def setApplicationDisplayName(self, name):
            pass

        def setOrganizationName(self, name):
            pass

        def exec(self):
            return 0

    class Inspector:
        def show(self):
            calls.append("show")

        def open_path(self, path):
            calls.append(path)

    monkeypatch.setattr(app_module, "QApplication", App)
    monkeypatch.setattr(records, "RecordWindow", Inspector)
    assert app_module.main(["--open", "measurement.rime"]) == 0
    assert calls == ["show", "measurement.rime"]
