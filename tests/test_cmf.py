from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from rime_core.cmf import CMFLoader, CMFValidationError


def _write_wrapper_package(path: Path, *, name: str = "DemoModel", include_version: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    config = {
        "cmf_version": "1.0",
        "name": name,
        "description": "Demo model description",
        "license": "MIT",
        "runtime": {
            "type": "wrapper",
            "entry": "wrapper.py",
        },
        "inputs": [
            {
                "name": "imu_window",
                "type": "signal",
                "channels": ["acc_x", "acc_y"],
                "sampling_rate_hz": 100,
                "shape": [1, 600, 2],
            }
        ],
        "outputs": [
            {
                "name": "fog_probability",
                "type": "probability",
                "labels": ["no_fog", "fog"],
                "shape": [1],
            }
        ],
        "inference": {
            "mode": "windowed",
            "window_size_ms": 6000,
            "stride_ms": 500,
            "threshold": 0.5,
        },
        "output_mappings": [
            {"output_name": "fog_probability", "lane": "FOG", "label": "FOG"}
        ],
    }
    if include_version:
        config["version"] = "0.1.0"

    (path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (path / "labels.json").write_text(
        json.dumps({"events": {"FOG": {"description": "Freezing of gait"}}}),
        encoding="utf-8",
    )
    (path / "wrapper.py").write_text(
        (
            "import numpy as np\n\n"
            "class CMFModel:\n"
            "    def __init__(self, model_dir):\n"
            "        self.model_dir = model_dir\n\n"
            "    def predict(self, inputs):\n"
            "        return {'fog_probability': np.array([0.75], dtype=np.float32)}\n"
        ),
        encoding="utf-8",
    )
    return path


def _write_point_wrapper_package(path: Path, *, name: str = "PointDemo") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    config = {
        "cmf_version": "1.0",
        "name": name,
        "version": "0.1.0",
        "runtime": {
            "type": "wrapper",
            "entry": "wrapper.py",
        },
        "inputs": [
            {
                "name": "trunk_accel",
                "type": "signal",
                "channels": ["acc_x", "acc_y"],
                "sampling_rate_hz": 100,
            }
        ],
        "outputs": [
            {
                "name": "step_times",
                "type": "point",
                "description": "Foot contact timestamps in ms",
            }
        ],
        "inference": {
            "mode": "whole_signal",
            "threshold": 0.5,
        },
        "parameters": [],
        "output_mappings": [
            {"output_name": "step_times", "lane": "Steps", "label": "step"}
        ],
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
            "        return {'step_times': np.array([100.0, 250.0], dtype=np.float32)}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_load_wrapper_package_directory(tmp_path: Path) -> None:
    package_dir = _write_wrapper_package(tmp_path / "demo-model.rime")

    package = CMFLoader.load(package_dir)
    output = package.predict({"imu_window": np.zeros((1, 600, 2), dtype=np.float32)})

    assert package.name == "DemoModel"
    assert package.config.labels["events"]["FOG"]["description"] == "Freezing of gait"
    assert package.config.runtime_type == "wrapper"
    assert package.config.runtime_entry == "wrapper.py"
    assert package.config.inference_mode == "windowed"
    assert package.config.description == "Demo model description"
    assert package.config.license == "MIT"
    assert package.config.parameters == []
    assert package.config.output_mappings == [
        {"output_name": "fog_probability", "lane": "FOG", "label": "FOG"}
    ]
    assert np.isclose(output["fog_probability"][0], 0.75)


def test_load_zip_package(tmp_path: Path) -> None:
    source_dir = _write_wrapper_package(tmp_path / "zip-source")
    zip_path = tmp_path / "demo-model.rime"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for child in source_dir.iterdir():
            archive.write(child, arcname=f"{source_dir.name}/{child.name}")

    package = CMFLoader.load(zip_path)

    assert package.path == zip_path
    assert package.config.name == "DemoModel"
    assert package.predict({"imu_window": np.zeros((1, 600, 2), dtype=np.float32)})


def test_scan_skips_invalid_packages(tmp_path: Path) -> None:
    valid_dir = _write_wrapper_package(tmp_path / "valid-model.rime", name="ValidModel")
    _write_wrapper_package(tmp_path / "invalid-model.rime", include_version=False)
    (tmp_path / "README.txt").write_text("ignore me", encoding="utf-8")

    packages = CMFLoader.scan(tmp_path)

    assert [package.path for package in packages] == [valid_dir]
    assert packages[0].config.name == "ValidModel"


def test_missing_required_fields_raise_validation_error(tmp_path: Path) -> None:
    package_dir = _write_wrapper_package(tmp_path / "broken-model.rime", include_version=False)

    with pytest.raises(CMFValidationError, match="version"):
        CMFLoader.load(package_dir)


def test_missing_output_mappings_defaults_to_empty_list(tmp_path: Path) -> None:
    package_dir = _write_wrapper_package(tmp_path / "no-mappings.rime")
    config = json.loads((package_dir / "config.json").read_text(encoding="utf-8"))
    config.pop("output_mappings")
    (package_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    package = CMFLoader.load(package_dir)

    assert package.config.output_mappings == []


def test_malformed_output_mappings_raise_validation_error(tmp_path: Path) -> None:
    package_dir = _write_wrapper_package(tmp_path / "bad-mappings.rime")
    config = json.loads((package_dir / "config.json").read_text(encoding="utf-8"))
    config["output_mappings"] = [{"output_name": "fog_probability", "lane": "FOG"}]
    (package_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(CMFValidationError, match="output_mappings"):
        CMFLoader.load(package_dir)


def test_load_point_wrapper_package_without_windowing(tmp_path: Path) -> None:
    package_dir = _write_point_wrapper_package(tmp_path / "point-model.rime")

    package = CMFLoader.load(package_dir)
    output = package.predict({"trunk_accel": np.zeros((8, 2), dtype=np.float32)})

    assert package.config.window_size_ms is None
    assert package.config.stride_ms is None
    assert package.config.inference_mode == "whole_signal"
    assert np.allclose(output["step_times"], np.array([100.0, 250.0], dtype=np.float32))


def test_onnx_runtime_is_rejected(tmp_path: Path) -> None:
    package_dir = _write_wrapper_package(tmp_path / "onnx-model.rime")
    config = json.loads((package_dir / "config.json").read_text(encoding="utf-8"))
    config["runtime"] = {"type": "onnx", "entry": "model.onnx"}
    (package_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (package_dir / "model.onnx").write_bytes(b"placeholder")

    with pytest.raises(CMFValidationError, match="only 'wrapper' is supported"):
        CMFLoader.load(package_dir)
