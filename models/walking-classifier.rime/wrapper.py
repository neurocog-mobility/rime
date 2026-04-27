"""Wrapper for the demo ONNX walking classifier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


class CMFModel:
    def __init__(self, model_dir: str) -> None:
        self._model_dir = Path(model_dir)
        with open(self._model_dir / "config.json", "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        self._defaults = {
            param["name"]: param.get("default")
            for param in cfg.get("parameters", [])
            if isinstance(param, dict) and isinstance(param.get("name"), str)
        }
        self._onnx_path = self._model_dir / "model.onnx"
        self._session: Any | None = None

    def predict(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, np.ndarray]:
        merged_params = dict(self._defaults)
        if params:
            merged_params.update(params)

        left = self._prepare_ankle_input(inputs["left_ankle"], merged_params)
        right = self._prepare_ankle_input(inputs["right_ankle"], merged_params)
        outputs = self._get_session().run(
            ["walking_probability"],
            {
                "left_dynamic_magnitude": left,
                "right_dynamic_magnitude": right,
            },
        )
        return {"walking_probability": np.asarray(outputs[0], dtype=np.float32).reshape(-1)}

    def _get_session(self) -> Any:
        if self._session is not None:
            return self._session
        if not self._onnx_path.exists():
            raise FileNotFoundError(
                f"Demo walking classifier ONNX weights not found: {self._onnx_path}"
            )
        try:
            import onnxruntime  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is required to run demo-walking-classifier.rime"
            ) from exc
        self._session = onnxruntime.InferenceSession(str(self._onnx_path))
        return self._session

    def _prepare_ankle_input(
        self,
        raw_input: Any,
        params: dict[str, Any],
    ) -> np.ndarray:
        data = np.asarray(raw_input, dtype=np.float32)
        if data.ndim == 2:
            data = data[np.newaxis, :, :]
        if data.ndim != 3 or data.shape[-1] != 3:
            raise ValueError(
                f"Ankle input must have shape (batch, time, 3) or (time, 3); got {data.shape}"
            )

        if self._as_bool(params.get("scale_to_g", True)):
            data = data / np.float32(9.81)

        filled = self._interpolate_nans(data)
        magnitude = np.sqrt(np.sum(filled**2, axis=2, keepdims=True))
        baseline = np.median(magnitude, axis=1, keepdims=True)
        dynamic_magnitude = magnitude - baseline
        return dynamic_magnitude.astype(np.float32, copy=False)

    @staticmethod
    def _interpolate_nans(data: np.ndarray) -> np.ndarray:
        filled = np.array(data, dtype=np.float32, copy=True)
        sample_index = np.arange(filled.shape[1], dtype=np.float32)
        for batch_idx in range(filled.shape[0]):
            for channel_idx in range(filled.shape[2]):
                values = filled[batch_idx, :, channel_idx]
                mask = np.isfinite(values)
                if mask.all():
                    continue
                if not mask.any():
                    filled[batch_idx, :, channel_idx] = 0.0
                    continue
                filled[batch_idx, :, channel_idx] = np.interp(
                    sample_index,
                    sample_index[mask],
                    values[mask],
                ).astype(np.float32)
        return filled

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return False
