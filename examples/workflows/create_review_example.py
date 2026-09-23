"""Create a resumable review demonstration, reusing the synthetic workflow media."""

import argparse
from copy import deepcopy
from pathlib import Path
import uuid

from rime_core.annotation_workspace import AnnotationWorkspace
from rime_core.annotations import Annotation
from rime_core.review_workspace import ReviewWorkspace, load_input


def create(destination, source):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Choose an empty destination; existing reviews are never overwritten.")
    template = AnnotationWorkspace.open(source)
    destination.mkdir(parents=True, exist_ok=True)
    inputs = []
    for name, spans in (
        ("A", [(2000, 4000), (7000, 9000), (13000, 16000)]),
        ("B", [(2200, 4500), (7400, 9300), (14000, 16000)]),
    ):
        data = deepcopy(template.data)
        data.update(id=uuid.uuid4().hex, name=f"Illustrative annotator {name}",
                    rater=f"Synthetic {name}", annotations=[])
        workspace = AnnotationWorkspace(data)
        for index, (start, end) in enumerate(spans):
            workspace.put_annotation(Annotation(f"demo-{name}-{index}", "Events", "Event", start, end))
        workspace.save(destination / f"input-{name.lower()}.json")
        inputs.append(load_input(workspace.path))
    review = ReviewWorkspace.create_review("Review demonstration", "Example reviewer", inputs)
    refs = review.input_refs("Events", "Event")
    for index, choice, note in (
        (0, "union", "Illustrative decision: retain the full interval marked by either input."),
        (1, "custom", "Illustrative discussion note: inspected both boundaries; agreed on 7.2–9.1 s."),
    ):
        selected = [r for r in refs if r["annotation"].endswith(f"-{index}")]
        review.save_decision(review.selection(selected), choice, [[7200, 9100]] if index else [], note)
    review.save(destination / "review.json")
    return review.path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path, default=Path(__file__).parent / "review-demo")
    parser.add_argument("--source", type=Path, default=Path(__file__).parent / "generated/annotation.json")
    args = parser.parse_args()
    print(create(args.destination, args.source))
