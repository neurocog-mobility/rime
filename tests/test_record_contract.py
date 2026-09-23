"""Positive workflow cases and rejection of connections outside the closed matrix."""

import importlib.util
from pathlib import Path

import pytest

from rime_core.exchange import DocumentError, RimeDocument

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "contract_examples", ROOT / "examples/measurement-record/create_example.py"
)
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


def node(raw, kind):
    return next(n for n in raw["@graph"] if "rime:" + kind in n["@type"])


@pytest.mark.parametrize(
    "case", ["manual", "verification", "model", "model_review", "adjudication", "import"]
)
def test_declared_cases(case):
    doc = {
        "manual": examples.synthetic,
        "verification": lambda: examples.synthetic(True),
        "model": examples.computational,
        "model_review": lambda: examples.computational(True),
        "adjudication": examples.adjudication,
        "import": examples.imported,
    }[case]()
    assert doc.to_dict()["rime:version"] == "1.1"
    assert RimeDocument.from_dict(doc.to_dict()).to_dict() == doc.to_dict()
    assert not any(
        n["rime:data"].get("kind") in ("software", "organization") for n in doc.nodes.values()
    )


@pytest.mark.parametrize(
    "damage",
    [
        "unknown_method",
        "unknown_role",
        "wrong_role_for_method",
        "wrong_source_kind",
        "missing_mapping",
        "manual_model_agent",
        "calculation_agent",
        "import_agent",
        "missing_model_agent",
        "model_person_agent",
        "missing_package",
        "review_model_agent",
        "adjudication_one_set",
        "manual_execution",
        "free_top_field",
        "extra_scope",
        "extra_output",
        "bad_source_generator",
        "old_version",
    ],
)
def test_forbidden_connections(damage):
    if damage in ("missing_model_agent", "model_person_agent", "missing_package"):
        doc = examples.computational()
    elif damage in ("review_model_agent", "adjudication_one_set"):
        doc = examples.synthetic(True)
    elif damage == "import_agent":
        doc = examples.imported()
    else:
        doc = examples.synthetic()
    raw = doc.to_dict()
    production = node(raw, "AnnotationProduction")
    calc = node(raw, "MeasurementCalculation")
    person = next((n for n in raw["@graph"] if "prov:Agent" in n["@type"]), None)
    if damage == "unknown_method":
        production["rime:data"]["method"] = "other"
    elif damage == "unknown_role":
        production["prov:qualifiedUsage"][0]["prov:hadRole"]["@id"] = "rime:anything"
    elif damage == "wrong_role_for_method":
        production["prov:qualifiedUsage"][0]["prov:hadRole"]["@id"] = "rime:import_file"
    elif damage == "wrong_source_kind":
        source = node(raw, "Source")
        source["rime:data"]["source_kind"] = "annotation_file"
        source["rime:data"].pop("modality")
    elif damage == "missing_mapping":
        production["prov:qualifiedUsage"][0].pop("rime:data")
    elif damage in ("manual_model_agent", "review_model_agent"):
        person["rime:data"]["kind"] = "model"
    elif damage == "calculation_agent":
        calc["prov:wasAssociatedWith"] = [{"@id": person["@id"]}]
    elif damage == "import_agent":
        raw["@graph"].append(
            {
                "@id": "urn:person",
                "@type": ["prov:Agent"],
                "rime:data": {"name": "Importer", "kind": "person"},
            }
        )
        production["prov:wasAssociatedWith"] = [{"@id": "urn:person"}]
    elif damage == "missing_model_agent":
        production["prov:wasAssociatedWith"] = []
    elif damage == "model_person_agent":
        person["rime:data"]["kind"] = "person"
    elif damage == "missing_package":
        production["prov:qualifiedUsage"] = [
            u
            for u in production["prov:qualifiedUsage"]
            if u["prov:hadRole"]["@id"] != "rime:model_package"
        ]
        production["prov:used"] = [u["prov:entity"] for u in production["prov:qualifiedUsage"]]
    elif damage == "adjudication_one_set":
        node(raw, "AnnotationReview")["rime:data"]["method"] = "adjudication"
    elif damage == "manual_execution":
        production["rime:data"]["execution_specification"] = {}
    elif damage == "free_top_field":
        production["rime:data"]["invented_field"] = "anything"
    elif damage == "extra_scope":
        target = node(raw, "AnnotationSet")["@id"]
        calc["prov:qualifiedUsage"].append(
            {
                "@type": "prov:Usage",
                "prov:entity": {"@id": target},
                "prov:hadRole": {"@id": "rime:scope_annotations"},
            }
        )
    elif damage == "extra_output":
        import copy

        extra = copy.deepcopy(node(raw, "AnnotationSet"))
        extra["@id"] = "urn:extra"
        raw["@graph"].append(extra)
    elif damage == "bad_source_generator":
        node(raw, "Source")["prov:wasGeneratedBy"] = {"@id": production["@id"]}
    elif damage == "old_version":
        raw["rime:version"] = "1.0"
    with pytest.raises(DocumentError):
        RimeDocument.from_dict(raw)


def test_explicit_unknown_human_responsibility():
    raw = examples.synthetic().to_dict()
    production = node(raw, "AnnotationProduction")
    production["prov:wasAssociatedWith"] = []
    production["rime:data"]["responsibility"] = "unknown"
    raw["@graph"] = [n for n in raw["@graph"] if "prov:Agent" not in n["@type"]]
    RimeDocument.from_dict(raw)


def test_review_may_use_recording_evidence_locally():
    raw = examples.synthetic(True).to_dict()
    production = node(raw, "AnnotationProduction")
    review = node(raw, "AnnotationReview")
    import copy

    review["prov:qualifiedUsage"].append(copy.deepcopy(production["prov:qualifiedUsage"][0]))
    review["prov:used"].append(copy.deepcopy(production["prov:used"][0]))
    RimeDocument.from_dict(raw)
