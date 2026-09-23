"""Lossless, layout-independent overlay of two selected RIME record closures.

A merged display node is an equivalence group, never a new provenance entity.
Every traversal must retain its A/B membership through merges and forks.
"""

from copy import deepcopy
from hashlib import sha256
from html import escape
import json

from .comparison_view import _label
from .record_comparison import _links, _normalize, compare_records, record_nodes


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _acyclic(nodes, edges):
    successors = {n["id"]: set() for n in nodes}
    indegree = dict.fromkeys(successors, 0)
    for e in edges:
        if e["target"] not in successors[e["source"]]:
            successors[e["source"]].add(e["target"])
            indegree[e["target"]] += 1
    ready = [k for k, v in indegree.items() if v == 0]
    count = 0
    while ready:
        key = ready.pop()
        count += 1
        for target in successors[key]:
            indegree[target] -= 1
            if not indegree[target]:
                ready.append(target)
    return count == len(nodes)


def overlay_records(document_a, document_b, record_a=None, record_b=None):
    """Compare and overlay complete closures, without role-specific layout rules.

    Entities and Agents match on local types and data. Activities additionally
    require equal directly used inputs, including usage roles and attributes.
    Explicitly unknown
    contents merge only for the same identity and identical recorded local payload.
    Identity conflicts stay separate. A quotient cycle disables collapse rather
    than displaying a cyclic provenance DAG. Originals are retained losslessly.
    """
    diff = compare_records(document_a, document_b, record_a, record_b)
    native = {
        s: record_nodes(d, diff["record_" + s])[1]
        for s, d in [("a", document_a), ("b", document_b)]
    }
    components = sorted(diff["components"], key=lambda c: c["component"])
    correspondence = {
        s: {c["id_" + s]: c["component"] for c in components if "id_" + s in c} for s in native
    }
    collapsible = set()
    statuses = {}
    for c in components:
        if not all("id_" + s in c for s in native):
            statuses[c["component"]] = "A_only" if "id_a" in c else "B_only"
            continue
        states = {a["status"] for a in c["attributes"]}
        statuses[c["component"]] = (
            "changed"
            if c.get("identity_conflict") or states & {"different", "only_a", "only_b"}
            else "unavailable"
            if "unavailable" in states
            else "shared"
            if c["id_a"] == c["id_b"]
            else "equal"
        )
        if c.get("identity_conflict"):
            continue
        states = {a["status"] for a in c["attributes"]}
        equal = states <= {"equal"}
        if states <= {"equal", "unavailable"} and c["id_a"] == c["id_b"]:
            a, b = [native[s][c["id_" + s]] for s in native]
            equal = _key([a["@type"], a["rime:data"]]) == _key([b["@type"], b["rime:data"]])
        if equal:
            collapsible.add(c["component"])

    # Input Entities may have equal contents despite different earlier histories.
    # Preserve that convergence, but never collapse executions using unequal inputs.
    def input_signature(component, side):
        signature = []
        for relation, role, target, attrs in _links(native[side][component["id_" + side]]):
            if relation != "prov:used":
                continue
            target_component = correspondence[side][target]
            token = (
                [target_component] if target_component in collapsible else [target_component, side]
            )
            signature.append([role, token, _normalize(attrs, correspondence[side])])
        return sorted(signature, key=_key)

    for c in components:
        if (
            c["component"] in collapsible
            and "prov:Activity" in native["a"][c["id_a"]]["@type"]
            and input_signature(c, "a") != input_signature(c, "b")
        ):
            collapsible.remove(c["component"])
            statuses[c["component"]] = "changed"

    def build(merge):
        nodes, mapping = [], {}
        for c in components:
            groups = (
                [("a", "b")]
                if c["component"] in merge
                else [(s,) for s in native if "id_" + s in c]
            )
            for sides in groups:
                identity = "n" + sha256((c["component"] + "".join(sides)).encode()).hexdigest()[:16]
                for s in sides:
                    mapping[s, c["id_" + s]] = identity
                nodes.append(
                    dict(
                        id=identity,
                        component=c["component"],
                        status=statuses[c["component"]],
                        sides=list(sides),
                        comparison=deepcopy(c),
                        unavailable=any(
                            a["status"] == "unavailable" for a in c.get("attributes", [])
                        ),
                        originals={s: deepcopy(native[s][c["id_" + s]]) for s in sides},
                    )
                )
        edges = {}
        for s, originals in native.items():
            for owner, node in sorted(originals.items()):
                # Preserve repeated qualified relations, including their multiplicity.
                occurrences = {}
                for relation, role, target, attrs in sorted(_links(node), key=_key):
                    signature = _key(
                        [
                            mapping[s, owner],
                            mapping[s, target],
                            relation,
                            role,
                            _normalize(attrs, correspondence[s]),
                        ]
                    )
                    ordinal = occurrences.get(signature, 0)
                    occurrences[signature] = ordinal + 1
                    key = (signature, ordinal)
                    edge = edges.setdefault(
                        key,
                        dict(
                            source=mapping[s, owner],
                            target=mapping[s, target],
                            relation=relation,
                            role=role,
                            sides=[],
                            originals={},
                        ),
                    )
                    edge["sides"].append(s)
                    edge["originals"][s] = dict(
                        owner=owner, target=target, attributes=deepcopy(attrs)
                    )
        return nodes, [edges[k] for k in sorted(edges)], mapping

    nodes, edges, mapping = build(collapsible)
    warnings = []
    if not _acyclic(nodes, edges):
        warnings.append("Collapse disabled: the aligned quotient would introduce a cycle.")
        nodes, edges, mapping = build(set())
    return dict(
        overlay_version="1.1",
        nodes=nodes,
        edges=edges,
        roots={s: mapping[s, diff["record_" + s]] for s in native},
        original_roots={s: diff["record_" + s] for s in native},
        numerical_comparison=deepcopy(diff["numerical_comparison"]),
        alignment_issues=deepcopy(diff["alignment_issues"]),
        warnings=warnings,
    )


