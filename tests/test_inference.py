from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rime_core.cmf import CMFConfig, CMFPackage
from rime_core.inference import (
    InferenceError,
    InferenceRunner,
    InputBinding,
    OutputMapping,
)
from rime_core.signals import Signal


class SequenceRunner:
    def __init__(self, values: list[dict[str, np.ndarray]]) -> None:
        self.values = list(values)
        self.calls: list[dict[str, np.ndarray]] = []

    def predict(self, inputs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        self.calls.append(inputs)
        return self.values.pop(0)


def _make_signal(
    *,
    name: str = "synthetic",
    sample_count: int = 50,
    sampling_rate_hz: float = 10.0,
    channels: list[str] | None = None,
    offset_ms: float = 0.0,
) -> Signal:
    channel_names = channels or ["acc_x", "acc_y"]
    time = np.arange(sample_count, dtype=np.float64) / sampling_rate_hz
    data = {"time": time}
    for idx, channel in enumerate(channel_names):
        data[channel] = np.linspace(idx, idx + 1, sample_count)
    return Signal(
        name=name,
        data=pd.DataFrame(data),
        sampling_rate_hz=sampling_rate_hz,
        time_column="time",
        channels=channel_names,
        offset_ms=offset_ms,
    )


def _make_package(runner: SequenceRunner) -> CMFPackage:
    return CMFPackage(
        path=Path("dummy-model.rime"),
        config=CMFConfig(
            cmf_version="1.0",
            name="MultiModel",
            version="0.1.0",
            description="",
            license="",
            runtime_type="wrapper",
            runtime_entry="wrapper.py",
            inputs=[
                {
                    "name": "imu_window",
                    "type": "signal",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                }
            ],
            outputs=[
                {
                    "name": "fog_probability",
                    "type": "probability",
                    "shape": [1],
                    "labels": ["no_fog", "fog"],
                },
                {
                    "name": "task_probability",
                    "type": "probability",
                    "shape": [1],
                    "labels": ["no_walk", "Walk"],
                },
                {
                    "name": "phenotype",
                    "type": "classification",
                    "shape": [3],
                    "labels": ["trembling", "Akinetic", "shuffling"],
                },
            ],
            inference_mode="windowed",
            window_size_ms=1000,
            stride_ms=500,
            threshold=0.5,
            parameters=[],
            labels={"events": {"FOG": {"description": "Freezing of gait"}}},
            output_mappings=[],
        ),
        _runner=runner,
        _model_dir=Path("dummy-model"),
    )


def _make_point_package(runner: SequenceRunner) -> CMFPackage:
    return CMFPackage(
        path=Path("point-model.rime"),
        config=CMFConfig(
            cmf_version="1.0",
            name="PointModel",
            version="0.1.0",
            description="",
            license="",
            runtime_type="wrapper",
            runtime_entry="wrapper.py",
            inputs=[
                {
                    "name": "trunk_accel",
                    "type": "signal",
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                }
            ],
            outputs=[
                {
                    "name": "step_times",
                    "type": "point",
                }
            ],
            inference_mode="whole_signal",
            window_size_ms=None,
            stride_ms=None,
            threshold=0.5,
            parameters=[],
            labels={"events": {"Steps": {"description": "Step events"}}},
            output_mappings=[],
        ),
        _runner=runner,
        _model_dir=Path("dummy-model"),
    )


def test_run_produces_annotations_for_multiple_mapped_outputs() -> None:
    runner = SequenceRunner(
        [
            {
                "fog_probability": np.array([0.1], dtype=np.float32),
                "task_probability": np.array([0.8], dtype=np.float32),
                "phenotype": np.array([1, 0, 0], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.2], dtype=np.float32),
                "task_probability": np.array([0.8], dtype=np.float32),
                "phenotype": np.array([0, 1, 0], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.7], dtype=np.float32),
                "task_probability": np.array([0.8], dtype=np.float32),
                "phenotype": np.array([0, 1, 0], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.8], dtype=np.float32),
                "task_probability": np.array([0.2], dtype=np.float32),
                "phenotype": np.array([0, 0, 1], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.9], dtype=np.float32),
                "task_probability": np.array([0.1], dtype=np.float32),
                "phenotype": np.array([0, 0, 1], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.2], dtype=np.float32),
                "task_probability": np.array([0.1], dtype=np.float32),
                "phenotype": np.array([1, 0, 0], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.1], dtype=np.float32),
                "task_probability": np.array([0.1], dtype=np.float32),
                "phenotype": np.array([1, 0, 0], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.1], dtype=np.float32),
                "task_probability": np.array([0.1], dtype=np.float32),
                "phenotype": np.array([1, 0, 0], dtype=np.float32),
            },
            {
                "fog_probability": np.array([0.1], dtype=np.float32),
                "task_probability": np.array([0.1], dtype=np.float32),
                "phenotype": np.array([1, 0, 0], dtype=np.float32),
            },
        ]
    )
    package = _make_package(runner)
    signal = _make_signal()
    bindings = [InputBinding(input_name="imu_window", signal=signal)]
    mappings = [
        OutputMapping(output_name="fog_probability", lane="FOG", label="FOG"),
        OutputMapping(output_name="task_probability", lane="Tasks", label="Walk"),
        OutputMapping(output_name="phenotype", lane="Manifestations", label="Akinetic"),
    ]

    result = InferenceRunner(package, bindings, mappings).run()

    assert np.allclose(result.time_ms, np.array([0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000]))
    assert len(result.outputs) == 3
    assert runner.calls[0]["imu_window"].shape == (1, 10, 2)

    fog_output = next(output for output in result.outputs if output.output_name == "fog_probability")
    assert len(fog_output.annotations) == 1
    assert fog_output.annotations[0].lane == "FOG"
    assert fog_output.annotations[0].start_ms == 1000.0
    assert fog_output.annotations[0].end_ms == 3000.0
    assert fog_output.annotations[0].confidence == pytest.approx((0.7 + 0.8 + 0.9) / 3.0)
    assert fog_output.annotations[0].origin_confidence == pytest.approx((0.7 + 0.8 + 0.9) / 3.0)
    assert fog_output.annotations[0].origin_start_ms == 1000.0
    assert fog_output.annotations[0].origin_end_ms == 3000.0

    task_output = next(output for output in result.outputs if output.output_name == "task_probability")
    assert len(task_output.annotations) == 1
    assert task_output.annotations[0].lane == "Tasks"
    assert task_output.annotations[0].label == "Walk"
    assert task_output.annotations[0].start_ms == 0.0
    assert task_output.annotations[0].end_ms == 2000.0

    phenotype_output = next(output for output in result.outputs if output.output_name == "phenotype")
    assert len(phenotype_output.annotations) == 1
    assert phenotype_output.annotations[0].lane == "Manifestations"
    assert phenotype_output.annotations[0].label == "Akinetic"
    assert phenotype_output.annotations[0].confidence == 1.0


