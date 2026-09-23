"""Closed RIME 1.1 activity/input/output/responsibility matrix."""

# Values: required entity type, optional Source subtype, minimum and maximum count.
INPUTS = {
    ("AnnotationProduction", "manual"): {"recording": ("Source", "recording", 1, None)},
    ("AnnotationProduction", "computational"): {
        "recording": ("Source", "recording", 1, None),
        "model_package": ("Source", "model_package", 1, 1),
        "scope_annotations": ("AnnotationSet", None, 0, 1),
    },
    ("AnnotationProduction", "import"): {"import_file": ("Source", "annotation_file", 1, 1)},
    ("AnnotationReview", "verification"): {
        "annotation_input": ("AnnotationSet", None, 1, None),
        "recording": ("Source", "recording", 0, None),
    },
    ("AnnotationReview", "adjudication"): {
        "annotation_input": ("AnnotationSet", None, 2, None),
        "recording": ("Source", "recording", 0, None),
    },
    ("MeasurementCalculation", None): {
        "annotations": ("AnnotationSet", None, 1, 1),
        "observation": ("ObservationPeriod", None, 1, 1),
        "definition": ("CalculationDefinition", None, 1, 1),
        "scope_annotations": ("AnnotationSet", None, 0, 1),
    },
}


def validate_connections(nodes, uses, require):
    outputs = {}
    for n in nodes.values():
        ref = n.get("prov:wasGeneratedBy")
        if ref:
            outputs.setdefault(ref["@id"], []).append(n)
        if "rime:Source" in n["@type"]:
            data = n["rime:data"]
            if data["source_kind"] == "model_package":
                names = [m["file_name"] for m in data["manifest"]]
                require(len(names) == len(set(names)), "Duplicate package manifest name.")
                require(
                    all(
                        name and "/" not in name and "\\" not in name and name not in (".", "..")
                        for name in names
                    ),
                    "Package manifest requires flat relative filenames.",
                )
            else:
                require(
                    not any(k in data for k in ("manifest", "scope", "digest_scope")),
                    "Package attributes require a model package.",
                )
            require(
                data["source_kind"] == "recording" or "modality" not in data,
                "Modality belongs to a recording.",
            )
    for identity, inputs in uses.items():
        node = nodes[identity]
        kind = next(t[5:] for t in node["@type"] if t.startswith("rime:"))
        data = node["rime:data"]
        method = data.get("method")
        require((kind, method) in INPUTS, "Unknown activity method.")
        contract = INPUTS[kind, method]
        require(
            all(role in contract for role, _ in inputs),
            "Input role not permitted for activity/method.",
        )
        for role, (expected, subtype, lower, upper) in contract.items():
            matching = [nodes[t] for r, t in inputs if r == role]
            require(
                len(matching) >= lower and (upper is None or len(matching) <= upper),
                "Invalid input cardinality: " + role,
            )
            require(
                all(
                    "rime:" + expected in n["@type"]
                    and (subtype is None or n["rime:data"]["source_kind"] == subtype)
                    for n in matching
                ),
                "Wrong entity kind for input: " + role,
            )
        generated = outputs.get(identity, [])
        expected_output = (
            "MeasurementResult" if kind == "MeasurementCalculation" else "AnnotationSet"
        )
        require(
            len(generated) == 1 and "rime:" + expected_output in generated[0]["@type"],
            "Activity requires exactly one " + expected_output + " output.",
        )
        agents = [nodes[r["@id"]]["rime:data"]["kind"] for r in node["prov:wasAssociatedWith"]]
        require(
            len(node["prov:wasAssociatedWith"])
            == len({r["@id"] for r in node["prov:wasAssociatedWith"]}),
            "Duplicate responsible agent.",
        )
        if kind == "MeasurementCalculation" or method == "import":
            require(
                not agents and "responsibility" not in data,
                "Calculation/import has no Agent association or unknown-agent placeholder.",
            )
        elif method == "computational":
            require(
                agents == ["model"] and "responsibility" not in data,
                "Computational production requires one model Agent.",
            )
        else:
            require(
                all(a in ("person", "group") for a in agents),
                "Human production/review requires person/group Agents.",
            )
            require(
                (bool(agents) and "responsibility" not in data)
                or (not agents and data.get("responsibility") == "unknown"),
                "Record known agents or explicitly unknown responsibility, not both.",
            )
        if kind == "AnnotationProduction":
            require(
                ("execution_specification" in data) == (method == "computational"),
                "Effective execution specification belongs to computational production and is required.",
            )
            require(
                method == "computational" or "configuration_id" not in data,
                "Configuration ID belongs to computational production.",
            )
        # Recording usage has an explicit relation-specific temporal mapping.
        for usage in node["prov:qualifiedUsage"]:
            role = usage["prov:hadRole"]["@id"][5:]
            attrs = usage.get("rime:data", {})
            if role == "recording":
                require(
                    "mapping" in attrs,
                    "Recording use requires an explicit known/unknown temporal mapping.",
                )
            if attrs:
                require(
                    role in ("recording", "import_file"),
                    "Timing attributes are not permitted for this input role.",
                )
        output_data = generated[0]["rime:data"]
        for role, target in inputs:
            if role == "scope_annotations":
                scope = nodes[target]["rime:data"]
                require(scope["status"] == "retained", "Scope annotations must be retained.")
                if kind == "AnnotationProduction":
                    require(
                        scope["timeline"] == output_data["timeline"],
                        "Execution scope timeline differs from produced annotations.",
                    )
