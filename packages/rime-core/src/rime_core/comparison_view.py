"""A traceable comparison-view model and Mermaid rendering of native record diffs."""

from __future__ import annotations

from hashlib import sha256
from html import escape
import json
import re

from .record_comparison import _links, record_nodes


def _short(value, limit=70):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _title(node):
    kind = next((t[5:] for t in node["@type"] if t.startswith("rime:")), "Agent")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", kind)


def _label(node, component, side):
    data = node["rime:data"]
    lines = [_title(node)]
    kinds = node["@type"]
    if "rime:Source" in kinds:
        lines.append(_short(data["file_name"], 42))
    elif "prov:Agent" in kinds:
        lines.append(_short(data["name"]))
    elif "rime:MeasurementResult" in kinds:
        value = data["value"]
        lines.append("undefined" if value is None else f"{value:.6g} {data['unit']}")
    elif "rime:AnnotationSet" in kinds:
        lines.append(f"{len(data['annotations'])} annotation entries")
    elif "rime:ObservationPeriod" in kinds:
        intervals = data["intervals"]
        lines.append(
            f"{intervals[0][0]:g}–{intervals[0][1]:g} ms"
            if len(intervals) == 1
            else f"{len(intervals)} observation intervals"
        )
    elif "rime:CalculationDefinition" in kinds:
        lines.extend(
            [
                data["operation"].replace("_", " "),
                f"{data['lane']} / {data['label'] if data['label'] is not None else 'all labels'}",
            ]
        )
    # A fixed rule, independent of the exemplar: show up to four changed scalar
    # activity attributes. Full paths and every omitted attribute stay in the view.
    if "prov:Activity" in kinds:
        changed = [
            a
            for a in component.get("attributes", [])
            if a["status"] in ("different", "only_a", "only_b")
            and side in a
            and a["path"].startswith("/rime:data/")
            and not isinstance(a[side], (list, dict))
        ]
        for attr in changed[:4]:
            parts = attr["path"].split("/")
            depth = 1
            while sum(a["path"].endswith("/" + "/".join(parts[-depth:])) for a in changed) > 1:
                depth += 1
            path = "/".join(parts[-depth:])
            lines.append(f"{path}: {_short(attr[side], 40)}")
        if len(changed) > 4:
            lines.append(f"+ {len(changed) - 4} changed scalar attributes")
    return lines


def build_comparison_view(diff, document_a, document_b):
    """Shared nodes require equal retained dependency closures, not just values.

    Common identity with consistent retained unknown markers may be drawn once, but
    remains explicitly unavailable. Equal distinct nodes are collapsed only when all
    their retained dependencies are also collapsible. All original side-specific
    edges are preserved, preventing a false recombination of A and B histories.
    """
    _, aa = record_nodes(document_a, diff["record_a"])
    _, bb = record_nodes(document_b, diff["record_b"])
    native = {"a": aa, "b": bb}
    components = {c["component"]: c for c in diff["components"]}
    index = {side: {} for side in ("a", "b")}
    for key, c in components.items():
        for side in ("a", "b"):
            if c.get("id_" + side):
                identity = c["id_" + side]
                if identity not in native[side] or identity in index[side]:
                    raise ValueError("Comparison does not map the supplied record closure.")
                index[side][identity] = key
    if any(set(index[side]) != set(native[side]) for side in native):
        raise ValueError("Incomplete comparison closure.")
    deps = {}
    for key, c in components.items():
        deps[key] = {r["target_component"] for r in c.get("relationships", [])}
    common, active = {}, set()

    def collapsible(key):
        if key in common:
            return common[key]
        if key in active:
            return False
        c = components[key]
        allowed = c["status"] == "equal" or (
            c["status"] == "unavailable" and c.get("identity_status") == "shared"
        )
        if not allowed or c.get("identity_conflict") or "id_a" not in c or "id_b" not in c:
            common[key] = False
            return False
        active.add(key)
        common[key] = all(collapsible(target) for target in sorted(deps[key]))
        active.remove(key)
        return common[key]

    for key in components:
        collapsible(key)

    nodes, display_ids = [], {}
    for key, c in sorted(components.items()):
        groups = [("a", "b")] if common[key] else [(s,) for s in ("a", "b") if "id_" + s in c]
        for sides in groups:
            side = sides[0]
            identity = c["id_" + side]
            raw = native[side][identity]
            view_id = "n" + sha256((key + ":" + "".join(sides)).encode()).hexdigest()[:12]
            for s in sides:
                display_ids[(s, c["id_" + s])] = view_id
            if common[key]:
                state = (
                    "shared_identity"
                    if c["identity_status"] == "shared"
                    else "equal_retained_basis"
                )
            elif c["status"] == "equal":
                state = "equal_content_different_lineage"
            else:
                state = c["status"]
            labels = _label(raw, c, side)
            labels.append(state.replace("_", " "))
            if c["status"] == "unavailable":
                labels.append("contains explicitly unavailable provenance")
            nodes.append(
                dict(
                    id=view_id,
                    component=key,
                    sides=list(sides),
                    original_ids={s: c["id_" + s] for s in sides},
                    local_status=c["status"],
                    display_state=state,
                    label_lines=labels,
                    comparison=c,
                    retained_nodes={s: native[s][c["id_" + s]] for s in sides},
                )
            )

    # Display arrows point from inputs/agents to operations and operations to
    # outputs. Stored PROV orientation and the actual owner/target IDs stay explicit.
    edges = {}
    for side, original in native.items():
        for owner, node in original.items():
            for relation, role, target, data in _links(node):
                source, destination = display_ids[(side, target)], display_ids[(side, owner)]
                key = (source, destination, relation, role)
                edge = edges.setdefault(
                    key,
                    dict(
                        source=source,
                        target=destination,
                        relation=relation,
                        role=role or None,
                        sides=[],
                        retained_relationships={},
                    ),
                )
                edge["sides"].append(side)
                edge["retained_relationships"][side] = dict(
                    owner=owner, target=target, attributes=data
                )
    return dict(
        view_version="1.0",
        nodes=nodes,
        edges=[edges[k] for k in sorted(edges)],
        result_nodes={s: display_ids[(s, diff["record_" + s])] for s in ("a", "b")},
        numerical_comparison=diff["numerical_comparison"],
        alignment_issues=diff["alignment_issues"],
    )


