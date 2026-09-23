"""Read-only inspection of native records; no media or workspace state.

The display may group equal measurement values and hide a redundant scope edge.
Original nodes, attributes and relations remain available in the returned graph.
"""

from copy import deepcopy
import math

from .exchange import calculate
from .record_comparison import _links, record_nodes
from .record_overlay import overlay_records

TITLES = {
    "Source": "Source reference",
    "AnnotationSet": "Annotation set",
    "ObservationPeriod": "Observation period",
    "CalculationDefinition": "Calculation definition",
    "MeasurementResult": "Measurement result",
    "AnnotationProduction": "Annotation production",
    "AnnotationReview": "Annotation review",
    "MeasurementCalculation": "Measurement calculation",
    "Agent": "Agent",
}


def node_title(node):
    return TITLES[next((t[5:] for t in node["@type"] if t.startswith("rime:")), "Agent")]


def format_result(data):
    if data["value"] is None:
        return "Undefined"
    number = format(data["value"], ".8g")
    return number + ("%" if data["unit"] == "%" else " " + data["unit"])


def calculation_basis(document, root):
    nodes = document.nodes
    result = nodes[root]
    activity = nodes[result["prov:wasGeneratedBy"]["@id"]]
    inputs = {
        u["prov:hadRole"]["@id"][5:]: nodes[u["prov:entity"]["@id"]]
        for u in activity["prov:qualifiedUsage"]
    }
    return result, inputs


def measurement_summaries(document):
    summaries = []
    for root in document.records:
        result, inputs = calculation_basis(document, root)
        definition = inputs["definition"]["rime:data"]
        label = definition["label"] if definition["label"] is not None else "all labels"
        title = f"{definition['operation'].replace('_', ' ').capitalize()} · {definition['lane']} / {label}"
        summaries.append(
            dict(
                root=root,
                title=title,
                value=format_result(result["rime:data"]),
                observation=inputs["observation"]["rime:data"]["intervals"],
            )
        )
    return summaries


def verify_record(document, root):
    result, inputs = calculation_basis(document, root)
    calculated = calculate(
        inputs["annotations"]["rime:data"]["annotations"],
        inputs["observation"]["rime:data"]["intervals"],
        inputs["definition"]["rime:data"],
    )
    stored = result["rime:data"]

    def equal(a, b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
        return a == b

    return dict(
        matches=all(equal(stored[k], v) for k, v in calculated.items()),
        stored=deepcopy(stored),
        recalculated=calculated,
    )


def measurement_value_overlay(full):
    """Group equal values under equal definitions, preserving ancillary audit differences."""
    view = deepcopy(full)
    numeric = view["numerical_comparison"]
    ra, rb = view["roots"]["a"], view["roots"]["b"]
    if numeric["status"] == "applicable" and numeric["absolute_difference"] == 0 and ra != rb:
        a = next(n for n in view["nodes"] if n["id"] == ra)
        b = next(n for n in view["nodes"] if n["id"] == rb)
        a["originals"].update(b["originals"])
        a["sides"] = ["a", "b"]
        a["status"] = "equal"
        a["display_equivalence"] = "measurement_value_and_definition"
        a["unavailable"] = a["unavailable"] or b["unavailable"]
        view["nodes"] = [n for n in view["nodes"] if n["id"] != rb]
        for edge in view["edges"]:
            for key in ("source", "target"):
                if edge[key] == rb:
                    edge[key] = ra
        view["roots"]["b"] = ra
    return view


def _mark_scope_edges(graph):
    """Same per-record display rule as the manuscript; never combine A and B paths."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    outgoing = {}
    for e in graph["edges"]:
        outgoing.setdefault(e["source"], []).append(e)
    for edge in graph["edges"]:
        if edge["role"] != "rime:scope_annotations":
            continue
        covered = []
        for side in edge["sides"]:
            source = nodes[edge["source"]]["originals"][side]
            if "rime:MeasurementCalculation" not in source["@type"]:
                covered.append(False)
                continue
            pending = [
                (e["target"], False)
                for e in outgoing.get(edge["source"], [])
                if e["role"] == "rime:annotations" and side in e["sides"]
            ]
            seen, found = set(), False
            while pending:
                key, production = pending.pop()
                if (key, production) in seen:
                    continue
                seen.add((key, production))
                production |= "rime:AnnotationProduction" in nodes[key]["originals"][side]["@type"]
                if key == edge["target"] and production:
                    found = True
                    break
                pending.extend(
                    (e["target"], production)
                    for e in outgoing.get(key, [])
                    if side in e["sides"] and e["relation"] in ("prov:used", "prov:wasGeneratedBy")
                )
            covered.append(found)
        if all(covered):
            edge["display_omitted"] = "Scope also reached through annotation production"


def inspection_graph(document, root, other=None, other_root=None):
    if other is not None:
        graph = measurement_value_overlay(overlay_records(document, other, root, other_root))
        graph["comparison"] = True
    else:
        root, native = record_nodes(document, root)
        nodes, edges = [], []
        for key, node in native.items():
            nodes.append(
                dict(id=key, originals={"a": node}, sides=["a"], status="single", unavailable=False)
            )
            for relation, role, target, attrs in _links(node):
                edges.append(
                    dict(
                        source=key,
                        target=target,
                        relation=relation,
                        role=role,
                        sides=["a"],
                        originals={"a": dict(owner=key, target=target, attributes=attrs)},
                    )
                )
        graph = dict(
            nodes=nodes,
            edges=edges,
            roots={"a": root},
            comparison=False,
            warnings=[],
            alignment_issues=[],
            numerical_comparison=None,
        )
    _mark_scope_edges(graph)
    return graph