def test_short_signal_produces_empty_outputs() -> None:
    runner = SequenceRunner([])
    package = _make_package(runner)
    signal = _make_signal(sample_count=8)

    result = InferenceRunner(
        package,
        [InputBinding(input_name="imu_window", signal=signal)],
        [OutputMapping(output_name="fog_probability", lane="FOG", label="FOG")],
    ).run()

    assert result.time_ms.size == 0
    assert result.outputs[0].raw_predictions.size == 0
    assert result.annotations == []


def test_unknown_output_mapping_raises_error() -> None:
    runner = SequenceRunner([{"fog_probability": np.array([0.1], dtype=np.float32)}] * 9)
    package = _make_package(runner)
    signal = _make_signal()

    with pytest.raises(InferenceError, match="no output named"):
        InferenceRunner(
            package,
            [InputBinding(input_name="imu_window", signal=signal)],
            [OutputMapping(output_name="missing_output", lane="FOG", label="FOG")],
        ).run()


def test_missing_input_binding_raises_error() -> None:
    runner = SequenceRunner([{"fog_probability": np.array([0.1], dtype=np.float32)}] * 9)
    package = CMFPackage(
        path=Path("dummy-model.rime"),
        config=CMFConfig(
            cmf_version="1.0",
            name="TwoInputs",
            version="0.1.0",
            description="",
            license="",
            runtime_type="wrapper",
            runtime_entry="wrapper.py",
            inputs=[
                {
                    "name": "imu_window",
                    "type": "signal",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                },
                {
                    "name": "imu_window_2",
                    "type": "signal",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                },
            ],
            outputs=[
                {
                    "name": "fog_probability",
                    "type": "probability",
                    "shape": [1],
                    "labels": ["no_fog", "fog"],
                }
            ],
            inference_mode="windowed",
            window_size_ms=1000,
            stride_ms=500,
            threshold=0.5,
            parameters=[],
            labels={"events": {"FOG": {"description": "Freezing of gait"}}},
            output_mappings=[],
        ),
        _runner=runner,
        _model_dir=Path("dummy-model"),
    )
    signal = _make_signal()

    with pytest.raises(InferenceError, match="imu_window_2"):
        InferenceRunner(
            package,
            [InputBinding(input_name="imu_window", signal=signal)],
            [OutputMapping(output_name="fog_probability", lane="FOG", label="FOG")],
        ).run()


