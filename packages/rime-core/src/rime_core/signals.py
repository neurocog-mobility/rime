"""Signal loading and representation for RIME."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from rime_core.session import SignalConfig


def detect_signal_config(path: str | Path, sample_rows: int = 200) -> dict[str, object]:
    """Infer basic signal config values from a CSV header and sample rows."""
    signal_path = Path(path)
    if signal_path.suffix.lower() != ".csv":
        return {
            "columns": [],
            "time_column": "time",
            "sampling_rate_hz": 100.0,
            "time_unit": "seconds",
            "channels": [],
        }

    try:
        df = pd.read_csv(signal_path, nrows=sample_rows)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"No columns found in signal file: {signal_path}") from exc
    columns = list(df.columns)
    if not columns:
        raise ValueError(f"No columns found in signal file: {signal_path}")

    time_column = next(
        (name for name in ["timestamp", "time", "t", "time_s"] if name in columns),
        columns[0],
    )
    sampling_rate_hz = 100.0
    time_unit = "seconds"

    if time_column in df.columns and len(df.index) >= 10:
        time_values = pd.to_numeric(df[time_column], errors="coerce")
        dt = time_values.diff().dropna().abs().median()
        if pd.notna(dt) and float(dt) > 0:
            dt_value = float(dt)
            if dt_value > 1000:
                time_unit = "microseconds"
                sampling_rate_hz = round(1_000_000 / dt_value)
            elif dt_value > 1:
                time_unit = "milliseconds"
                sampling_rate_hz = round(1_000 / dt_value)
            else:
                sampling_rate_hz = round(1 / dt_value)

    channels = [column for column in columns if column != time_column]
    return {
        "columns": columns,
        "time_column": time_column,
        "sampling_rate_hz": float(sampling_rate_hz),
        "time_unit": time_unit,
        "channels": channels,
    }


@dataclass
class Signal:
    """Loaded signal data with metadata."""

    name: str
    data: pd.DataFrame
    sampling_rate_hz: float
    time_column: str
    channels: list[str]
    offset_ms: float = 0.0
    time_reference: str = "relative"
    time_unit: str = "seconds"

    @property
    def duration_ms(self) -> float:
        """Total duration of the signal in milliseconds."""
        if len(self.data) == 0:
            return 0.0
        time_ms = self.get_time_ms()
        return float(time_ms[-1] - time_ms[0])

    @property
    def num_samples(self) -> int:
        """Number of samples in the signal."""
        return len(self.data)

    def get_time_ms(self) -> np.ndarray:
        """Get time array in milliseconds (relative to signal start + offset)."""
        if self.time_reference == "sample_index":
            sample_count = len(self.data)
            time_ms = np.arange(sample_count, dtype=np.float64) / self.sampling_rate_hz * 1000.0
            return time_ms + self.offset_ms

        if self.time_column not in self.data.columns:
            raise ValueError(
                f"Time column '{self.time_column}' not found. Available: {list(self.data.columns)}"
            )

        time = self.data[self.time_column].to_numpy(dtype=np.float64)
        if self.time_unit == "milliseconds":
            time = time / 1_000.0
        elif self.time_unit == "microseconds":
            time = time / 1_000_000.0
        elif self.time_unit == "nanoseconds":
            time = time / 1_000_000_000.0
        elif self.time_unit != "seconds":
            raise ValueError(f"Unsupported time unit: {self.time_unit}")

        time_ms = (time - time[0]) * 1000.0
        return time_ms + self.offset_ms

    def get_channel(self, channel_name: str) -> np.ndarray:
        """Get data for a specific channel."""
        if channel_name not in self.data.columns:
            raise ValueError(
                f"Channel '{channel_name}' not found. Available: {list(self.data.columns)}"
            )
        return self.data[channel_name].values


def load_csv_signal(
    path: str | Path,
    config: SignalConfig,
) -> Signal:
    """
    Load a CSV signal file.

    Args:
        path: Path to the CSV file.
        config: Signal configuration from session manifest.

    Returns:
        Signal object with loaded data.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If required columns are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Signal file not found: {path}")

    df = pd.read_csv(path)

    if config.time_reference != "sample_index" and config.time_column not in df.columns:
        raise ValueError(
            f"Time column '{config.time_column}' not found in {path}. "
            f"Available columns: {list(df.columns)}"
        )

    # Determine channels (all columns except time if not specified)
    channels = config.channels
    if not channels:
        channels = [c for c in df.columns if c != config.time_column]

    # Validate channels exist
    missing = [c for c in channels if c not in df.columns]
    if missing:
        raise ValueError(f"Channels not found in {path}: {missing}")

    return Signal(
        name=path.stem,
        data=df,
        sampling_rate_hz=config.sampling_rate_hz,
        time_column=config.time_column,
        channels=channels,
        offset_ms=config.offset_ms,
        time_reference=config.time_reference,
        time_unit=config.time_unit,
    )
