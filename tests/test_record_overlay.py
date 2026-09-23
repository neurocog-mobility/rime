"""Overlay correctness is lossless per-record recovery, not a particular layout."""

import importlib.util
import json
from pathlib import Path

import pytest

from rime_core.exchange import RimeDocument
from rime_core.record_comparison import _links, record_nodes
from rime_core.record_overlay import overlay_records, recover_record, to_mermaid, _acyclic

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "overlay_examples", ROOT / "examples/measurement-record/create_example.py"
)
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


def assert_lossless(a, b):
    view = overlay_records(a, b)
    assert _acyclic(view["nodes"], view["edges"])
    for side, doc in [("a", a), ("b", b)]:
        assert recover_record(view, side) == record_nodes(doc)
        _, original = record_nodes(doc)
        expected = [
            (owner, relation, role, target, json.dumps(attrs, sort_keys=True))
            for owner, n in original.items()
            for relation, role, target, attrs in _links(n)
        ]
        actual = [
            (
                e["originals"][side]["owner"],
                e["relation"],
                e["role"],
                e["originals"][side]["target"],
                json.dumps(e["originals"][side]["attributes"], sort_keys=True),
            )
            for e in view["edges"]
            if side in e["sides"]
        ]
        assert sorted(actual) == sorted(expected)
        ids = {n["id"] for n in view["nodes"] if side in n["sides"]}
        assert all(
            e["source"] in ids and e["target"] in ids for e in view["edges"] if side in e["sides"]
        )
    return view


@pytest.mark.parametrize("review", [False, True])
def test_identity_overlay_preserves_unknowns_and_review(review):
    a = examples.synthetic(review)
    view = assert_lossless(a, a)
    assert len(view["nodes"]) == len(a.nodes)
    assert any(n["unavailable"] for n in view["nodes"])
    assert all(n["sides"] == ["a", "b"] for n in view["nodes"])


def test_different_histories_and_one_sided_components():
    view = assert_lossless(examples.synthetic(), examples.synthetic(True))
    assert any(len(n["sides"]) == 1 for n in view["nodes"])


@pytest.mark.parametrize(
    "name", ["different_records_similar_result", "limited_record_difference_divergent_result"]
)
def test_synthetic_procedure_comparison(name):
    category = "annotation_output" if name == "different_records_similar_result" else "neither"
    a, b = examples.convergence_pair(category, operation="percentage_coverage")
    view = assert_lossless(a, b)
    calculations = [
        n
        for n in view["nodes"]
        if any("rime:MeasurementCalculation" in raw["@type"] for raw in n["originals"].values())
    ]
    if name == "different_records_similar_result":
        assert view["roots"]["a"] == view["roots"]["b"]
        assert len(calculations) == 1
        assert calculations[0]["sides"] == ["a", "b"]
    else:
        assert view["roots"]["a"] != view["roots"]["b"]
        assert len(calculations) == 2
        assert all(n["status"] == "changed" and len(n["sides"]) == 1 for n in calculations)
    assert view == overlay_records(a, b)
    assert to_mermaid(view) == to_mermaid(view)


def test_cycle_detection():
    nodes = [{"id": "x"}, {"id": "y"}]
    assert not _acyclic(nodes, [{"source": "x", "target": "y"}, {"source": "y", "target": "x"}])
    assert not _acyclic(nodes, [{"source": "x", "target": "x"}])
    assert _acyclic(nodes, [{"source": "x", "target": "y"}])


