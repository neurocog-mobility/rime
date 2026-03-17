"""Model inference over bound signal and video session inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from rime_core.annotations import Annotation, generate_id
from rime_core.cmf import CMFPackage
from rime_core.signals import Signal


@dataclass(frozen=True)
class VideoInput:
    """One video file plus an optional bounded time range."""

    path: Path
    start_ms: float = 0.0
    end_ms: float | None = None


@dataclass
class InputBinding:
    """Bind a model input name to one loaded signal or video."""

    input_name: str
    signal: Signal | None = None
    video_path: Path | None = None
    channel_map: dict[str, str] | None = None


@dataclass
class OutputMapping:
    """Map one model output to one RIME lane/label target."""

    output_name: str
    lane: str
    label: str


@dataclass
class OutputPredictions:
    """Predictions and derived annotations for one mapped output."""

    output_name: str
    lane: str
    label: str
    annotations: list[Annotation]
    raw_predictions: np.ndarray


@dataclass
class InferenceResult:
    """Output of running one CMF package against bound inputs."""

    model_name: str
    outputs: list[OutputPredictions]
    time_ms: np.ndarray
    duration_ms: float

    @property
    def annotations(self) -> list[Annotation]:
        """Flat list of all annotations across mapped outputs."""
        return [annotation for output in self.outputs for annotation in output.annotations]


class InferenceError(Exception):
    """Raised when bound inputs or mapped outputs are invalid."""


class InferenceRunner:
    """Run one CMF package against configured inputs and output mappings."""

    def __init__(
        self,
        package: CMFPackage,
        input_bindings: list[InputBinding],
        output_mappings: list[OutputMapping],
        params: dict[str, Any] | None = None,
    ) -> None:
        self.package = package
        self.input_bindings = input_bindings
        self.output_mappings = output_mappings
        self.params = dict(params or {})
        self._input_configs = {config["name"]: config for config in package.config.inputs}
        self._output_configs = {config["name"]: config for config in package.config.outputs}

    def run(
        self,
        time_range: tuple[float, float] | None = None,
    ) -> InferenceResult:
        """Execute inference for the configured bindings and mappings."""
        if not self.input_bindings:
            raise InferenceError("At least one input binding is required")
        if not self.output_mappings:
            raise InferenceError("At least one output mapping is required")

        start_ms, end_ms = self._normalized_time_range(time_range)
        self._validate_bindings()

        signal_durations = [
            binding.signal.duration_ms for binding in self.input_bindings if binding.signal is not None
        ]
        duration_ms = (
            (end_ms - start_ms)
            if end_ms is not None
            else (max(signal_durations) if signal_durations else 0.0)
        )

        if self.package.config.inference_mode == "windowed":
            time_axis, outputs_by_index = self._run_windowed_inference(
                duration_ms,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        else:
            time_axis = np.array([], dtype=np.float64)
            outputs_by_index = self._run_whole_signal_inference(
                duration_ms,
                start_ms=start_ms,
                end_ms=end_ms,
            )

        outputs = [outputs_by_index[idx] for idx in range(len(self.output_mappings))]
        result = InferenceResult(
            model_name=self.package.name,
            outputs=outputs,
            time_ms=time_axis,
            duration_ms=duration_ms,
        )
        self._offset_result_to_session_time(result, start_ms)
        return result

    def _normalized_time_range(
        self,
        time_range: tuple[float, float] | None,
    ) -> tuple[float, float | None]:
        if time_range is None:
            return 0.0, None
        start_ms, end_ms = float(time_range[0]), float(time_range[1])
        if end_ms <= start_ms:
            raise InferenceError("time_range end_ms must be greater than start_ms")
        return max(0.0, start_ms), max(0.0, end_ms)

    def _run_windowed_inference(
        self,
        duration_ms: float,
        *,
        start_ms: float,
        end_ms: float | None,
    ) -> tuple[np.ndarray, dict[int, OutputPredictions]]:
        binding_windows = {
            binding.input_name: self._extract_binding_windows(
                binding,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            for binding in self.input_bindings
        }
        time_axis = self._shared_time_axis(binding_windows)
        indexed_mappings = list(enumerate(self.output_mappings))

        if time_axis.size == 0:
            return (
                time_axis,
                {
                    idx: OutputPredictions(
                        output_name=mapping.output_name,
                        lane=mapping.lane,
                        label=mapping.label,
                        annotations=[],
                        raw_predictions=np.array([], dtype=np.float64),
                    )
                    for idx, mapping in indexed_mappings
                },
            )

        prediction_series: dict[int, list[float]] = {idx: [] for idx, _ in indexed_mappings}
        for window_idx, _window_start_ms in enumerate(time_axis):
            model_inputs = {
                input_name: binding_windows[input_name][window_idx][1]
                for input_name in binding_windows
            }
            outputs = self.package.predict(model_inputs, params=self.params)
            for mapping_idx, mapping in indexed_mappings:
                prediction_series[mapping_idx].append(self._extract_output_value(outputs, mapping))

        results: dict[int, OutputPredictions] = {}
        for mapping_idx, mapping in indexed_mappings:
            raw_predictions = np.asarray(prediction_series[mapping_idx], dtype=np.float64)
            annotations = self._predictions_to_annotations(time_axis, raw_predictions, mapping)
            results[mapping_idx] = OutputPredictions(
                output_name=mapping.output_name,
                lane=mapping.lane,
                label=mapping.label,
                annotations=annotations,
                raw_predictions=raw_predictions,
            )
        return time_axis, results

    def _run_whole_signal_inference(
        self,
        duration_ms: float,
        *,
        start_ms: float,
        end_ms: float | None,
    ) -> dict[int, OutputPredictions]:
        model_inputs = self._build_whole_signal_inputs(start_ms=start_ms, end_ms=end_ms)
        outputs = self.package.predict(model_inputs, params=self.params)

        results: dict[int, OutputPredictions] = {}
        for mapping_idx, mapping in enumerate(self.output_mappings):
            if mapping.output_name not in self._output_configs:
                raise InferenceError(f"Model has no output named '{mapping.output_name}'")
            if mapping.output_name not in outputs:
                raise InferenceError(
                    f"Model output '{mapping.output_name}' not found. Available: {sorted(outputs)}"
                )

            output_type = self._output_type(mapping.output_name)
            raw = np.asarray(outputs[mapping.output_name], dtype=np.float64)
            if output_type == "point":
                raw_predictions = raw.reshape(-1)
                if duration_ms > 0:
                    raw_predictions = raw_predictions[
                        (raw_predictions >= 0.0) & (raw_predictions <= duration_ms)
                    ]
                annotations = self._point_output_to_annotations(raw_predictions, mapping, duration_ms)
            elif output_type == "interval":
                raw_predictions = self._coerce_interval_array(raw)
                annotations = self._interval_output_to_annotations(raw_predictions, mapping, duration_ms)
            elif output_type == "probability":
                raise InferenceError(
                    f"Whole-signal inference does not support probability output '{mapping.output_name}'"
                )
            else:
                raise InferenceError(
                    f"Whole-signal inference does not support output type '{output_type}' "
                    f"for '{mapping.output_name}'"
                )

            results[mapping_idx] = OutputPredictions(
                output_name=mapping.output_name,
                lane=mapping.lane,
                label=mapping.label,
                annotations=annotations,
                raw_predictions=raw_predictions,
            )
        return results

    def _point_output_to_annotations(
        self,
        timestamps_ms: np.ndarray,
        mapping: OutputMapping,
        duration_ms: float,
    ) -> list[Annotation]:
        if duration_ms > 0:
            timestamps_ms = timestamps_ms[
                (timestamps_ms >= 0.0) & (timestamps_ms <= duration_ms)
            ]
        return [
            Annotation(
                id=generate_id(),
                lane=mapping.lane,
                label=mapping.label,
                start_ms=float(timestamp_ms),
                end_ms=float(timestamp_ms),
                event_type="point",
                source=f"model:{self.package.name}",
                ghost=True,
                confidence=1.0,
                origin_confidence=1.0,
                origin_start_ms=float(timestamp_ms),
                origin_end_ms=float(timestamp_ms),
            )
            for timestamp_ms in timestamps_ms
        ]

    def _interval_output_to_annotations(
        self,
        intervals_ms: np.ndarray,
        mapping: OutputMapping,
        duration_ms: float,
    ) -> list[Annotation]:
        annotations: list[Annotation] = []
        for start_ms, end_ms in intervals_ms:
            if duration_ms > 0:
                start_ms = max(0.0, min(float(start_ms), duration_ms))
                end_ms = max(0.0, min(float(end_ms), duration_ms))
            if end_ms < start_ms:
                start_ms, end_ms = end_ms, start_ms
            if end_ms < start_ms:
                continue
            annotations.append(
                Annotation(
                    id=generate_id(),
                    lane=mapping.lane,
                    label=mapping.label,
                    start_ms=float(start_ms),
                    end_ms=float(end_ms),
                    event_type="interval",
                    source=f"model:{self.package.name}",
                    ghost=True,
                    confidence=1.0,
                    origin_confidence=1.0,
                    origin_start_ms=float(start_ms),
                    origin_end_ms=float(end_ms),
                )
            )
        return annotations

    def _validate_bindings(self) -> None:
        declared_inputs = set(self._input_configs)
        bound_inputs = [binding.input_name for binding in self.input_bindings]
        bound_input_set = set(bound_inputs)

        missing = sorted(declared_inputs - bound_input_set)
        if missing:
            raise InferenceError(
                "Missing input bindings for declared model inputs: " + ", ".join(missing)
            )

        duplicates = sorted({name for name in bound_inputs if bound_inputs.count(name) > 1})
        if duplicates:
            raise InferenceError(
                "Duplicate input bindings provided for: " + ", ".join(duplicates)
            )

        for binding in self.input_bindings:
            if binding.input_name not in self._input_configs:
                raise InferenceError(f"Model has no input named '{binding.input_name}'")

            has_signal = binding.signal is not None
            has_video = binding.video_path is not None
            if has_signal == has_video:
                raise InferenceError(
                    f"Input binding '{binding.input_name}' must provide exactly one of "
                    "'signal' or 'video_path'"
                )

            config = self._input_configs[binding.input_name]
            input_type = str(config.get("type", "signal")).casefold()
            if input_type == "video":
                if not has_video or binding.video_path is None:
                    raise InferenceError(
                        f"Video input '{binding.input_name}' requires a video_path binding"
                    )
                if not binding.video_path.exists():
                    raise InferenceError(
                        f"Video path for input '{binding.input_name}' does not exist: {binding.video_path}"
                    )
                continue

            if input_type != "signal":
                raise InferenceError(
                    f"Input '{binding.input_name}' with type '{config.get('type')}' is not yet supported"
                )
            if binding.signal is None:
                raise InferenceError(
                    f"Signal input '{binding.input_name}' requires a signal binding"
                )

            required_channels = [str(channel) for channel in config.get("channels", [])]
            missing_channels: list[str] = []
            for model_channel in required_channels:
                signal_column = (binding.channel_map or {}).get(model_channel, model_channel)
                if signal_column not in binding.signal.channels:
                    missing_channels.append(
                        f"{model_channel}->{signal_column}"
                        if model_channel != signal_column
                        else signal_column
                    )
            if missing_channels:
                raise InferenceError(
                    f"Signal missing required channels for input '{binding.input_name}': "
                    + ", ".join(sorted(missing_channels))
                )

            expected_rate = config.get("sampling_rate_hz", config.get("sample_rate_hz"))
            if expected_rate is not None and not np.isclose(
                binding.signal.sampling_rate_hz,
                float(expected_rate),
            ):
                raise InferenceError(
                    f"Signal sampling rate {binding.signal.sampling_rate_hz}Hz does not match "
                    f"model requirement {float(expected_rate)}Hz for input '{binding.input_name}'"
                )

    def _resolve_channels(
        self,
        binding: InputBinding,
        required_channels: list[str],
    ) -> list[np.ndarray]:
        if binding.signal is None:
            raise InferenceError(f"Signal input '{binding.input_name}' requires a signal binding")
        channel_map = binding.channel_map or {}
        arrays: list[np.ndarray] = []
        for model_channel in required_channels:
            signal_column = channel_map.get(model_channel, model_channel)
            if signal_column not in binding.signal.channels:
                detail = (
                    f" (mapped from model channel '{model_channel}')"
                    if model_channel != signal_column
                    else ""
                )
                raise InferenceError(f"Channel '{signal_column}' not found in signal{detail}")
            arrays.append(binding.signal.get_channel(signal_column))
        return arrays

    def _extract_binding_windows(
        self,
        binding: InputBinding,
        *,
        start_ms: float = 0.0,
        end_ms: float | None = None,
    ) -> list[tuple[float, np.ndarray]]:
        if binding.input_name not in self._input_configs:
            raise InferenceError(f"Model has no input named '{binding.input_name}'")
        if binding.signal is None:
            raise InferenceError(f"Signal input '{binding.input_name}' requires a signal binding")

        config = self._input_configs[binding.input_name]
        input_type = str(config.get("type", "signal")).casefold()
        if input_type != "signal":
            raise InferenceError(
                f"Input '{binding.input_name}' with type '{config.get('type')}' is not yet supported"
            )

        sliced_data, sliced_time_ms = self._slice_signal(
            binding,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        window_samples = self._window_sample_count(binding.signal)
        stride_samples = self._stride_sample_count(binding.signal)
        if sliced_data.shape[0] < window_samples:
            return []

        windows: list[tuple[float, np.ndarray]] = []
        for start_idx in range(0, sliced_data.shape[0] - window_samples + 1, stride_samples):
            end_idx = start_idx + window_samples
            raw_window = sliced_data[start_idx:end_idx]
            windows.append(
                (
                    float(sliced_time_ms[start_idx]),
                    self._reshape_window(raw_window, config),
                )
            )
        return windows

    def _shared_time_axis(
        self,
        binding_windows: dict[str, list[tuple[float, np.ndarray]]],
    ) -> np.ndarray:
        sequences = list(binding_windows.values())
        if not sequences or not sequences[0]:
            return np.array([], dtype=np.float64)

        reference = np.asarray([start_ms for start_ms, _ in sequences[0]], dtype=np.float64)
        for windows in sequences[1:]:
            candidate = np.asarray([start_ms for start_ms, _ in windows], dtype=np.float64)
            if reference.shape != candidate.shape or not np.allclose(reference, candidate):
                raise InferenceError("Bound inputs do not share the same window timeline")
        return reference

    def _build_whole_signal_inputs(
        self,
        *,
        start_ms: float,
        end_ms: float | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for binding in self.input_bindings:
            config = self._input_configs[binding.input_name]
            input_type = str(config.get("type", "signal")).casefold()
            if input_type == "video":
                if binding.video_path is None:
                    raise InferenceError(
                        f"Video input '{binding.input_name}' requires a video_path binding"
                    )
                result[binding.input_name] = VideoInput(
                    path=binding.video_path,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            else:
                sliced_data, _ = self._slice_signal(binding, start_ms=start_ms, end_ms=end_ms)
                result[binding.input_name] = sliced_data
        return result

    def _slice_signal(
        self,
        binding: InputBinding,
        *,
        start_ms: float,
        end_ms: float | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        if binding.signal is None:
            raise InferenceError(f"Signal input '{binding.input_name}' requires a signal binding")

        config = self._input_configs[binding.input_name]
        required_channels = [str(channel) for channel in config.get("channels", [])]
        resolved = self._resolve_channels(binding, required_channels)
        time_ms = binding.signal.get_time_ms()
        start_idx = int(np.searchsorted(time_ms, start_ms, side="left"))
        end_idx = (
            int(np.searchsorted(time_ms, end_ms, side="right"))
            if end_ms is not None
            else binding.signal.num_samples
        )
        end_idx = max(start_idx, min(end_idx, binding.signal.num_samples))

        if end_idx <= start_idx:
            return (
                np.zeros((0, len(required_channels)), dtype=np.float32),
                np.zeros(0, dtype=np.float64),
            )

        data = np.column_stack([channel[start_idx:end_idx] for channel in resolved]).astype(
            np.float32,
            copy=False,
        )
        local_time_ms = time_ms[start_idx:end_idx].astype(np.float64, copy=False) - float(start_ms)
        return data, local_time_ms

    def _reshape_window(self, raw_window: np.ndarray, input_config: dict[str, Any]) -> np.ndarray:
        expected_shape = input_config.get("shape")
        if not expected_shape:
            return raw_window[np.newaxis, :, :]
        if not isinstance(expected_shape, list) or not all(isinstance(item, int) for item in expected_shape):
            raise InferenceError("Model input shape must be a list of integers")
        if int(np.prod(expected_shape)) != int(raw_window.size):
            raise InferenceError(
                f"Window data shape {raw_window.shape} cannot be reshaped to model input "
                f"shape {tuple(expected_shape)}"
            )
        return raw_window.reshape(tuple(expected_shape))

    def _extract_output_value(
        self,
        outputs: dict[str, np.ndarray],
        mapping: OutputMapping,
    ) -> float:
        if mapping.output_name not in self._output_configs:
            raise InferenceError(f"Model has no output named '{mapping.output_name}'")
        if mapping.output_name not in outputs:
            raise InferenceError(
                f"Model output '{mapping.output_name}' not found. Available: {sorted(outputs)}"
            )

        config = self._output_configs[mapping.output_name]
        values = np.asarray(outputs[mapping.output_name]).squeeze()
        flat = values.reshape(-1) if values.ndim > 0 else np.array([float(values)])
        labels = [str(label) for label in config.get("labels", [])]
        output_type = str(config.get("type", "")).casefold()

        if output_type == "probability":
            if flat.size == 1:
                return float(flat[0])
            return float(flat[self._target_index(labels, mapping.label, flat.size)])

        target_index = self._target_index(labels, mapping.label, max(len(labels), flat.size))
        if flat.size == 1:
            predicted_index = int(flat[0])
        else:
            predicted_index = int(np.argmax(flat))
        return 1.0 if predicted_index == target_index else 0.0

    def _predictions_to_annotations(
        self,
        times_ms: np.ndarray,
        probs: np.ndarray,
        mapping: OutputMapping,
    ) -> list[Annotation]:
        if times_ms.size == 0 or probs.size == 0:
            return []

        binary = probs >= self.package.config.threshold
        spans: list[list[int]] = []
        start_idx: int | None = None

        for idx, is_positive in enumerate(binary):
            if is_positive and start_idx is None:
                start_idx = idx
            elif not is_positive and start_idx is not None:
                spans.append([start_idx, idx])
                start_idx = None
        if start_idx is not None:
            spans.append([start_idx, len(binary)])

        if not spans:
            return []

        annotations: list[Annotation] = []
        for span_start_idx, span_end_idx in self._merge_spans(times_ms, spans):
            confidence = (
                float(np.mean(probs[span_start_idx:span_end_idx]))
                if self._output_is_probability(mapping.output_name)
                else 1.0
            )
            annotations.append(
                Annotation(
                    id=generate_id(),
                    lane=mapping.lane,
                    label=mapping.label,
                    start_ms=float(times_ms[span_start_idx]),
                    end_ms=float(times_ms[span_end_idx - 1] + (self.package.config.window_size_ms or 0)),
                    source=f"model:{self.package.name}",
                    ghost=True,
                    confidence=confidence,
                    origin_confidence=confidence,
                    origin_start_ms=float(times_ms[span_start_idx]),
                    origin_end_ms=float(
                        times_ms[span_end_idx - 1] + (self.package.config.window_size_ms or 0)
                    ),
                )
            )
        return annotations

    def _merge_spans(self, times_ms: np.ndarray, spans: list[list[int]]) -> list[tuple[int, int]]:
        merged: list[tuple[int, int]] = []
        current_start, current_end = spans[0]
        for next_start, next_end in spans[1:]:
            stride_ms = float(self.package.config.stride_ms or 0)
            gap_ms = float(times_ms[next_start] - times_ms[current_end - 1])
            if gap_ms < stride_ms:
                current_end = next_end
                continue
            merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end
        merged.append((current_start, current_end))
        return merged

    def _offset_result_to_session_time(self, result: InferenceResult, start_ms: float) -> None:
        if not start_ms:
            return
        for annotation in result.annotations:
            annotation.start_ms += start_ms
            annotation.end_ms += start_ms
            if annotation.origin_start_ms is not None:
                annotation.origin_start_ms += start_ms
            if annotation.origin_end_ms is not None:
                annotation.origin_end_ms += start_ms
        if result.time_ms.size:
            result.time_ms = result.time_ms + start_ms

    def _output_is_probability(self, output_name: str) -> bool:
        return self._output_type(output_name) == "probability"

    def _output_type(self, output_name: str) -> str:
        return str(self._output_configs.get(output_name, {}).get("type", "")).casefold()

    def _window_sample_count(self, signal: Signal) -> int:
        if self.package.config.window_size_ms is None:
            raise InferenceError("Model window_size_ms is required for windowed inference")
        return int(round(self.package.config.window_size_ms * signal.sampling_rate_hz / 1000.0))

    def _stride_sample_count(self, signal: Signal) -> int:
        if self.package.config.stride_ms is None:
            raise InferenceError("Model stride_ms is required for windowed inference")
        return int(round(self.package.config.stride_ms * signal.sampling_rate_hz / 1000.0))

    def _coerce_interval_array(self, values: np.ndarray) -> np.ndarray:
        if values.size == 0:
            return np.zeros((0, 2), dtype=np.float64)
        if values.ndim == 1 and values.size == 2:
            return values.reshape(1, 2).astype(np.float64, copy=False)
        if values.ndim != 2 or values.shape[1] != 2:
            raise InferenceError("Whole-signal interval outputs must have shape (N, 2)")
        return values.astype(np.float64, copy=False)

    @staticmethod
    def _target_index(labels: list[str], target_label: str, size: int) -> int:
        lowered = [label.casefold() for label in labels]
        target = target_label.casefold()
        if target in lowered:
            return lowered.index(target)
        if size >= 2:
            return size - 1
        return 0
