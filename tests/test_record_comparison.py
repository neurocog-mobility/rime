"""Comparison semantics, including order, ambiguity, missing history and units."""

import importlib.util
from pathlib import Path

import pytest

from rime_core.exchange import RimeDocument, calculate, entity, activity
from rime_core.record_comparison import compare_records

spec = importlib.util.spec_from_file_location(
    "comparison_examples",
    Path(__file__).resolve().parents[1] / "examples/measurement-record/create_example.py",
)
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


def fixture():
    return examples.synthetic(True)


def node(raw, kind):
    return next(n for n in raw["@graph"] if "rime:" + kind in n["@type"])


def changed(raw):
    """Recalculate a modified fixture so malformed documents never reach comparison."""
    graph = {n["@id"]: n for n in raw["@graph"]}
    for result in raw["rime:records"]:
        r = graph[result["@id"]]
        calc = graph[r["prov:wasGeneratedBy"]["@id"]]
        inputs = {
            u["prov:hadRole"]["@id"]: graph[u["prov:entity"]["@id"]]["rime:data"]
            for u in calc["prov:qualifiedUsage"]
        }
        r["rime:data"] = calculate(
            inputs["rime:annotations"]["annotations"],
            inputs["rime:observation"]["intervals"],
            inputs["rime:definition"],
        )
    return RimeDocument.from_dict(raw)


def attributes(diff):
    return [a for c in diff["components"] for a in c.get("attributes", [])]


def test_identical_and_serialization_order_invariance():
    a = fixture()
    raw = a.to_dict()
    raw["@graph"].reverse()
    for n in raw["@graph"]:
        for key in ("prov:used", "prov:qualifiedUsage", "prov:wasAssociatedWith"):
            if key in n:
                n[key].reverse()
        for key in ("annotations", "decisions", "contributors"):
            if key in n["rime:data"]:
                n["rime:data"][key].reverse()
        n["@type"].reverse()
    assert all(
        c["status"] in ("equal", "unavailable")
        for c in compare_records(a, RimeDocument.from_dict(raw))["components"]
    )
    diff = compare_records(a, a)
    assert not diff["alignment_issues"]
    assert diff["numerical_comparison"]["signed_difference_b_minus_a"] == 0
    assert all(x["status"] in ("equal", "unavailable") for x in diff["components"])


def test_distinct_ids_do_not_create_content_differences_or_claim_shared_identity():
    a = fixture()
    raw = a.to_dict()
    mapping = {n["@id"]: n["@id"] + ":copy" for n in raw["@graph"]}

    def rename(v):
        if isinstance(v, dict):
            return {k: rename(x) for k, x in v.items()}
        if isinstance(v, list):
            return [rename(x) for x in v]
        return mapping.get(v, v) if isinstance(v, str) else v

    b = RimeDocument.from_dict(rename(raw))
    diff = compare_records(a, b)
    assert not diff["alignment_issues"]
    assert len(diff["components"]) == len(a.nodes)
    assert all(c["status"] in ("equal", "unavailable") for c in diff["components"])
    assert all(c["identity_status"] == "distinct" for c in diff["components"])


def test_qualified_mapping_changes_are_not_lost():
    a = fixture()
    raw = a.to_dict()
    node(raw, "AnnotationProduction")["prov:qualifiedUsage"][0]["rime:data"] = {
        "mapping": {"status": "known", "method": "manual_offset", "offset_ms": 100}
    }
    diff = compare_records(a, RimeDocument.from_dict(raw))
    rels = [r for c in diff["components"] for r in c.get("relationships", [])]
    assert any(r["status"] == "different" for r in rels)
    assert any(
        at["status"] == "different" and "mapping" in at["path"] for r in rels for at in r["attributes"]
    )


def test_numerical_sign_and_same_definition_different_observation():
    a = fixture()
    raw = a.to_dict()
    node(raw, "ObservationPeriod")["rime:data"]["intervals"] = [[0, 30000]]
    b = changed(raw)
    ab, ba = compare_records(a, b), compare_records(b, a)
    assert ab["numerical_comparison"]["signed_difference_b_minus_a"] == 10
    assert ba["numerical_comparison"]["signed_difference_b_minus_a"] == -10
    assert ab["numerical_comparison"]["absolute_difference"] == 10


@pytest.mark.parametrize("change", ["operation", "selector", "empty"])
def test_numerical_inapplicability(change):
    a = fixture()
    raw = a.to_dict()
    if change == "operation":
        node(raw, "CalculationDefinition")["rime:data"].update(operation="count", unit="count")
    elif change == "selector":
        node(raw, "CalculationDefinition")["rime:data"]["label"] = "other"
    else:
        node(raw, "ObservationPeriod")["rime:data"]["intervals"] = []
    diff = compare_records(a, changed(raw))["numerical_comparison"]
    assert diff["status"] == "not_applicable"
    assert diff["signed_difference_b_minus_a"] is None
    assert diff["reasons"]


def test_unknown_is_not_equal_and_null_selector_is_not_unknown():
    a = fixture()
    raw = a.to_dict()
    node(raw, "CalculationDefinition")["rime:data"]["label"] = None
    b = changed(raw)
    diff = compare_records(b, b)
    assert any(
        x["path"].endswith("/sha256") and x["status"] == "unavailable" for x in attributes(diff)
    )
    assert any(
        x["path"].endswith("/label") and x["a"] is None and x["status"] == "equal"
        for x in attributes(diff)
    )
    assert diff["numerical_comparison"]["status"] == "applicable"


