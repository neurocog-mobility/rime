from __future__ import annotations

import pytest

from rime_ui import app as app_module


def test_parse_args_requires_open_when_compare_is_used() -> None:
    with pytest.raises(SystemExit):
        app_module._parse_args(["--compare", "session2/session.json"])


def test_main_opens_session_then_comparison_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeApp:
        def __init__(self, argv):
            self.argv = argv

        def setApplicationName(self, name: str) -> None:
            pass

        def setApplicationDisplayName(self, name: str) -> None:
            pass

        def setOrganizationName(self, name: str) -> None:
            pass

        def exec(self) -> int:
            return 0

    class FakeWindow:
        def show(self) -> None:
            calls.append(("show", ""))

        def open_session_path(self, path: str) -> bool:
            calls.append(("open", path))
            return True

        def load_comparison_path(self, path: str) -> bool:
            calls.append(("compare", path))
            return True

        def load_model_path(self, path: str) -> bool:
            calls.append(("model", path))
            return True

    monkeypatch.setattr(app_module, "QApplication", FakeApp)
    monkeypatch.setattr(app_module, "RimeMainWindow", FakeWindow)

    code = app_module.main(
        [
            "--open",
            "sample-data/test/session.json",
            "--compare",
            "sample-data/test2/session.json",
            "--model",
            "demo.rime",
        ]
    )

    assert code == 0
    assert calls == [
        ("show", ""),
        ("open", "sample-data/test/session.json"),
        ("compare", "sample-data/test2/session.json"),
        ("model", "demo.rime"),
    ]
