from __future__ import annotations

import os

import pandas as pd
from PySide6.QtWidgets import QApplication

from rime_core.signals import Signal
from rime_ui.signals import SignalTrackWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _signal(name: str, channels: list[str]) -> Signal:
    data = {"time": [0.0, 0.5, 1.0]}
    for index, channel in enumerate(channels):
        data[channel] = [float(index), float(index + 1), float(index + 2)]
    return Signal(
        name=name,
        data=pd.DataFrame(data),
        sampling_rate_hz=2.0,
        time_column="time",
        channels=channels,
    )


def test_signal_panel_defaults_to_combined_view() -> None:
    _app()
    widget = SignalTrackWidget()
    widget.set_display_config(
        [
            (_signal("Trunk", ["acc_x", "acc_y"]), ["acc_x"]),
            (_signal("Leg", ["gyro_x"]), ["gyro_x"]),
        ]
    )

    assert widget._combined_view is True
    assert widget.current_label.text() == "All signals (2)"


def test_signal_panel_cycles_single_signal_view() -> None:
    _app()
    widget = SignalTrackWidget()
    widget.set_display_config(
        [
            (_signal("Trunk", ["acc_x"]), ["acc_x"]),
            (_signal("Leg", ["gyro_x"]), ["gyro_x"]),
        ]
    )

    widget.set_combined_view(False)
    assert widget.current_label.text() == "Trunk"
    widget._advance_signal(1)
    assert widget.current_label.text() == "Leg"


def test_signal_panel_applies_channel_selection_filter() -> None:
    _app()
    widget = SignalTrackWidget()
    widget.set_display_config(
        [
            (_signal("Trunk", ["acc_x", "acc_y"]), ["acc_x", "acc_y"]),
            (_signal("Leg", ["gyro_x"]), ["gyro_x"]),
        ]
    )

    widget._apply_channel_selection({"Trunk": ["acc_y"]})

    assert widget._entries[0].channels == ["acc_y"]
    assert widget._entries[1].channels == []
    assert widget.current_label.text() == "All signals (1)"


def test_signal_panel_keeps_hidden_entries_available_for_selector() -> None:
    _app()
    widget = SignalTrackWidget()
    widget.set_display_config(
        [
            (_signal("Trunk", ["acc_x", "acc_y"]), []),
            (_signal("Leg", ["gyro_x"]), ["gyro_x"]),
        ]
    )

    assert len(widget._entries) == 2
    assert widget.selector_button.isEnabled() is True
    assert widget.current_label.text() == "All signals (1)"
