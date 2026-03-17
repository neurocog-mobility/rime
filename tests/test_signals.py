from __future__ import annotations

from pathlib import Path

import pytest

from rime_core.signals import detect_signal_config


def test_detect_signal_config_prefers_timestamp_and_estimates_hz(tmp_path: Path) -> None:
    csv_path = tmp_path / "signal.csv"
    csv_path.write_text(
        "timestamp,acc_x,acc_y\n"
        "0,1.0,2.0\n"
        "10000,1.1,2.1\n"
        "20000,1.2,2.2\n"
        "30000,1.3,2.3\n"
        "40000,1.4,2.4\n"
        "50000,1.5,2.5\n"
        "60000,1.6,2.6\n"
        "70000,1.7,2.7\n"
        "80000,1.8,2.8\n"
        "90000,1.9,2.9\n"
        "100000,2.0,3.0\n",
        encoding="utf-8",
    )

    detected = detect_signal_config(csv_path)

    assert detected["columns"] == ["timestamp", "acc_x", "acc_y"]
    assert detected["time_column"] == "timestamp"
    assert detected["sampling_rate_hz"] == 100.0
    assert detected["time_unit"] == "microseconds"
    assert detected["channels"] == ["acc_x", "acc_y"]


def test_detect_signal_config_falls_back_to_first_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "signal.csv"
    csv_path.write_text(
        "frame,acc_x\n"
        "0.00,1.0\n"
        "0.01,1.1\n"
        "0.02,1.2\n"
        "0.03,1.3\n"
        "0.04,1.4\n"
        "0.05,1.5\n"
        "0.06,1.6\n"
        "0.07,1.7\n"
        "0.08,1.8\n"
        "0.09,1.9\n"
        "0.10,2.0\n",
        encoding="utf-8",
    )

    detected = detect_signal_config(csv_path)

    assert detected["time_column"] == "frame"
    assert detected["sampling_rate_hz"] == 100.0
    assert detected["time_unit"] == "seconds"
    assert detected["channels"] == ["acc_x"]


def test_detect_signal_config_non_csv_returns_defaults(tmp_path: Path) -> None:
    signal_path = tmp_path / "signal.h5"
    signal_path.write_text("ignored", encoding="utf-8")

    detected = detect_signal_config(signal_path)

    assert detected["columns"] == []
    assert detected["time_column"] == "time"
    assert detected["sampling_rate_hz"] == 100.0
    assert detected["time_unit"] == "seconds"
    assert detected["channels"] == []


def test_detect_signal_config_empty_csv_raises(tmp_path: Path) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        detect_signal_config(csv_path)