def recover_record(overlay, side):
    """Recover the selected record's original root and complete native node payloads.

    Document-level packaging and unrelated measurement roots are outside this scope.
    """
    if side not in ("a", "b"):
        raise ValueError("side must be a or b")
    return overlay["original_roots"][side], {
        n["originals"][side]["@id"]: deepcopy(n["originals"][side])
        for n in overlay["nodes"]
        if side in n["sides"]
    }


def to_mermaid(overlay):
    """Full graph with automatic Mermaid layout; no scientific roles are hidden."""
    lines = ["flowchart TB", "  %% Follow A/B membership consistently through merged nodes."]
    for n in overlay["nodes"]:
        side = n["sides"][0]
        raw = n["originals"][side]
        labels = _label(raw, n["comparison"], side)
        if n["status"] == "equal":
            labels.append("A = B")
        if len(n["sides"]) == 1:
            labels.insert(0, "Record " + side.upper())
        if n["unavailable"]:
            labels.append("Provenance partly unavailable")
        label = "<br/>".join(escape(str(x), quote=True) for x in labels)
        kind = (
            "activity"
            if "prov:Activity" in raw["@type"]
            else ("agent" if "prov:Agent" in raw["@type"] else "entity")
        )
        lines += [f'  {n["id"]}["{label}"]', f"  class {n['id']} {kind};"]
    for e in overlay["edges"]:
        label = e["relation"].removeprefix("prov:")
        if e["role"]:
            label += " · " + e["role"].removeprefix("rime:")
        if len(e["sides"]) == 1:
            label = e["sides"][0].upper() + " · " + label
        lines.append(f'  {e["source"]} -->|"{escape(label, quote=True)}"| {e["target"]}')
    lines += [
        "  classDef entity fill:#DBE8F4,stroke:#888,color:#111;",
        "  classDef activity fill:#F2D3CF,stroke:#888,color:#111;",
        "  classDef agent fill:#DCF0D4,stroke:#888,color:#111;",
    ]
    return "\n".join(lines) + "\n"
