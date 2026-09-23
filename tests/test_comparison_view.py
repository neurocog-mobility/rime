"""The comparison view preserves history even where downstream values are equal."""

import importlib.util
from pathlib import Path

import pytest

from rime_core.comparison_view import build_comparison_view, to_mermaid
from rime_core.record_comparison import _links, compare_records, record_nodes

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "view_examples", ROOT / "examples/measurement-record/create_example.py"
)
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


@pytest.mark.parametrize("review", [False, True])
def test_identical_records_share_nodes_with_unknown_markers_preserved(review):
    doc = examples.synthetic(review)
    view = build_comparison_view(compare_records(doc, doc), doc, doc)
    assert len(view["nodes"]) == len(doc.nodes)
    assert all(n["sides"] == ["a", "b"] for n in view["nodes"])
    assert any(
        n["local_status"] == "unavailable"
        and "contains explicitly unavailable provenance" in n["label_lines"]
        for n in view["nodes"]
    )


@pytest.mark.parametrize(
    "name", ["different_records_similar_result", "limited_record_difference_divergent_result"]
)
def test_exemplars_preserve_all_original_edges_without_crossing_branches(name):
    category = "annotation_output" if name == "different_records_similar_result" else "neither"
    a, b = examples.convergence_pair(category, operation="percentage_coverage")
    view = build_comparison_view(compare_records(a, b), a, b)
    for side, doc in [("a", a), ("b", b)]:
        root, nodes = record_nodes(doc)
        expected = {
            (owner, target, relation, role or None)
            for owner, node in nodes.items()
            for relation, role, target, _ in _links(node)
        }
        actual = {
            (
                edge["retained_relationships"][side]["owner"],
                edge["retained_relationships"][side]["target"],
                edge["relation"],
                edge["role"],
            )
            for edge in view["edges"]
            if side in edge["sides"]
        }
        assert actual == expected
        assert any(
            n["id"] == view["result_nodes"][side] and n["original_ids"][side] == root
            for n in view["nodes"]
        )
    if name == "different_records_similar_result":
        assert view["result_nodes"]["a"] != view["result_nodes"]["b"]
        outputs = [n for n in view["nodes"] if n["id"] in view["result_nodes"].values()]
        assert all(n["display_state"] == "equal_content_different_lineage" for n in outputs)
    for edge in view["edges"]:
        for side in edge["sides"]:
            assert all(
                side in n["sides"]
                for n in view["nodes"]
                if n["id"] in (edge["source"], edge["target"])
            )


def test_text_and_mermaid_are_deterministic_and_escape_labels():
    doc = examples.synthetic()
    diff = compare_records(doc, doc)
    view = build_comparison_view(diff, doc, doc)
    assert to_mermaid(view) == to_mermaid(view)
    text = to_mermaid(view, 'a"<script>', "b")
    assert "<script>" not in text
    assert "exemplar_execution_field_count" not in text
    assert "annotation_comparison[" not in text
    changed_order = dict(diff, components=list(reversed(diff["components"])))
    assert build_comparison_view(changed_order, doc, doc) == view


def test_wrong_document_is_rejected():
    a = examples.synthetic()
    b = examples.synthetic(True)
    with pytest.raises(ValueError):
        build_comparison_view(compare_records(a, a), a, b)
