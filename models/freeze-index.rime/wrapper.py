"""Freeze Index CMF wrapper based on Moore et al. (2008)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import scipy.signal


class CMFModel:
    def __init__(self, model_dir: str) -> None:
        with open(Path(model_dir) / "config.json", "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        param_defaults = {param["name"]: param["default"] for param in cfg.get("parameters", [])}
        self._fi_centre = float(param_defaults.get("fi_centre", 2.0))
        self._fi_scale = float(param_defaults.get("fi_scale", 1.0))
        self._fs = float(cfg["inputs"][0].get("sampling_rate_hz", 128))

    def predict(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, np.ndarray]:
        params = params or {}
        fi_centre = float(params.get("fi_centre", self._fi_centre))
        fi_scale = float(params.get("fi_scale", self._fi_scale))

        window = np.asarray(inputs["accel_window"], dtype=np.float64).reshape(-1)
        freqs, psd = scipy.signal.welch(window, fs=self._fs, nperseg=min(256, len(window)))

        freeze_mask = (freqs >= 3.0) & (freqs <= 8.0)
        locomotor_mask = (freqs >= 0.5) & (freqs < 3.0)
        freeze_area = float(np.trapezoid(psd[freeze_mask], freqs[freeze_mask]))
        locomotor_area = float(np.trapezoid(psd[locomotor_mask], freqs[locomotor_mask]))
        freeze_index = (freeze_area ** 2) / (locomotor_area ** 2 + 1e-10)
        probability = 1.0 / (1.0 + np.exp(-fi_scale * (freeze_index - fi_centre)))

        return {"fog_probability": np.array([probability], dtype=np.float32)}
