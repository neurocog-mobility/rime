from __future__ import annotations

from pathlib import Path

import pytest

from rime_core.loaders import SignalLoaderError, SignalLoaderRegistry
from rime_core.session import SignalConfig


def test_default_registry_loads_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "signal.csv"
    csv_path.write_text("time,acc_x\n0.0,1.0\n0.5,2.0\n", encoding="utf-8")

    registry = SignalLoaderRegistry.default()
    signal = registry.load(
        csv_path,
        SignalConfig(
            path=str(csv_path),
            type="imu",
            format="csv",
            sampling_rate_hz=2.0,
            time_column="time",
            channels=["acc_x"],
        ),
    )

    assert signal.name == "signal"
    assert signal.channels == ["acc_x"]


def test_unknown_loader_format_raises_error(tmp_path: Path) -> None:
    registry = SignalLoaderRegistry.default()
    fake_path = tmp_path / "signal.fake"
    fake_path.write_text("ignored", encoding="utf-8")

    with pytest.raises(SignalLoaderError, match="No signal loader registered"):
        registry.load(
            fake_path,
            SignalConfig(
                path=str(fake_path),
                type="imu",
                format="fake",
                sampling_rate_hz=1.0,
                time_column="time",
            ),
        )


def test_register_overwrites_previous_loader_and_supported_formats() -> None:
    registry = SignalLoaderRegistry()

    def first_loader(path: Path, config: SignalConfig):  # pragma: no cover - overwritten
        return ("first", path, config)

    def second_loader(path: Path, config: SignalConfig):
        return ("second", path, config)

    registry.register("csv", first_loader)
    registry.register("csv", second_loader)

    assert registry.can_load("csv") is True
    assert registry.can_load("hdf5") is False
    assert registry.supported_formats() == ["csv"]

    path = Path("demo.csv")
    config = SignalConfig(
        path=str(path),
        type="imu",
        format="csv",
        sampling_rate_hz=1.0,
        time_column="time",
    )
    loaded = registry.load(path, config)
    assert loaded[0] == "second"
