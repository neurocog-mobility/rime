from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.context import WorkingContext
from rime_core.session import VideoConfig, create_session
from rime_ui import main_window as main_window_module
from rime_ui.main_window import RimeMainWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_restore_session_models_loads_saved_package_paths(tmp_path: Path) -> None:
    _app()
    session = create_session(
        session_dir=tmp_path / "session",
        name="Session",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    model_dir = session.session_dir / "models" / "demo.rime"
    model_dir.mkdir(parents=True)
    session.model_paths = {"Demo": "models/demo.rime"}

    window = RimeMainWindow()
    loaded_paths: list[Path] = []
    registered: dict[str, object] = {}
    package = SimpleNamespace(name="Demo", path=model_dir, config=SimpleNamespace(inputs=[]))

    def register_model_package(pkg: object) -> object:
        registered[package.name] = pkg
        return pkg

    window.session = session
    window.context = SimpleNamespace(
        load_model=lambda path: loaded_paths.append(Path(path)) or package,
        register_model_package=register_model_package,
        loaded_models=registered,
        save=lambda: None,
    )

    missing = window._restore_session_models()

    assert missing == []
    assert loaded_paths == [model_dir]
    assert window._loaded_models == {"Demo": package}
    assert window._active_model_name == "Demo"

    window.close()


def test_loading_context_warns_and_prunes_missing_saved_models(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    ctx = WorkingContext.create(
        session_dir=tmp_path / "session",
        name="Session",
        videos=[],
    )
    ctx.session.model_paths = {"Missing Demo": "models/missing.rime"}
    ctx.save()

    warnings: list[str] = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )

    window = RimeMainWindow()
    window._load_context(ctx)

    assert ctx.session.model_paths == {}
    assert len(warnings) == 1
    assert "Missing Demo" in warnings[0]

    window.close()


def test_register_and_unload_model_update_session_store(tmp_path: Path) -> None:
    _app()
    session = create_session(
        session_dir=tmp_path / "session",
        name="Session",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    model_dir = session.session_dir / "models" / "demo.rime"
    model_dir.mkdir(parents=True)

    saved_snapshots: list[dict[str, str]] = []
    unloaded: list[str] = []
    loaded_models: dict[str, object] = {}
    package = SimpleNamespace(name="Demo", path=model_dir, config=SimpleNamespace(inputs=[]))

    def register_model_package(pkg: object) -> object:
        loaded_models[package.name] = pkg
        return pkg

    window = RimeMainWindow()
    window.session = session
    window.context = SimpleNamespace(
        loaded_models=loaded_models,
        register_model_package=register_model_package,
        unload_model=lambda model_name: unloaded.append(model_name),
        signals={},
        save=lambda: saved_snapshots.append(dict(session.model_paths)),
    )
    window._refresh_model_panel = lambda: None  # type: ignore[method-assign]

    window._register_loaded_model(package)
    assert session.model_paths == {"Demo": "models/demo.rime"}

    window._on_unload_model("Demo")

    assert session.model_paths == {}
    assert unloaded == ["Demo"]
    assert saved_snapshots == [{"Demo": "models/demo.rime"}, {}]

    window.close()
