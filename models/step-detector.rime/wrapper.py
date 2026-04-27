"""Step detector CMF wrapper using adaptive peak detection on ankle acceleration."""

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
        self._fs = float(cfg["inputs"][0].get("sampling_rate_hz", 128))
        param_defaults = {param["name"]: param["default"] for param in cfg.get("parameters", [])}
        self._min_step_interval_ms = int(param_defaults.get("min_step_interval_ms", 300))
        self._threshold_multiplier = float(param_defaults.get("threshold_multiplier", 1.0))

    def predict(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, np.ndarray]:
        params = params or {}
        min_interval_ms = int(params.get("min_step_interval_ms", self._min_step_interval_ms))
        threshold_multiplier = float(
            params.get("threshold_multiplier", self._threshold_multiplier)
        )

        accel = np.asarray(inputs["ankle_accel"], dtype=np.float64)
        if accel.ndim == 1:
            vector_magnitude = np.abs(accel)
        else:
            vector_magnitude = np.sqrt((accel**2).sum(axis=1))

        sg_window = max(5, int(round(self._fs * 0.1)) | 1)
        if sg_window >= len(vector_magnitude):
            sg_window = max(3, len(vector_magnitude) - (1 - len(vector_magnitude) % 2))
        if sg_window < 3:
            return {"step_times": np.array([], dtype=np.float64)}

        filtered = scipy.signal.savgol_filter(vector_magnitude, window_length=sg_window, polyorder=3)
        filtered = filtered - np.median(filtered)

        window_samples = max(3, int(round(self._fs * 2.0)))
        half = window_samples // 2
        padded = np.pad(filtered, (half, window_samples - half - 1), mode="edge")
        cumulative = np.cumsum(np.insert(padded, 0, 0.0))
        cumulative_sq = np.cumsum(np.insert(padded**2, 0, 0.0))
        mean = (cumulative[window_samples:] - cumulative[:-window_samples]) / window_samples
        sq_mean = (cumulative_sq[window_samples:] - cumulative_sq[:-window_samples]) / window_samples
        rolling_std = np.sqrt(np.maximum(sq_mean - mean**2, 0.0))
        adaptive_height = threshold_multiplier * rolling_std

        min_distance_samples = max(1, int(round(min_interval_ms * self._fs / 1000.0)))
        peaks, _ = scipy.signal.find_peaks(
            filtered,
            height=adaptive_height,
            distance=min_distance_samples,
            prominence=0.2,
        )

        step_times_ms = peaks / self._fs * 1000.0
        return {"step_times": step_times_ms.astype(np.float64)}
