"""The package is a real fixed artifact; its contents remain inspectable."""

import hashlib
from pathlib import Path
import zipfile

import pytest

from rime_core.exchange import DocumentError, RimeDocument
from rime_core.record_comparison import compare_records


@pytest.fixture
def package_record(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "package_examples",
        Path(__file__).parents[1] / "examples/measurement-record/create_example.py",
    )
    examples = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(examples)
    path = tmp_path / "synthetic-package.zip"
    contents = {"fixture.json": b"synthetic fixture"}
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    raw = examples.computational().to_dict()
    package = next(n for n in raw["@graph"] if n["rime:data"].get("source_kind") == "model_package")
    package["rime:data"].update(
        file_name=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        manifest=[
            dict(file_name=name, sha256=hashlib.sha256(content).hexdigest())
            for name, content in contents.items()
        ],
    )
    return RimeDocument.from_dict(raw), path


def test_package_manifest_matches_archived_bytes(package_record):
    doc, path = package_record
    package = next(
        n for n in doc.nodes.values() if n["rime:data"].get("source_kind") == "model_package"
    )
    data = package["rime:data"]
    assert path.name == data["file_name"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == data["sha256"]
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == sorted(x["file_name"] for x in data["manifest"])
        for item in data["manifest"]:
            assert hashlib.sha256(archive.read(item["file_name"])).hexdigest() == item["sha256"]
    for activity in doc.nodes.values():
        if activity["rime:data"].get("method") == "computational":
            uses = [
                u
                for u in activity["prov:qualifiedUsage"]
                if u["prov:hadRole"]["@id"] == "rime:model_package"
            ]
            assert len(uses) == 1
            assert uses[0]["prov:entity"]["@id"] == package["@id"]


def test_manifest_change_is_visible_in_record_comparison(package_record):
    doc, _ = package_record
    raw = doc.to_dict()
    package = next(n for n in raw["@graph"] if n["rime:data"].get("source_kind") == "model_package")
    package["rime:data"]["manifest"][0]["sha256"] = "0" * 64
    changed = RimeDocument.from_dict(raw)
    diff = compare_records(doc, changed, doc.records[0], changed.records[0])
    component = next(c for c in diff["components"] if c.get("id_a") == package["@id"])
    assert component["status"] == "different"
    assert any(
        "/manifest" in a["path"] and a["status"] == "different" for a in component["attributes"]
    )
    package["rime:data"]["manifest"][0]["sha256"] = "invalid"
    with pytest.raises(DocumentError):
        RimeDocument.from_dict(raw)
