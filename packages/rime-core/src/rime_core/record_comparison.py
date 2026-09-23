"""Role-aware comparison of two native RIME record closures; no distance score."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json

from .exchange import RimeDocument

VERSION = "1.0"
MISSING = object()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _links(node):
    """Qualified uses carry roles; the corresponding direct used edge is redundant."""
    links = []
    if "prov:wasGeneratedBy" in node:
        links.append(("prov:wasGeneratedBy", "", node["prov:wasGeneratedBy"]["@id"], {}))
    for use in node.get("prov:qualifiedUsage", []):
        links.append(
            (
                "prov:used",
                use["prov:hadRole"]["@id"],
                use["prov:entity"]["@id"],
                use.get("rime:data", {}),
            )
        )
    for ref in node.get("prov:wasAssociatedWith", []):
        links.append(("prov:wasAssociatedWith", "", ref["@id"], {}))
    return sorted(links, key=_json)


def record_nodes(document: RimeDocument, record_id: str | None = None):
    """Return the selected root and exactly its reachable retained components."""
    if record_id is None:
        if len(document.records) != 1:
            raise ValueError("Select a measurement ID for a multi-record document.")
        record_id = document.records[0]
    if record_id not in document.records:
        raise ValueError("Measurement ID is not a record root in this document.")
    nodes, selected, pending = document.nodes, {}, [record_id]
    while pending:
        current = pending.pop()
        if current not in selected:
            selected[current] = nodes[current]
            pending.extend(target for _, _, target, _ in _links(nodes[current]))
    return record_id, selected


def _unavailable(value, path):
    # Null selectors (all labels), null calculation reasons, and undefined numerical
    # results are NOT unknown provenance. Never infer missing history from absence.
    if value is MISSING:
        return False
    key = path.rsplit("/", 1)[-1]
    unknown_fields = {
        "history",
        "original_annotation_history",
        "responsibility",
        "review_status",
        "media_identity",
        "original_author",
        "alignment_validation",
        "status",
    }
    if isinstance(value, str) and value == "unknown" and key in unknown_fields:
        return True
    return value is None and key in {"sha256", "original_author", "media_identity"}


def _normalize(value, correspondence):
    if isinstance(value, dict):
        return {
            key: (
                correspondence.get(item, item)
                if key in {"@id", "entity", "annotation_set"} and isinstance(item, str)
                else _normalize(item, correspondence)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item, correspondence) for item in value]
    return value


def _escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _equal(a, b):
    """JSON booleans are not numbers; integer/float representations may be equal."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _attributes(a, b, map_a, map_b, path=""):
    """JSON-pointer paths; identified annotations align by ID, never list position."""

    def entry(status):
        result = {
            "path": path or "/",
            "status": status,
            "present_a": a is not MISSING,
            "present_b": b is not MISSING,
        }
        if a is not MISSING:
            result["a"] = a
        if b is not MISSING:
            result["b"] = b
        if status == "unavailable":
            result["unavailable_in"] = [
                side for side, value in [("a", a), ("b", b)] if _unavailable(value, path)
            ]
        return [result]

    if _unavailable(a, path) or _unavailable(b, path):
        return entry("unavailable")
    if a is MISSING or b is MISSING:
        return entry("only_b" if a is MISSING else "only_a")
    if isinstance(a, dict) and isinstance(b, dict):
        if not a and not b:
            return entry("equal")
        return [
            item
            for key in sorted(set(a) | set(b))
            for item in _attributes(
                a.get(key, MISSING), b.get(key, MISSING), map_a, map_b, path + "/" + _escape(key)
            )
        ]
    if isinstance(a, list) and isinstance(b, list):
        # These arrays are unordered by contract; arbitrary numeric/config arrays
        # remain ordered atomic values. No guessed matching of unknown raters.
        if path.endswith("/annotations") and all(isinstance(x, dict) and "id" in x for x in a + b):
            aa, bb = {x["id"]: x for x in a}, {x["id"]: x for x in b}
            if not aa and not bb:
                return entry("equal")
            return [
                item
                for key in sorted(set(aa) | set(bb))
                for item in _attributes(
                    aa.get(key, MISSING),
                    bb.get(key, MISSING),
                    map_a,
                    map_b,
                    path + "/by_id/" + _escape(key),
                )
            ]
        if path.rsplit("/", 1)[-1] in {
            "contributors",
            "annotation_ids",
            "intervals",
            "decisions",
            "@type",
        }:

            def canonical(v, mapping):
                values = _normalize(v, mapping)
                if path.endswith("/decisions"):
                    values = deepcopy(values)
                    for decision in values:
                        for key in ("inputs", "outputs", "extent"):
                            if key in decision:
                                decision[key] = sorted(decision[key], key=_json)
                return sorted(values, key=_json)

            return entry(
                "equal" if _equal(canonical(a, map_a), canonical(b, map_b)) else "different"
            )
    aa, bb = _normalize(a, map_a), _normalize(b, map_b)
    if path.rsplit("/", 1)[-1] in {"entity", "annotation_set"}:
        aa = map_a.get(a, a) if isinstance(a, str) else a
        bb = map_b.get(b, b) if isinstance(b, str) else b
    return entry("equal" if _equal(aa, bb) else "different")


