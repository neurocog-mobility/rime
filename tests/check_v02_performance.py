"""Repeatable synthetic v0.2 performance smoke check; no participant data required.

Run: QT_QPA_PLATFORM=offscreen .venv/bin/python tests/check_v02_performance.py
Timings are observations, not platform-independent pass/fail thresholds.
"""

# ruff: noqa: E402 -- source paths and headless Qt must be configured before imports
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
for package in ("rime-core", "rime-ui"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from rime_core.annotation_workspace import AnnotationWorkspace, source_entry
from rime_core.annotations import Annotation
from rime_core.exchange import read_document, write_document
from rime_core.measurement_capture import capture_measurements, preview_measurements
from rime_core.record_inspection import inspection_graph, verify_record
from rime_core.record_overlay import overlay_records, recover_record
from rime_core.records import VideoSource
from rime_core.schema import ProtocolSchema
from rime_ui.presentation.window import RimeWindow
from rime_ui.presentation.record_graph import RecordGraph
from rime_ui.timeline import AnnotationLanes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    results = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "qt_platform": app.platformName(),
        "repeats": args.repeats,
        "workloads": {},
    }

    def measure(target, name, fn):
        print(f"Measuring {name}", file=sys.stderr, flush=True)
        times = []
        for _ in range(args.repeats):
            start = time.perf_counter()
            value = fn()
            times.append((time.perf_counter() - start) * 1000)
        target[name] = {
            "median_ms": round(statistics.median(times), 2),
            "max_ms": round(max(times), 2),
        }
        return value

    def startup():
        window = RimeWindow()
        window.show()
        app.processEvents()
        window.close()
        window.deleteLater()
        app.processEvents()

    measure(results, "warm_shell_start", startup)
    with tempfile.TemporaryDirectory(prefix="rime-performance-") as folder:
        folder = Path(folder)
        # Synthetic source identity only: no video decoding is claimed by this workload.
        source = folder / "synthetic.bin"
        source.write_bytes(bytes(1024 * 1024))
        schema = ProtocolSchema.from_dict(
            {
                "name": "Performance",
                "version": "1",
                "rules": [],
                "groups": [],
                "lanes": [{"name": "Event", "level": 1, "labels": ["Freeze"], "color": "#444444"}],
                "measurements": [
                    dict(
                        id=op,
                        name=op,
                        calculation=op,
                        events={"lane": "Event", "label": "Freeze"},
                        scope=None,
                    )
                    for op in ("covered_duration", "percentage_coverage", "count")
                ],
            }
        )
        import cv2
        import numpy as np
        import pandas as pd
        from PySide6.QtTest import QTest
        from rime_core.records import SignalSource
        from rime_core.signals import load_csv_signal
        from rime_ui.widgets.signals import SignalTrackWidget
        from rime_ui.widgets.multi_view_player import MultiViewPlayer

        signal_times = results["signal_30min_100hz_3channels"] = {}
        t = np.arange(180000) / 100
        csv = folder / "signal.csv"
        pd.DataFrame({"time": t, **{f"axis{i}": np.sin(t * (i + 1)) for i in range(3)}}).to_csv(
            csv, index=False
        )
        config = SignalSource(
            type="imu",
            format="csv",
            sampling_rate_hz=100,
            time_column="time",
            channels=["axis0", "axis1", "axis2"],
        )
        signal = measure(signal_times, "csv_load", lambda: load_csv_signal(csv, config))
        widget = SignalTrackWidget()
        widget.resize(1200, 400)
        widget.show()

        def signal_plot():
            widget.set_display_config([(signal, signal.channels)])
            app.processEvents()
            widget.grab()

        measure(signal_times, "configure_and_paint", signal_plot)
        widget.close()
        widget.deleteLater()

        video = folder / "video.avi"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 30, (640, 360))
        assert writer.isOpened()
        for frame in range(150):
            writer.write(np.full((360, 640, 3), frame % 255, dtype=np.uint8))
        writer.release()
        player = MultiViewPlayer()
        configs = [VideoSource(label="Video 1", role="primary"), VideoSource(label="Video 2")]
        player.load_videos(configs, {c.id: str(video) for c in configs})
        player.show()
        deadline = time.monotonic() + 10
        while any(p.player.duration() == 0 for p in player._panes):
            assert time.monotonic() < deadline, "Synthetic video failed to load"
            QTest.qWait(10)
        # Let each pane finish its initial first-frame preview/pause.
        QTest.qWait(150)
        counts = [0, 0]

        def count_frame(index, frame):
            if frame.isValid():
                counts[index] += 1

        for index, pane in enumerate(player._panes):
            pane.video_widget.videoSink().videoFrameChanged.connect(
                lambda frame, index=index: count_frame(index, frame)
            )
            pane.player.play()
        start = time.perf_counter()
        QTest.qWait(2000)
        elapsed = time.perf_counter() - start
        for pane in player._panes:
            pane.player.pause()
        assert all(count > 0 for count in counts), "Both video panes must deliver frames"
        results["two_video_640x360_30fps"] = {
            "elapsed_s": round(elapsed, 3),
            "delivered_frames": list(counts),
            "delivered_fps": [round(count / elapsed, 1) for count in counts],
            "position_difference_ms": abs(
                player._panes[0].player.position() - player._panes[1].player.position()
            ),
        }
        player.load_videos([], {})
        player.close()
        player.deleteLater()

        for size in args.sizes:
            timings = results["workloads"][str(size)] = {}
            workspace = AnnotationWorkspace.create(
                "Synthetic performance",
                schema,
                [source_entry(source, VideoSource(label="Video 1"), "video")],
            )
            workspace.data["annotations"] = [
                asdict(Annotation(str(i), "Event", "Freeze", i * 1000, i * 1000 + 500))
                for i in range(size)
            ]
            duration = size * 1000
            measure(timings, "workspace_save", lambda: workspace.save(folder / "workspace.json"))
            measure(timings, "workspace_open", lambda: AnnotationWorkspace.open(workspace.path))
            previews = measure(
                timings,
                "three_measurement_preview",
                lambda: preview_measurements(workspace.data, duration),
            )
            assert [p["result"]["value"] for p in previews] == [size / 2, 50, size]

            def edit():
                workspace.put_annotation(Annotation("0", "Event", "Freeze", 0, 600))
                workspace.undo()

            measure(timings, "edit_and_undo", edit)
            doc = measure(
                timings, "capture", lambda: capture_measurements(workspace.data, duration)
            )
            measure(timings, "document_write", lambda: write_document(folder / "record.rime", doc))
            loaded = measure(
                timings, "document_read", lambda: read_document(folder / "record.rime")
            )
            checks = measure(
                timings,
                "verify_three_results",
                lambda: [verify_record(loaded, root) for root in loaded.records],
            )
            assert all(check["matches"] for check in checks)
            model = measure(
                timings, "inspection_graph", lambda: inspection_graph(doc, doc.records[0])
            )
            overlay = measure(
                timings,
                "equal_record_overlay",
                lambda: overlay_records(doc, loaded, doc.records[0], loaded.records[0]),
            )
            assert recover_record(overlay, "a")
            graph = RecordGraph()
            graph.resize(1200, 700)
            graph.show()

            def paint_graph():
                graph.set_model(model)
                app.processEvents()
                graph.grab()

            measure(timings, "graph_layout_and_paint", paint_graph)
            graph.close()
            lanes = AnnotationLanes(schema, single_set=True)
            lanes.resize(1200, 400)
            lanes.set_duration(duration)
            lanes.set_store(workspace.store)
            lanes.show()
            measure(timings, "timeline_paint", lambda: (app.processEvents(), lanes.grab()))
            lanes.close()
            graph.deleteLater()
            lanes.deleteLater()
            app.processEvents()
            timings["document_bytes"] = (folder / "record.rime").stat().st_size
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