def test_video_input_requires_video_path() -> None:
    runner = SequenceRunner([{"moving_bouts": np.zeros((0, 2), dtype=np.float32)}])
    package = CMFPackage(
        path=Path("dummy-model.rime"),
        config=CMFConfig(
            cmf_version="1.0",
            name="VideoModel",
            version="0.1.0",
            description="",
            license="",
            runtime_type="wrapper",
            runtime_entry="wrapper.py",
            inputs=[
                {
                    "name": "video_window",
                    "type": "video",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                }
            ],
            outputs=[
                {
                    "name": "moving_bouts",
                    "type": "interval",
                    "shape": [0, 2],
                }
            ],
            inference_mode="whole_signal",
            window_size_ms=1000,
            stride_ms=500,
            threshold=0.5,
            parameters=[],
            labels={"events": {"FOG": {"description": "Freezing of gait"}}},
            output_mappings=[],
        ),
        _runner=runner,
        _model_dir=Path("dummy-model"),
    )
    signal = _make_signal()

    with pytest.raises(InferenceError, match="video_path"):
        InferenceRunner(
            package,
            [InputBinding(input_name="video_window", signal=signal)],
            [OutputMapping(output_name="moving_bouts", lane="Tasks", label="Moving")],
        ).run()


def test_empty_output_mappings_raise_error() -> None:
    runner = SequenceRunner([])
    package = _make_package(runner)
    signal = _make_signal()

    with pytest.raises(InferenceError, match="output mapping"):
        InferenceRunner(
            package,
            [InputBinding(input_name="imu_window", signal=signal)],
            [],
        ).run()


def test_multiple_inputs_must_share_time_axis() -> None:
    runner = SequenceRunner(
        [
            {"fog_probability": np.array([0.1], dtype=np.float32)}
            for _ in range(9)
        ]
    )
    package = CMFPackage(
        path=Path("dummy-model.rime"),
        config=CMFConfig(
            cmf_version="1.0",
            name="MultiInput",
            version="0.1.0",
            description="",
            license="",
            runtime_type="wrapper",
            runtime_entry="wrapper.py",
            inputs=[
                {
                    "name": "imu_window",
                    "type": "signal",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                },
                {
                    "name": "imu_window_2",
                    "type": "signal",
                    "shape": [1, 10, 2],
                    "channels": ["acc_x", "acc_y"],
                    "sampling_rate_hz": 10,
                },
            ],
            outputs=[
                {
                    "name": "fog_probability",
                    "type": "probability",
                    "shape": [1],
                    "labels": ["no_fog", "fog"],
                }
            ],
            inference_mode="windowed",
            window_size_ms=1000,
            stride_ms=500,
            threshold=0.5,
            parameters=[],
            labels={"events": {"FOG": {"description": "Freezing of gait"}}},
            output_mappings=[],
        ),
        _runner=runner,
        _model_dir=Path("dummy-model"),
    )
    signal_a = _make_signal(name="a")
    signal_b = _make_signal(name="b", offset_ms=250.0)

    with pytest.raises(InferenceError, match="same window timeline"):
        InferenceRunner(
            package,
            [
                InputBinding(input_name="imu_window", signal=signal_a),
                InputBinding(input_name="imu_window_2", signal=signal_b),
            ],
            [OutputMapping(output_name="fog_probability", lane="FOG", label="FOG")],
        ).run()


