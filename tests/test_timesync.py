from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from rime_core.sessions import SignalConfig
from rime_core.signals import Signal, load_csv_signal


def test_relative_signal_time_axis_uses_offset() -> None:
    signal = Signal(
        name="relative",
        data=pd.DataFrame({"time": [10.0, 10.5, 11.0], "acc_x": [0.0, 1.0, 2.0]}),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=["acc_x"],
        offset_ms=25.0,
        time_reference="relative",
        time_unit="seconds",
    )

    assert np.allclose(signal.get_time_ms(), np.array([25.0, 525.0, 1025.0]))


def test_utc_epoch_microseconds_normalize_correctly() -> None:
    signal = Signal(
        name="utc",
        data=pd.DataFrame(
            {
                "timestamp": [1_700_000_000_000_000, 1_700_000_000_500_000, 1_700_000_001_000_000],
                "acc_x": [0.0, 1.0, 2.0],
            }
        ),
        sampling_rate_hz=2.0,
        time_column="timestamp",
        channels=["acc_x"],
        offset_ms=10.0,
        time_reference="utc_epoch",
        time_unit="microseconds",
    )

    assert np.allclose(signal.get_time_ms(), np.array([10.0, 510.0, 1010.0]))


def test_sample_index_time_axis_is_synthesized() -> None:
    signal = Signal(
        name="index",
        data=pd.DataFrame({"acc_x": [0.0, 1.0, 2.0, 3.0]}),
        sampling_rate_hz=10.0,
        time_column="time",
        channels=["acc_x"],
        offset_ms=5.0,
        time_reference="sample_index",
        time_unit="seconds",
    )

    assert np.allclose(signal.get_time_ms(), np.array([5.0, 105.0, 205.0, 305.0]))


def test_load_csv_signal_allows_sample_index_without_time_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "signal.csv"
    csv_path.write_text("acc_x,acc_y\n0,1\n2,3\n4,5\n", encoding="utf-8")

    signal = load_csv_signal(
        csv_path,
        SignalConfig(
            path=str(csv_path),
            type="imu",
            format="csv",
            sampling_rate_hz=10.0,
            time_column="time",
            time_reference="sample_index",
            channels=["acc_x", "acc_y"],
        ),
    )

    assert np.allclose(signal.get_time_ms(), np.array([0.0, 100.0, 200.0]))
