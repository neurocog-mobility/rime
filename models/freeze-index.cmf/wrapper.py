"""CMF wrapper for the manuscript's three-second Welch Freeze Index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import welch


def compute_window_fi(window: np.ndarray, *, sampling_rate_hz: float) -> float:
    """Return the E2 log band-power ratio for one complete signal window."""
    proxy = np.asarray(window, dtype=np.float64).reshape(-1)
    if proxy.size < 2:
        raise ValueError("Freeze Index input must contain at least two samples")

    frequencies, psd = welch(
        proxy,
        fs=float(sampling_rate_hz),
        nperseg=min(256, proxy.size),
    )
    freeze = (frequencies >= 3.0) & (frequencies <= 8.0)
    locomotor = (frequencies >= 0.5) & (frequencies < 3.0)
    if freeze.sum() < 2 or locomotor.sum() < 2:
        raise ValueError("Sampling rate is insufficient for the declared FI bands")

    freeze_power = float(np.trapezoid(psd[freeze], frequencies[freeze]))
    locomotor_power = float(np.trapezoid(psd[locomotor], frequencies[locomotor]))
    return float(
        np.log10((freeze_power + 1e-12) / (locomotor_power + 1e-12))
    )


def logistic_probability(feature: float, *, coefficient: float, intercept: float) -> float:
    """Apply the stored one-feature logistic classifier without overflow."""
    logit = float(intercept + coefficient * feature)
    if logit >= 0.0:
        return float(1.0 / (1.0 + np.exp(-logit)))
    exp_logit = float(np.exp(logit))
    return float(exp_logit / (1.0 + exp_logit))


class CMFModel:
    def __init__(self, model_dir: str) -> None:
        root = Path(model_dir)
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        classifier = json.loads((root / "classifier.json").read_text(encoding="utf-8"))
        self._sampling_rate_hz = float(config["inputs"][0]["sampling_rate_hz"])
        self._coefficient = float(classifier["coefficient"])
        self._intercept = float(classifier["intercept"])

    def predict(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, np.ndarray]:
        del params
        feature = compute_window_fi(
            inputs["accel_window"],
            sampling_rate_hz=self._sampling_rate_hz,
        )
        probability = logistic_probability(
            feature,
            coefficient=self._coefficient,
            intercept=self._intercept,
        )
        return {"fog_probability": np.asarray([probability], dtype=np.float32)}
