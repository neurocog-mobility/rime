from __future__ import annotations

import os
import json
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.cmf import CMFLoader
from rime_core.sessions import VideoConfig, create_session
from rime_core.workspace import WorkingContext
from rime_ui.workflows import model_workflows as model_workflows_module
from rime_ui.windows import main_window as main_window_module
from rime_ui.windows.main_window import RimeMainWindow


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_model_package(
    path: Path,
    *,
    name: str = "Demo",
    requirements: list[dict[str, str]] | None = None,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    config = {
        "cmf_version": "1.0",
        "name": name,
        "version": "0.1.0",
        "runtime": {"type": "wrapper", "entry": "wrapper.py"},
        "inputs": [{"name": "imu_window", "type": "signal", "sampling_rate_hz": 100}],
        "outputs": [{"name": "fog_probability", "type": "probability"}],
        "inference": {"mode": "whole_signal", "threshold": 0.5},
        "parameters": [],
        "output_mappings": [{"output_name": "fog_probability", "lane": "FOG", "label": "FOG"}],
        "requirements": requirements or [],
    }
    (path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (path / "labels.json").write_text(json.dumps({"events": {}}), encoding="utf-8")
    (path / "wrapper.py").write_text(
        (
            "import numpy as np\n\n"
            "class CMFModel:\n"
            "    def __init__(self, model_dir):\n"
            "        self.model_dir = model_dir\n\n"
            "    def predict(self, inputs):\n"
            "        return {'fog_probability': np.array([0.5], dtype=np.float32)}\n"
        ),
        encoding="utf-8",
    )
    return path


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


def test_register_loaded_model_warns_when_declared_requirements_are_missing(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    session = create_session(
        session_dir=tmp_path / "session",
        name="Session",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    model_dir = _write_model_package(
        session.session_dir / "models" / "demo.rime",
        requirements=[
            {
                "package": "demo-missing-package",
                "import": "demo_missing_package_for_rime_tests",
                "install_hint": "pip install demo-missing-package",
            }
        ],
    )
    package = CMFLoader.load(model_dir)

    warnings: list[str] = []
    monkeypatch.setattr(
        model_workflows_module.QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )

    window = RimeMainWindow()
    window.session = session
    window.context = SimpleNamespace(
        loaded_models={},
        register_model_package=lambda pkg: pkg,
        signals={},
        save=lambda: None,
    )
    window._refresh_model_panel = lambda: None  # type: ignore[method-assign]

    window._register_loaded_model(package)

    assert len(warnings) == 1
    assert "demo-missing-package" in warnings[0]
    assert "pip install demo-missing-package" in warnings[0]

    window.close()


def test_restore_session_models_warns_when_declared_requirements_are_missing(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    session = create_session(
        session_dir=tmp_path / "session",
        name="Session",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    model_dir = _write_model_package(
        session.session_dir / "models" / "demo.rime",
        requirements=[
            {
                "package": "demo-missing-package",
                "import": "demo_missing_package_for_rime_tests",
                "install_hint": "pip install demo-missing-package",
            }
        ],
    )
    session.model_paths = {"Demo": "models/demo.rime"}

    warnings: list[str] = []
    monkeypatch.setattr(
        model_workflows_module.QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )

    window = RimeMainWindow()
    registered: dict[str, object] = {}
    window.session = session
    window.context = SimpleNamespace(
        load_model=lambda path: CMFLoader.load(path),
        register_model_package=lambda pkg: registered.setdefault(pkg.name, pkg),
        loaded_models=registered,
        save=lambda: None,
    )

    missing = window._restore_session_models()

    assert missing == []
    assert len(warnings) == 1
    assert "Some restored models declare missing Python dependencies." in warnings[0]
    assert "demo-missing-package" in warnings[0]
    assert window._loaded_models["Demo"].path == model_dir

    window.close()
