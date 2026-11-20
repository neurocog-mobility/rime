from copy import deepcopy
from dataclasses import asdict

import pympi
import pytest

from rime_core.annotation_workspace import AnnotationWorkspace, import_annotations
from rime_core.records import VideoSource
from rime_core.schema import ProtocolSchema
from rime_core.suggestions import decide, pending


@pytest.mark.parametrize("enabled", [False, True])
def test_import_suggestions_are_optional_pending_and_persisted(tmp_path, enabled):
    workspace = AnnotationWorkspace.create(
        "Import", ProtocolSchema.default(),
        [{"kind": "video", "path": str(tmp_path / "video.mp4"),
          "config": asdict(VideoSource(label="Video 1"))}],
    )
    eaf = pympi.Elan.Eaf()
    eaf.add_tier("FOG")
    eaf.add_annotation("FOG", 100, 300, "FOG")
    path = tmp_path / "annotations.eaf"
    eaf.to_file(str(path))
    original_file = path.read_bytes()
    before = deepcopy(workspace.data)
    kwargs = {"generate_suggestions": True} if enabled else {}
    assert import_annotations(workspace, path, {"FOG": "FOG"}, **kwargs) == 1
    assert len(workspace.data["annotations"]) == 1
    assert workspace.data["imports"][0]["generate_suggestions"] is enabled
    proposals = pending(workspace.data)
    assert bool(proposals) is enabled
    if enabled:
        assert {item["annotation"]["lane"] for _, item in proposals} == {
            "Core", "Manifestations"
        }
    imported = deepcopy(workspace.data)
    workspace.undo()
    assert workspace.data == before
    workspace.redo()
    assert workspace.data == imported
    workspace.save(tmp_path / "workspace.json")
    reopened = AnnotationWorkspace.open(workspace.path)
    assert pending(reopened.data) == proposals
    if enabled:
        decide(reopened, proposals[0][1]["annotation"]["id"], "accept")
        assert len(reopened.data["annotations"]) == 2
        assert len(reopened.data["imports"][0]["annotations"]) == 1
    assert path.read_bytes() == original_file