def test_unknown_history_and_only_side_components():
    a = fixture()
    raw = a.to_dict()
    reviewed = next(n for n in raw["@graph"] if n["@id"] == examples.identity("reviewed"))
    reviewed.pop("prov:wasGeneratedBy")
    reviewed["rime:data"]["history"] = "unknown"
    # Keep only the new root closure, dropping now-unrelated review/input/source.
    from rime_core.record_comparison import _links

    nodes = {n["@id"]: n for n in raw["@graph"]}
    keep = set()
    todo = [raw["rime:records"][0]["@id"]]
    while todo:
        x = todo.pop()
        if x not in keep:
            keep.add(x)
            todo.extend(t for _, _, t, _ in _links(nodes[x]))
    raw["@graph"] = [nodes[x] for x in sorted(keep)]
    diff = compare_records(a, RimeDocument.from_dict(raw))
    assert any(c["status"] == "only_a" for c in diff["components"])
    assert any(
        x["path"].endswith("/history")
        and x["status"] == "unavailable"
        and x["unavailable_in"] == ["b"]
        for x in attributes(diff)
    )


def test_repeated_role_ambiguity_does_not_guess_by_position():
    def make(suffix):
        raw = examples.synthetic().to_dict()
        prod = node(raw, "AnnotationProduction")
        src = node(raw, "Source")
        raw["@graph"].remove(src)
        sources = [
            entity(
                "urn:source:" + suffix + str(i), "Source", {"source_kind":"recording","modality":"video","file_name": "same.mp4", "sha256": None}
            )
            for i in range(2)
        ]
        raw["@graph"].extend(sources)
        replacement = activity(
            prod["@id"],
            "AnnotationProduction",
            [("recording", n["@id"], {"mapping": {"status": "unknown"}}) for n in sources],
            prod["rime:data"],
            [r["@id"] for r in prod["prov:wasAssociatedWith"]],
        )
        raw["@graph"][raw["@graph"].index(prod)] = replacement
        return RimeDocument.from_dict(raw)

    diff = compare_records(make("a"), make("b"))
    assert len(diff["alignment_issues"]) == 1
    assert sum(c["status"] == "only_a" for c in diff["components"]) == 2
    assert sum(c["status"] == "only_b" for c in diff["components"]) == 2


def test_multi_record_requires_root_and_excludes_other_measurements():
    a = examples.imported()
    with pytest.raises(ValueError, match="Select a measurement"):
        compare_records(a, a)
    diff = compare_records(a, a, a.records[0], a.records[0])
    assert not any(c.get("id_a") in a.records[1:] for c in diff["components"])


def test_annotation_order_and_identity_not_episode_matching():
    a = examples.synthetic()
    raw = a.to_dict()
    node(raw, "AnnotationSet")["rime:data"]["annotations"].reverse()
    diff = compare_records(a, changed(raw))
    assert all(c["status"] in ("equal", "unavailable") for c in diff["components"])
    raw = a.to_dict()
    node(raw, "AnnotationSet")["rime:data"]["annotations"][0]["id"] = "new-local-id"
    diff = compare_records(a, changed(raw))
    assert any(x["status"] == "only_a" and "/by_id/" in x["path"] for x in attributes(diff))
    assert any(x["status"] == "only_b" and "/by_id/" in x["path"] for x in attributes(diff))
    assert diff["numerical_comparison"]["absolute_difference"] == 0


def test_metadata_boolean_is_not_numeric_one():
    a = fixture()
    raw_a, raw_b = a.to_dict(), a.to_dict()
    node(raw_a, "AnnotationProduction")["rime:data"].setdefault("metadata", {})["setting"] = True
    node(raw_b, "AnnotationProduction")["rime:data"].setdefault("metadata", {})["setting"] = 1
    diff = compare_records(RimeDocument.from_dict(raw_a), RimeDocument.from_dict(raw_b))
    assert any(
        x["path"].endswith("/setting") and x["status"] == "different" for x in attributes(diff)
    )


def test_repeated_role_sources_can_align_by_digest_without_shared_node_identity():
    def make(suffix):
        raw = examples.synthetic().to_dict()
        prod = node(raw, "AnnotationProduction")
        src = node(raw, "Source")
        raw["@graph"].remove(src)
        sources = [
            entity(
                "urn:source:" + suffix + str(i),
                "Source",
                {"source_kind":"recording","modality":"video","file_name": suffix + str(i) + ".mp4", "sha256": str(i) * 64},
            )
            for i in range(2)
        ]
        raw["@graph"].extend(sources)
        replacement = activity(
            prod["@id"],
            "AnnotationProduction",
            [("recording", n["@id"], {"mapping": {"status": "unknown"}}) for n in reversed(sources)],
            prod["rime:data"],
            [r["@id"] for r in prod["prov:wasAssociatedWith"]],
        )
        raw["@graph"][raw["@graph"].index(prod)] = replacement
        return RimeDocument.from_dict(raw)

    diff = compare_records(make("a"), make("b"))
    assert not diff["alignment_issues"]
    matched = [
        c for c in diff["components"] if c.get("alignment_basis") == "role_and_source_digest"
    ]
    assert len(matched) == 2
    assert all(c["identity_status"] == "distinct" for c in matched)
    assert all(
        any(
            a["path"].endswith("/file_name") and a["status"] == "different" for a in c["attributes"]
        )
        for c in matched
    )
