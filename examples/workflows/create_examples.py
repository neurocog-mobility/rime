"""Generate the compact native workflow set using synthetic evidence only."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import cv2
import numpy as np
from rime_core.annotation_workspace import AnnotationWorkspace, source_entry
from rime_core.annotations import Annotation
from rime_core.cmf import CMFLoader
from rime_core.exchange import write_document
from rime_core.measurement_capture import capture_measurements
from rime_core.records import VideoSource, SignalSource
from rime_core.review_workspace import ReviewWorkspace, load_input
from rime_core.schema import ProtocolSchema
from rime_core.suggestions import execute, admit


ROOT = Path(__file__).resolve().parents[2]


def create(destination):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(
            "Choose an empty destination; existing annotation work is never overwritten."
        )
    destination.mkdir(parents=True, exist_ok=True)
    evidence = destination / "evidence"
    evidence.mkdir()
    for index in (1, 2):
        video = evidence / f"video-{index}.avi"
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 20, (320, 180))
        if not writer.isOpened():
            raise RuntimeError("MJPEG writer unavailable")
        for frame in range(400):
            image = np.full((180, 320, 3), 235 if index == 1 else 215, np.uint8)
            cv2.putText(
                image,
                f"Synthetic {index}: {frame / 20:.2f}s",
                (12, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (40, 40, 40),
                1,
            )
            writer.write(image)
        writer.release()
    t = np.arange(2000) / 100
    values = sum(((t >= a) & (t < b)).astype(float) for a, b in [(2, 4), (7, 9), (13, 16)])
    np.savetxt(
        evidence / "signal.csv",
        np.column_stack((t, values)),
        delimiter=",",
        header="time,value",
        comments="",
        fmt="%.3f",
    )
    schema = ProtocolSchema.from_dict(
        dict(
            name="Synthetic workflow",
            version="1",
            lanes=[dict(name="Events", level=1, labels=["Event"], color="#4477aa")],
            rules=[],
            groups=[],
            measurements=[
                dict(id=op, name=op, calculation=op, events={"lane": "Events", "label": "Event"})
                for op in ["covered_duration", "percentage_coverage", "count"]
            ],
        )
    )
    videos = [
        source_entry(
            evidence / f"video-{i}.avi",
            VideoSource(label=f"Video {i}", role="primary" if i == 1 else "secondary"),
            "video",
        )
        for i in (1, 2)
    ]
    signals = [
        source_entry(
            evidence / "signal.csv",
            SignalSource(
                type="signal",
                format="csv",
                sampling_rate_hz=100,
                time_column="time",
                channels=["value"],
            ),
            "signal",
        )
    ]
    a = AnnotationWorkspace.create("Synthetic annotator A", schema, videos, signals)
    a.data["rater"] = "Synthetic A"
    for i, (start, end) in enumerate([(2000, 4000), (7000, 9000)]):
        a.put_annotation(Annotation(str(i), "Events", "Event", start, end))
    a.save(destination / "annotation.json")
    b = AnnotationWorkspace.create("Synthetic annotator B", schema, videos, signals)
    b.data["rater"] = "Synthetic B"
    for annotation in a.store.all():
        b.put_annotation(replace(annotation, end_ms=annotation.end_ms + 500))
    b.save(destination / "review-input-b.json")
    review = ReviewWorkspace.create_review(
        "Synthetic adjudication", "Synthetic reviewer", [load_input(a.path), load_input(b.path)]
    )
    refs = review.input_refs("Events", "Event")
    review.save_decision(review.selection(refs), "union")
    review.save(destination / "review.json")
    package = destination / "threshold.cmf"
    package.mkdir()
    (package / "labels.json").write_text("{}\n")
    (package / "config.json").write_text(
        json.dumps(
            dict(
                cmf_version="1.1",
                name="Synthetic threshold",
                version="1",
                description="Synthetic software demonstration; not a clinical detector.",
                runtime={"type": "wrapper", "entry": "wrapper.py"},
                inputs=[
                    {
                        "name": "input",
                        "type": "signal",
                        "channels": ["value"],
                        "sampling_rate_hz": 100,
                    }
                ],
                outputs=[{"name": "events", "type": "interval"}],
                inference={"mode": "whole_signal", "threshold": 0.5},
                parameters=[],
                output_mappings=[{"output_name": "events", "lane": "Events", "label": "Event"}],
            ),
            indent=2,
        )
    )
    (package / "wrapper.py").write_text("""import numpy as np
class CMFModel:
    def predict(self, inputs, params):
        active = np.asarray(inputs['input'])[:, 0] > .5
        changes = np.diff(np.r_[False, active, False].astype(int))
        return {'events': np.column_stack((np.where(changes == 1)[0], np.where(changes == -1)[0])) * 10.0}
""")
    suggestions = AnnotationWorkspace.create("Synthetic model suggestions", schema, videos, signals)
    result = execute(
        CMFLoader.load(package),
        deepcopy(suggestions.data),
        [{"name": "input", "source": signals[0]["config"]["id"], "channels": {"value": "value"}}],
        [{"output_name": "events", "lane": "Events", "label": "Event"}],
        {},
        [0, 20000],
    )
    admit(suggestions, result)
    suggestions.save(destination / "suggestions.json")
    records = destination / "records"
    records.mkdir()
    write_document(records / "manual.rime", capture_measurements(a.data, 20000))
    write_document(records / "reviewed.rime", capture_measurements(review.data, 20000))
    spec = importlib.util.spec_from_file_location(
        "record_examples", ROOT / "examples/measurement-record/create_example.py"
    )
    examples = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(examples)
    for category in ["annotation_output", "measurement_output_only", "neither"]:
        for side, doc in zip("ab", examples.convergence_pair(category)):
            write_document(records / f"{category}.{side}.rime", doc)
    print(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "destination", nargs="?", type=Path, default=Path(__file__).parent / "generated"
    )
    create(parser.parse_args().destination)
