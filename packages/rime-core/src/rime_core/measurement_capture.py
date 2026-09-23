"""Protocol previews and native record capture from editable annotation work.

Preview uses the same pure interval calculator as exchange validation. Capture
receives detached state and retains scientific endpoints, never interface actions.
"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from .exchange import RimeDocument, activity, agent, calculate, entity, UNITS, _union
from .schema import ProtocolSchema

ANNOTATION_FIELDS = ("id", "lane", "label", "start_ms", "end_ms", "event_type")


def recording_timing(source):
    timing = {
        "mapping": {
            "status": "known",
            "offset_ms": source["config"]["offset_ms"],
            "method": "manual_offset",
        }
    }
    if source.get("synchronization_note"):
        timing["alignment_validation"] = source["synchronization_note"]
    return timing


def annotation_values(items):
    return sorted(
        ({key: a[key] for key in ANNOTATION_FIELDS} for a in items), key=lambda a: a["id"]
    )


def settings_for(data):
    return deepcopy(
        data.get(
            "measurement_settings",
            {
                "selected": [d.id for d in ProtocolSchema.from_dict(data["protocol"]).measurements],
                "period": {"mode": "protocol"},
            },
        )
    )


def resolve_period(annotations, outcome, period, duration_ms):
    mode = period.get("mode")
    selected = None
    if mode == "protocol" and outcome.scope is not None:
        selected = [
            a
            for a in annotations
            if a["lane"] == outcome.scope.lane
            and outcome.scope.label in (None, a["label"])
            and a["event_type"] == "interval"
        ]
    elif mode == "annotations":
        lanes = period.get("lanes", [])
        if not lanes:
            raise ValueError("Select at least one observation lane.")
        candidates = [
            a for a in annotations if a["lane"] in lanes and a["event_type"] == "interval"
        ]
        if period.get("all", True):
            selected = candidates
        else:
            ids = period.get("ids", [])
            selected = [a for a in candidates if a["id"] in ids]
            if len(selected) != len(set(ids)) or len(ids) != len(set(ids)):
                raise ValueError(
                    "An observation annotation was removed or is no longer in the selected lanes. Reconfigure the period."
                )
    elif mode not in ("protocol", "time"):
        raise ValueError("Unknown observation selection.")
    if selected is not None:
        return _union([[a["start_ms"], a["end_ms"]] for a in selected]), sorted(
            a["id"] for a in selected
        )
    if mode == "time":
        start, end = period.get("start_ms"), period.get("end_ms")
        if (
            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (start, end))
            or not 0 <= start < end
        ):
            raise ValueError("Choose a finite start and end, with end after start.")
        if duration_ms is not None and end > duration_ms:
            raise ValueError("Observation period extends beyond Video 1.")
        return [[start, end]], None
    if duration_ms is None or not math.isfinite(duration_ms) or duration_ms <= 0:
        raise ValueError("Video 1 duration is not available yet.")
    return [[0, duration_ms]], None


def preview_measurements(data, duration_ms, settings=None):
    schema = ProtocolSchema.from_dict(data["protocol"])
    settings = settings_for(data) if settings is None else settings
    selected = settings["selected"]
    if len(selected) != len(set(selected)) or set(selected) - {d.id for d in schema.measurements}:
        raise ValueError("Unknown or duplicate protocol measurement.")
    annotations = annotation_values(data["annotations"])
    previews = []
    for outcome in schema.measurements:
        if outcome.id not in selected:
            continue
        definition = dict(
            operation=outcome.calculation,
            version=outcome.calculation_version,
            lane=outcome.events.lane,
            label=outcome.events.label,
            unit=UNITS[outcome.calculation],
        )
        spans, ids = resolve_period(annotations, outcome, settings["period"], duration_ms)
        previews.append(
            dict(
                id=outcome.id,
                name=outcome.name,
                definition=definition,
                intervals=spans,
                selection_ids=ids,
                result=calculate(annotations, spans, definition),
            )
        )
    return previews


def _identity(kind, content):
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return f"urn:rime:{kind}:{digest}"


def _checksum(path):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Source changed while being read: {path.name}")
    return digest.hexdigest()


def capture_annotation_basis(data, duration_ms):
    """Retain annotation provenance independently of selecting a measurement."""
    if data.get("format") == "rime-review-workspace":
        from .review_workspace import capture_review_basis

        return capture_review_basis(data)
    data = deepcopy(data)
    nodes = {}

    def add(node):
        nodes[node["@id"]] = node
        return node["@id"]

    def ent(kind, content, producer=None):
        return add(entity(_identity(kind, [content, producer]), kind, content, producer))

    def act(kind, inputs, content, agents=()):
        return add(
            activity(_identity(kind, [inputs, content, agents]), kind, inputs, content, agents)
        )

    timeline = "urn:rime:timeline:" + data["id"]

    def annset(values, producer, review_status="unreviewed", status="retained"):
        return ent(
            "AnnotationSet",
            dict(
                annotations=annotation_values(values),
                timeline=timeline,
                status=status,
                review_status=review_status,
                research_context=data["research_context"],
            ),
            producer,
        )

    def responsibility():
        name = data.get("rater", "").strip()
        if name:
            return [add(agent(_identity("person", name), name))], {}
        return [], {"responsibility": "unknown"}

    def recordings():
        inputs, configurations = [], []
        for source in data["sources"]:
            config = source["config"]
            sid = ent(
                "Source",
                dict(
                    source_kind="recording",
                    modality=source["kind"],
                    file_name=Path(source["path"]).name,
                    sha256=_checksum(source["path"]),
                ),
            )
            inputs.append(
                (
                    "recording",
                    sid,
                    recording_timing(source),
                )
            )
            configurations.append({"source": sid, "configuration": config})
        return inputs, configurations

    all_annotations = annotation_values(data["annotations"])
    runs = [r for r in data.get("suggestion_runs", []) if r["kind"] == "model"]
    model_ids = {
        identifier
        for r in runs
        for s in r["suggestions"]
        for identifier in [s["annotation"]["id"], *s.get("output_ids", [])]
    }
    annotations = [a for a in all_annotations if a["id"] not in model_ids]
    imports = data.get("imports", [])
    original_sets = []
    original = {}
    for retained in imports:
        source = ent(
            "Source",
            dict(
                source_kind="annotation_file",
                file_name=Path(retained["path"]).name,
                sha256=retained["sha256"],
            ),
        )
        # This records import, not authorship by the importing application.
        metadata = {
            key: deepcopy(value)
            for key, value in retained.items()
            if key not in ("path", "sha256", "annotations")
        }
        metadata["original_annotation_history"] = "Not established by importing this file."
        producer = act(
            "AnnotationProduction",
            [
                (
                    "import_file",
                    source,
                    {"mapping": {"status": "known", "offset_ms": 0, "method": "import"}},
                )
            ],
            dict(
                method="import",
                description="EAF annotation import with retained tier and label mapping",
                clinical_definition={"status": "unknown"},
                metadata=metadata,
            ),
        )
        aid = annset(retained["annotations"], producer)
        original_sets.append(aid)
        for annotation in annotation_values(retained["annotations"]):
            if annotation["id"] in original:
                raise ValueError("Duplicate annotation identity across imports.")
            original[annotation["id"]] = (aid, annotation)
    if not imports and not annotations and runs:
        basis = None
    elif not imports:
        inputs, configurations = recordings()
        agents, unknown = responsibility()
        producer = act(
            "AnnotationProduction",
            inputs,
            dict(
                method="manual",
                description="Manual annotation on the workspace evidence timeline",
                clinical_definition={
                    "status": "known",
                    "description": "Workspace annotation protocol",
                    "protocol_id": data["protocol"]["name"],
                    "protocol_version": data["protocol"]["version"],
                },
                metadata={
                    "source_configurations": configurations,
                    "protocol": data["protocol"],
                    "alignment_validation": "Not independently verified",
                    "protocol_assistance": [
                        r for r in data.get("suggestion_runs", []) if r["kind"] == "rule"
                    ],
                },
                **unknown,
            ),
            agents,
        )
        basis = annset(annotations, producer)
    elif len(original_sets) == 1 and annotations == annotation_values(
        [a for _, a in original.values()]
    ):
        basis = original_sets[0]
    else:
        # Final editing decisions, not a record of mouse actions or a claim of adjudication.
        decisions = []
        current = {a["id"]: a for a in annotations}
        for identifier, (aid, old) in original.items():
            new = current.get(identifier)
            extent = [[old["start_ms"], old["end_ms"]]]
            if new is not None:
                extent = [
                    [min(old["start_ms"], new["start_ms"]), max(old["end_ms"], new["end_ms"])]
                ]
            if extent[0][0] == extent[0][1]:
                # The profile requires a nonempty interval extent for review decisions.
                raise ValueError(
                    "Export of edited imported point annotations requires a review extent; this workflow is not connected yet."
                )
            decisions.append(
                dict(
                    action="reject" if new is None else "accept" if new == old else "modify",
                    inputs=[{"entity": aid, "annotation": identifier}],
                    outputs=[] if new is None else [identifier],
                    extent=extent,
                    note="Final workspace retention/edit; not independent verification.",
                )
            )
        for new in annotations:
            if new["id"] not in original:
                if new["event_type"] == "point":
                    raise ValueError(
                        "Export of added points in an imported set requires a review extent; this workflow is not connected yet."
                    )
                decisions.append(
                    dict(
                        action="custom",
                        inputs=[],
                        outputs=[new["id"]],
                        extent=[[new["start_ms"], new["end_ms"]]],
                        note="Annotation added during workspace editing.",
                    )
                )
        inputs, configurations = recordings()
        agents, unknown = responsibility()
        reviewer = act(
            "AnnotationReview",
            [("annotation_input", a) for a in original_sets] + inputs,
            dict(
                method="verification",
                decisions=decisions,
                metadata={
                    "description": "Final edits to imported annotations; no independent verification or adjudication claimed.",
                    "protocol_assistance": [
                        r for r in data.get("suggestion_runs", []) if r["kind"] == "rule"
                    ],
                    "protocol": data["protocol"],
                    "source_configurations": configurations,
                },
                **unknown,
            ),
            agents,
        )
        basis = annset(annotations, reviewer, "incomplete")
    if runs:
        inputs = [("annotation_input", basis)] if basis else []
        decisions = []
        current = {a["id"]: a for a in all_annotations}
        for a in annotations:
            decisions.append(
                dict(
                    action="accept",
                    inputs=[{"entity": basis, "annotation": a["id"]}],
                    outputs=[a["id"]],
                    extent=[[0, duration_ms]],
                    note="Existing workspace annotation retained.",
                )
            )
        for run in runs:
            package = ent(
                "Source", dict(source_kind="model_package", sha256=None, **run["package"])
            )
            used = [("model_package", package)]
            source_ids = {}
            source_configs = []
            for retained in run["sources"]:
                source = retained["source"]
                ref = ent(
                    "Source",
                    dict(
                        source_kind="recording",
                        modality=source["kind"],
                        file_name=Path(source["path"]).name,
                        sha256=retained["sha256"],
                    ),
                )
                source_ids[source["config"]["id"]] = ref
                source_configs.append({"source": ref, "configuration": source["config"]})
                used.append(
                    (
                        "recording",
                        ref,
                        recording_timing(source),
                    )
                )
            model = add(
                agent(_identity("model", [run["name"], run["package"]]), run["name"], "model")
            )
            execution = deepcopy(run["execution"])
            for binding in execution["bindings"]:
                binding["source"] = source_ids[binding["source"]]
            execution["source_configurations"] = source_configs
            production = act(
                "AnnotationProduction",
                used,
                dict(
                    method="computational",
                    description=run["name"],
                    clinical_definition={"status": "unknown"},
                    execution_specification=execution,
                ),
                [model],
            )
            proposals = annset(
                [s["annotation"] for s in run["suggestions"]], production, status="proposed"
            )
            inputs.append(("annotation_input", proposals))
            for item in run["suggestions"]:
                old = annotation_values([item["annotation"]])[0]
                outputs = [current[i] for i in item.get("output_ids", [old["id"]]) if i in current]
                new = outputs[0] if outputs else None
                action = item["decision"]
                if action == "pending":
                    action = "unresolved"
                elif new is None and action in ("accept", "modify"):
                    action = "reject"
                elif new is not None:
                    action = "accept" if outputs == [old] else "modify"
                decisions.append(
                    dict(
                        action=action,
                        inputs=[{"entity": proposals, "annotation": old["id"]}],
                        outputs=[a["id"] for a in outputs],
                        extent=[run["execution"]["time_range"]],
                        note="Final model suggestion decision; extent is the model execution period.",
                    )
                )
        agents, unknown = responsibility()
        reviewer = act(
            "AnnotationReview",
            inputs,
            dict(method="verification", decisions=decisions, **unknown),
            agents,
        )
        basis = annset(all_annotations, reviewer, "incomplete")
    return nodes, basis


def capture_measurements(data, duration_ms, settings=None):
    """Return an immutable, schema-validated native document, without writing it."""
    data = deepcopy(data)
    previews = preview_measurements(data, duration_ms, settings)
    if not previews:
        raise ValueError("Select at least one protocol measurement.")
    nodes, basis = capture_annotation_basis(data, duration_ms)
    timeline = "urn:rime:timeline:" + data["id"]

    def ent(kind, content, producer=None):
        node = entity(_identity(kind, [content, producer]), kind, content, producer)
        nodes[node["@id"]] = node
        return node["@id"]

    def act(kind, inputs, content):
        node = activity(_identity(kind, [inputs, content, []]), kind, inputs, content)
        nodes[node["@id"]] = node
        return node["@id"]

    roots = []
    for preview in previews:
        observation = dict(timeline=timeline, intervals=preview["intervals"])
        if preview["selection_ids"] is not None:
            observation["selection"] = dict(
                rule="selected_annotations",
                annotation_set=basis,
                annotation_ids=preview["selection_ids"],
            )
        obs = ent("ObservationPeriod", observation)
        definition = ent("CalculationDefinition", preview["definition"])
        calc = act(
            "MeasurementCalculation",
            [("annotations", basis), ("observation", obs), ("definition", definition)],
            {
                "metadata": {
                    "implementation": "RIME interval calculator 1",
                    "outcome_id": preview["id"],
                    "outcome_name": preview["name"],
                    "protocol": data["protocol"],
                }
            },
        )
        roots.append(ent("MeasurementResult", preview["result"], calc))
    return RimeDocument.create(nodes.values(), roots)
