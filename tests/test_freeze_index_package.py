from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from rime_core.cmf import CMFLoader


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/freeze-index.cmf"


def test_welch_freeze_index_package_declares_complete_operator() -> None:
    package = CMFLoader.load(MODEL_PATH)

    assert package.name == "Welch Freeze Index exemplar"
    assert package.config.version == "3.0.0"
    assert package.config.window_size_ms == 3_000
    assert package.config.stride_ms == 500
    assert package.config.threshold == pytest.approx(0.5)
    assert package.config.merge_gap_ms == 0
    assert package.config.min_duration_ms == 0
    assert [item.package for item in package.config.requirements] == ["numpy", "scipy"]

    classifier = json.loads((MODEL_PATH / "classifier.json").read_text(encoding="utf-8"))
    assert classifier["calibration"]["status"] == "fitted"
    assert classifier["calibration"]["n_trials"] == 49
    assert package.config.threshold == pytest.approx(
        classifier["calibration"]["decision_rule"]["threshold"]
    )
    assert np.isfinite(classifier["coefficient"])
    assert np.isfinite(classifier["intercept"])


def test_welch_freeze_index_integrity_manifest_matches_runtime_package() -> None:
    entries = (MODEL_PATH / "SHA256SUMS").read_text(encoding="utf-8").splitlines()

    assert entries
    for entry in entries:
        expected, filename = entry.split(maxsplit=1)
        actual = hashlib.sha256((MODEL_PATH / filename).read_bytes()).hexdigest()
        assert actual == expected


def test_welch_freeze_index_wrapper_returns_probability() -> None:
    package = CMFLoader.load(MODEL_PATH)
    sampling_rate_hz = package.config.inputs[0]["sampling_rate_hz"]
    sample_count = round(package.config.window_size_ms * sampling_rate_hz / 1_000)
    time = np.arange(sample_count, dtype=np.float64) / sampling_rate_hz
    signal = np.sin(2 * np.pi * 1.5 * time) + 0.25 * np.sin(2 * np.pi * 5.0 * time)

    output = package.predict({"accel_window": signal})["fog_probability"]

    assert output.shape == (1,)
    assert output.dtype == np.float32
    assert 0.0 <= float(output[0]) <= 1.0


def test_welch_fi_orders_freeze_band_above_locomotor() -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    wrapper_path = MODEL_PATH / "wrapper.py"
    spec = spec_from_file_location("freeze_index_wrapper_test", wrapper_path)
    assert spec is not None and spec.loader is not None
    wrapper = module_from_spec(spec)
    spec.loader.exec_module(wrapper)

    sampling_rate_hz = 128.0
    time = np.arange(384, dtype=np.float64) / sampling_rate_hz
    locomotor = np.sin(2 * np.pi * 1.5 * time)
    freezing = np.sin(2 * np.pi * 5.0 * time)
    arguments = {"sampling_rate_hz": sampling_rate_hz}

    assert wrapper.compute_window_fi(freezing, **arguments) > wrapper.compute_window_fi(
        locomotor, **arguments
    )