def test_point_output_runs_once_on_full_signal() -> None:
    runner = SequenceRunner(
        [
            {
                "step_times": np.array([-10.0, 300.0, 1200.0, 6000.0], dtype=np.float32),
            }
        ]
    )
    package = _make_point_package(runner)
    signal = _make_signal(sample_count=50, sampling_rate_hz=10.0)

    result = InferenceRunner(
        package,
        [InputBinding(input_name="trunk_accel", signal=signal)],
        [OutputMapping(output_name="step_times", lane="Steps", label="step")],
    ).run()

    assert result.time_ms.size == 0
    assert len(runner.calls) == 1
    assert runner.calls[0]["trunk_accel"].shape == (50, 2)
    assert np.allclose(result.outputs[0].raw_predictions, np.array([300.0, 1200.0]))
    assert [annotation.event_type for annotation in result.outputs[0].annotations] == ["point", "point"]
    assert [annotation.start_ms for annotation in result.outputs[0].annotations] == [300.0, 1200.0]
    assert [annotation.end_ms for annotation in result.outputs[0].annotations] == [300.0, 1200.0]
    assert [annotation.origin_start_ms for annotation in result.outputs[0].annotations] == [300.0, 1200.0]
    assert [annotation.origin_end_ms for annotation in result.outputs[0].annotations] == [300.0, 1200.0]
    assert [annotation.origin_confidence for annotation in result.outputs[0].annotations] == [1.0, 1.0]


def test_channel_map_resolves_model_channels() -> None:
    runner = SequenceRunner([{"step_times": np.array([100.0], dtype=np.float32)}])
    package = _make_point_package(runner)
    signal = _make_signal(channels=["x", "y"], sample_count=20)

    result = InferenceRunner(
        package,
        [
            InputBinding(
                input_name="trunk_accel",
                signal=signal,
                channel_map={"acc_x": "x", "acc_y": "y"},
            )
        ],
        [OutputMapping(output_name="step_times", lane="Steps", label="step")],
    ).run()

    assert len(result.annotations) == 1
    assert runner.calls[0]["trunk_accel"].shape == (20, 2)


def test_time_range_offsets_annotations_and_time_axis() -> None:
    runner = SequenceRunner(
        [
            {"fog_probability": np.array([0.1], dtype=np.float32)},
            {"fog_probability": np.array([0.9], dtype=np.float32)},
            {"fog_probability": np.array([0.9], dtype=np.float32)},
            {"fog_probability": np.array([0.1], dtype=np.float32)},
        ]
    )
    package = _make_package(runner)
    signal = _make_signal(sample_count=30, sampling_rate_hz=10.0)

    result = InferenceRunner(
        package,
        [InputBinding(input_name="imu_window", signal=signal)],
        [OutputMapping(output_name="fog_probability", lane="FOG", label="FOG")],
    ).run(time_range=(1000.0, 3000.0))

    assert np.allclose(result.time_ms, np.array([1000.0, 1500.0, 2000.0]))
    assert len(result.annotations) == 1
    assert result.annotations[0].start_ms == 1500.0
    assert result.annotations[0].end_ms == 3000.0
    assert result.annotations[0].origin_start_ms == 1500.0
    assert result.annotations[0].origin_end_ms == 3000.0