def to_mermaid(view, label_a="Record A", label_b="Record B", annotation_comparison=None):
    """Export the view, with optional separately supplied interval-analysis metrics."""

    def quote(text):
        return escape(str(text), quote=True).replace("\n", " ")

    lines = [
        "flowchart TB",
        "  %% Generated from the record comparison; no exemplar-specific topology.",
        "  %% Solid edges reverse stored PROV direction to show derivation flow.",
        "  %% Dashed summary links are comparisons, not provenance relations.",
    ]
    for group, title, sides in [
        ("common", "Shared / equal retained basis", ["a", "b"]),
        ("side_a", "A · " + label_a, ["a"]),
        ("side_b", "B · " + label_b, ["b"]),
    ]:
        group_nodes = [n for n in view["nodes"] if n["sides"] == sides]
        if not group_nodes:
            continue
        lines.append(f'  subgraph {group}["{quote(title)}"]')
        lines.append("    direction TB")
        for n in group_nodes:
            text = "<br/>".join(quote(x) for x in n["label_lines"])
            lines.extend(
                [
                    f"    %% {n['component']}: " + json.dumps(n["original_ids"]),
                    f'    {n["id"]}["{text}"]',
                ]
            )
        lines.append("  end")
    for edge in view["edges"]:
        label = {
            "prov:used": "used",
            "prov:wasGeneratedBy": "generated",
            "prov:wasAssociatedWith": "associated agent",
        }[edge["relation"]]
        if edge["role"]:
            label += ": " + edge["role"].removeprefix("rime:")
        lines.append(f'  {edge["source"]} -->|"{quote(label)}"| {edge["target"]}')
    num = view["numerical_comparison"]
    if num["status"] == "applicable":
        unit = "percentage points" if num["unit_a"] == "%" else num["unit_a"]
        summary = f"Absolute measurement difference = {num['absolute_difference']:.6g} {unit}"
    else:
        summary = "Numerical comparison not applicable: " + ", ".join(
            r["code"] for r in num["reasons"]
        )
    lines.extend(
        [
            '  subgraph comparison_summary["Comparison quantities — not provenance nodes"]',
            f'    measurement_difference["{quote(summary)}"]',
        ]
    )
    if annotation_comparison is not None:
        label = (
            f"Temporal disagreement = {annotation_comparison['temporal_disagreement_pct_observation']:.6g}%"
            f"<br/>IoU = {annotation_comparison['temporal_iou']:.6g}"
            "<br/>From the sensitivity analysis; separate from the RIME diff"
        )
        lines.append(f'    annotation_comparison["{label}"]')
    lines.append("  end")
    for node in sorted(set(view["result_nodes"].values())):
        lines.append(f"  {node} -.-> measurement_difference")
    lines.extend(
        [
            "  classDef common fill:#edf2ed,stroke:#526b52,color:#111;",
            "  classDef recordA fill:#e5edf8,stroke:#416797,color:#111;",
            "  classDef recordB fill:#f9eadf,stroke:#aa6e3c,color:#111;",
            "  classDef unknown stroke-dasharray:5 3;",
            "  classDef summary fill:#fff,stroke:#666,color:#111;",
        ]
    )
    for n in view["nodes"]:
        style = (
            "common" if len(n["sides"]) == 2 else "recordA" if n["sides"] == ["a"] else "recordB"
        )
        lines.append(f"  class {n['id']} {style};")
        if n["local_status"] == "unavailable":
            lines.append(f"  class {n['id']} unknown;")
    lines.append("  class measurement_difference summary;")
    if annotation_comparison is not None:
        lines.append("  class annotation_comparison summary;")
    return "\n".join(lines) + "\n"