def _status(items):
    statuses = {item["status"] for item in items}
    if statuses & {"different", "only_a", "only_b"}:
        return "different"
    return "unavailable" if "unavailable" in statuses else "equal"


def compare_records(
    document_a: RimeDocument,
    document_b: RimeDocument,
    record_a: str | None = None,
    record_b: str | None = None,
):
    """Compare retained record components and result B minus A.

    Matching precedence: roots, corresponding parent relationships/input roles,
    then exact identities for otherwise unpaired retained ancestors. Repeated-role sources can be disambiguated by a
    unique non-null SHA-256. Unambiguous same-type role slots are paired; remaining
    ambiguity is reported and components retained separately. Equality never
    asserts common history when node identities differ.
    """
    root_a, nodes_a = record_nodes(document_a, record_a)
    root_b, nodes_b = record_nodes(document_b, record_b)
    pairs, reverse, bases = {}, {}, {}

    def pair(a, b, basis):
        if a not in pairs and b not in reverse:
            pairs[a], reverse[b], bases[a] = b, a, basis
            return True
        return False

    pair(root_a, root_b, "measurement_root")

    def groups(node):
        result = defaultdict(set)
        for relation, role, target, _ in _links(node):
            result[(relation, role)].add(target)
        return result

    changed = True
    while changed:
        changed = False
        for a, b in sorted(list(pairs.items())):
            ga, gb = groups(nodes_a[a]), groups(nodes_b[b])
            for slot in sorted(set(ga) & set(gb)):
                aa = sorted(x for x in ga[slot] if x not in pairs)
                bb = sorted(x for x in gb[slot] if x not in reverse)
                # Identity disambiguates repeated inputs within a corresponding role.
                for identity in sorted(set(aa) & set(bb)):
                    changed |= pair(identity, identity, "role_and_identity")
                aa = [x for x in aa if x not in pairs]
                bb = [x for x in bb if x not in reverse]
                # A digest can identify a source even when its filename changed.
                da, db = defaultdict(list), defaultdict(list)
                for ids, nodes, digests in ((aa, nodes_a, da), (bb, nodes_b, db)):
                    for x in ids:
                        node = nodes[x]
                        digest = node["rime:data"].get("sha256")
                        if "rime:Source" in node["@type"] and digest:
                            digests[digest].append(x)
                for digest in sorted(set(da) & set(db)):
                    if len(da[digest]) == len(db[digest]) == 1:
                        changed |= pair(da[digest][0], db[digest][0], "role_and_source_digest")
                aa = [x for x in aa if x not in pairs]
                bb = [x for x in bb if x not in reverse]
                if len(aa) == len(bb) == 1 and set(nodes_a[aa[0]]["@type"]) == set(
                    nodes_b[bb[0]]["@type"]
                ):
                    changed |= pair(aa[0], bb[0], "unique_relationship_role")
                else:
                    ta, tb = defaultdict(list), defaultdict(list)
                    for x in aa:
                        ta[tuple(sorted(nodes_a[x]["@type"]))].append(x)
                    for x in bb:
                        tb[tuple(sorted(nodes_b[x]["@type"]))].append(x)
                    for kind in sorted(set(ta) & set(tb)):
                        if len(ta[kind]) == len(tb[kind]) == 1:
                            changed |= pair(ta[kind][0], tb[kind][0], "unique_role_and_type")

        if not changed:
            # Inserting a review can move an existing ancestor to another depth.
            # Role matches take precedence; exact retained identities recover it.
            for identity in sorted(set(nodes_a) & set(nodes_b)):
                changed |= pair(identity, identity, "identity")

    # Canonical component tokens allow links to corresponding-but-distinct nodes
    # to compare equal, while retaining both actual node IDs in every component.
    map_a = {a: f"component:{i}" for i, a in enumerate(sorted(pairs))}
    map_b = {b: map_a[a] for a, b in pairs.items()}
    for side, nodes, mapping in [("a", nodes_a, map_a), ("b", nodes_b, map_b)]:
        for identity in sorted(nodes):
            mapping.setdefault(identity, side + ":" + identity)
    components, issues = [], []
    for a, b in sorted(pairs.items()):
        na, nb = nodes_a[a], nodes_b[b]
        attributes = _attributes(na["rime:data"], nb["rime:data"], map_a, map_b, "/rime:data")
        attributes += _attributes(na["@type"], nb["@type"], map_a, map_b, "/@type")
        relations = []
        la = {(r, role, map_a[t]): (t, data) for r, role, t, data in _links(na)}
        lb = {(r, role, map_b[t]): (t, data) for r, role, t, data in _links(nb)}
        for key in sorted(set(la) | set(lb)):
            va, vb = la.get(key), lb.get(key)
            attrs = _attributes(
                va[1] if va else MISSING, vb[1] if vb else MISSING, map_a, map_b, "/rime:data"
            )
            relations.append(
                {
                    "relation": key[0],
                    "role": key[1] or None,
                    "target_component": key[2],
                    "target_a": va[0] if va else None,
                    "target_b": vb[0] if vb else None,
                    "status": "only_b"
                    if va is None
                    else "only_a"
                    if vb is None
                    else _status(attrs),
                    "attributes": attrs,
                }
            )
        components.append(
            {
                "component": map_a[a],
                "id_a": a,
                "id_b": b,
                "types_a": na["@type"],
                "types_b": nb["@type"],
                "alignment_basis": bases[a],
                "identity_status": "shared" if a == b else "distinct",
                "identity_conflict": a == b and _status(attributes + relations) == "different",
                "status": _status(attributes + relations),
                "attributes": attributes,
                "relationships": relations,
            }
        )
        ga, gb = groups(na), groups(nb)
        for slot in sorted(set(ga) & set(gb)):
            aa = sorted(x for x in ga[slot] if x not in pairs)
            bb = sorted(x for x in gb[slot] if x not in reverse)
            if aa and bb:
                issues.append(
                    {
                        "parent_component": map_a[a],
                        "relation": slot[0],
                        "role": slot[1] or None,
                        "candidates_a": aa,
                        "candidates_b": bb,
                        "reason": "ambiguous_correspondence; no positional matching",
                    }
                )
    for side, nodes, matched, mapping in [
        ("a", nodes_a, pairs, map_a),
        ("b", nodes_b, reverse, map_b),
    ]:
        for identity in sorted(set(nodes) - set(matched)):
            components.append(
                {
                    "component": mapping[identity],
                    "id_" + side: identity,
                    "status": "only_" + side,
                    "node_" + side: nodes[identity],
                }
            )

    def calculation_inputs(root, nodes):
        calc = nodes[nodes[root]["prov:wasGeneratedBy"]["@id"]]
        return {
            u["prov:hadRole"]["@id"]: nodes[u["prov:entity"]["@id"]]
            for u in calc["prov:qualifiedUsage"]
        }

    ia, ib = calculation_inputs(root_a, nodes_a), calculation_inputs(root_b, nodes_b)
    definition_a = ia["rime:definition"]["rime:data"]
    definition_b = ib["rime:definition"]["rime:data"]
    result_a, result_b = nodes_a[root_a]["rime:data"], nodes_b[root_b]["rime:data"]
    definition_diff = _attributes(definition_a, definition_b, {}, {}, "/definition")
    reasons = [
        {
            "code": "measurement_definition_differs",
            "path": item["path"],
            "a": item.get("a"),
            "b": item.get("b"),
        }
        for item in definition_diff
        if item["status"] != "equal"
    ]
    if result_a["unit"] != result_b["unit"]:
        reasons.append({"code": "incompatible_units", "a": result_a["unit"], "b": result_b["unit"]})
    if result_a["value"] is None or result_b["value"] is None:
        reasons.append(
            {
                "code": "undefined_measurement_value",
                "a": result_a["reason"],
                "b": result_b["reason"],
            }
        )
    signed = None if reasons else result_b["value"] - result_a["value"]
    return {
        "comparison_version": VERSION,
        "record_a": root_a,
        "record_b": root_b,
        "components": components,
        "alignment_issues": issues,
        "numerical_comparison": {
            "status": "not_applicable" if reasons else "applicable",
            "reasons": reasons,
            "value_a": result_a["value"],
            "value_b": result_b["value"],
            "unit_a": result_a["unit"],
            "unit_b": result_b["unit"],
            "signed_difference_b_minus_a": signed,
            "absolute_difference": None if signed is None else abs(signed),
        },
    }


def main():
    import argparse
    from pathlib import Path
    from .exchange import read_document

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_a", type=Path)
    parser.add_argument("file_b", type=Path)
    parser.add_argument("--record-a", help="Measurement root ID; required for multi-record files")
    parser.add_argument("--record-b", help="Measurement root ID; required for multi-record files")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare_records(
        read_document(args.file_a), read_document(args.file_b), args.record_a, args.record_b
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
