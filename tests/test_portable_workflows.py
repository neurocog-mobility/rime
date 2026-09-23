"""Public workflows remain usable after copying a checkout to another machine."""

from pathlib import Path
import json
import shutil

import pytest

from rime_core.annotation_workspace import AnnotationWorkspace
from rime_core.review_workspace import ReviewWorkspace
from rime_core.measurement_capture import capture_measurements
from rime_core.record_inspection import verify_record

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/workflows"


@pytest.mark.parametrize("name", ["generated/annotation.json", "generated/suggestions.json",
                                  "generated/review.json", "review-demo/review.json"])
def test_relocated_examples_and_save_as(tmp_path, monkeypatch, name):
    copied = tmp_path / "relocated"
    for folder in ("generated", "review-demo"):
        shutil.copytree(EXAMPLES / folder, copied / folder)
    monkeypatch.chdir(tmp_path)
    path = copied / name
    raw = json.loads(path.read_text())
    assert all(not Path(source["path"]).is_absolute() for source in raw["sources"])
    kind = ReviewWorkspace if raw["format"] == ReviewWorkspace.format else AnnotationWorkspace
    workspace = kind.open(path)
    assert not workspace.dirty
    assert all(Path(source["path"]).is_relative_to(copied) for source in workspace.data["sources"])
    if isinstance(workspace, ReviewWorkspace):
        workspace.verify_evidence()
    before = capture_measurements(workspace.data, 20000)
    workspace.save(tmp_path / "another-folder/saved.json")
    restored = kind.open(workspace.path)
    assert restored.data == workspace.data
    if isinstance(restored, ReviewWorkspace):
        restored.verify_evidence()
    doc = capture_measurements(restored.data, 20000)
    assert [doc.nodes[r]["rime:data"]["value"] for r in doc.records] == [
        before.nodes[r]["rime:data"]["value"] for r in before.records
    ]
    assert all(verify_record(doc, root)["matches"] for root in doc.records)