def test_multiple_review_inputs_and_production_branches():
    from copy import deepcopy

    a = examples.synthetic(True)
    nodes = deepcopy(list(a.nodes.values()))
    production = next(n for n in nodes if "rime:AnnotationProduction" in n["@type"])
    input_set = next(
        n for n in nodes if n.get("prov:wasGeneratedBy", {}).get("@id") == production["@id"]
    )
    other_production = deepcopy(production)
    other_production["@id"] += ":second"
    other_production["rime:data"]["description"] = "Second independent annotation"
    other_set = deepcopy(input_set)
    other_set["@id"] += ":second"
    other_set["prov:wasGeneratedBy"]["@id"] = other_production["@id"]
    review = next(n for n in nodes if "rime:AnnotationReview" in n["@type"])
    usage = deepcopy(review["prov:qualifiedUsage"][0])
    usage["prov:entity"]["@id"] = other_set["@id"]
    review["prov:qualifiedUsage"].append(usage)
    review["prov:used"].append({"@id": other_set["@id"]})
    b = RimeDocument.create(nodes + [other_production, other_set], a.records)
    view = assert_lossless(a, b)
    assert any(
        "rime:AnnotationProduction" in n["originals"]["b"]["@type"] and n["sides"] == ["b"]
        for n in view["nodes"]
        if "b" in n["sides"]
    )


def test_publication_members_cover_full_graph_and_changes_expand():
    from copy import deepcopy
    from rime_core.overlay_publication import publication_view

    a = examples.synthetic()
    nodes = deepcopy(list(a.nodes.values()))
    source = next(n for n in nodes if "rime:Source" in n["@type"])
    source["rime:data"]["file_name"] = "different.mp4"
    b = RimeDocument.create(nodes, a.records)
    overlay = assert_lossless(a, b)
    publication = publication_view(overlay)
    assert sorted(k for n in publication["nodes"] for k in n["members"]) == sorted(
        n["id"] for n in overlay["nodes"]
    )
    assert sorted(
        [i for e in publication["edges"] for i in e["members"]] + publication["hidden_edges"]
    ) == list(range(len(overlay["edges"])))
    source_ids = {
        n["id"]
        for n in overlay["nodes"]
        if any("rime:Source" in raw["@type"] for raw in n["originals"].values())
    }
    assert all(
        len(n["members"]) == 1 for n in publication["nodes"] if source_ids & set(n["members"])
    )
    assert all(n["status"] == "changed" for n in overlay["nodes"] if n["id"] in source_ids)


def test_publication_expands_shared_source_when_usage_changes():
    from copy import deepcopy
    from rime_core.overlay_publication import publication_view

    a = examples.synthetic()
    nodes = deepcopy(list(a.nodes.values()))
    prod = next(n for n in nodes if "rime:AnnotationProduction" in n["@type"])
    prod["prov:qualifiedUsage"][0]["rime:data"] = {
        "mapping": {"status": "known", "offset_ms": 100, "method": "manual_offset"}
    }
    b = RimeDocument.create(nodes, a.records)
    overlay = assert_lossless(a, b)
    publication = publication_view(overlay)
    source = next(
        n
        for n in overlay["nodes"]
        if any("rime:Source" in raw["@type"] for raw in n["originals"].values())
    )
    assert any(
        n["members"] == [source["id"]] and n["id"] != "supporting" for n in publication["nodes"]
    )


def test_role_matching_precedes_uuid_for_correspondence():
    from copy import deepcopy

    a = examples.synthetic()
    raw = deepcopy(a.to_dict())
    # Swap unrelated entity UUIDs, updating every reference. Corresponding roles
    # must still pair observation to observation and definition to definition.
    obs = next(n["@id"] for n in raw["@graph"] if "rime:ObservationPeriod" in n["@type"])
    definition = next(n["@id"] for n in raw["@graph"] if "rime:CalculationDefinition" in n["@type"])
    text = (
        json.dumps(raw)
        .replace(obs, "__swap__")
        .replace(definition, obs)
        .replace("__swap__", definition)
    )
    b = RimeDocument.from_dict(json.loads(text))
    overlay = assert_lossless(a, b)
    for n in overlay["nodes"]:
        if set(n["originals"]) == {"a", "b"}:
            assert set(n["originals"]["a"]["@type"]) == set(n["originals"]["b"]["@type"])
