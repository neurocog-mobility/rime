"""Shared time-unit helpers."""

from __future__ import annotations

from typing import Any


_SECONDS_PER_TIME_UNIT = {
    "seconds": 1.0,
    "milliseconds": 1 / 1_000.0,
    "microseconds": 1 / 1_000_000.0,
    "nanoseconds": 1 / 1_000_000_000.0,
}


def time_values_to_seconds(values: Any, time_unit: str) -> Any:
    """Convert scalar or vector time values to seconds."""
    try:
        return values * _SECONDS_PER_TIME_UNIT[time_unit]
    except KeyError as exc:
        raise ValueError(f"Unsupported time unit: {time_unit}") from exc
