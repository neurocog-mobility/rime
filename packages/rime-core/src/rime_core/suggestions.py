"""Retained computational runs and explicit decisions, separate from annotations."""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import uuid
import numpy as np

from .records import SignalSource
from .loaders import SignalLoaderRegistry
from .inference import InferenceRunner, InputBinding, OutputMapping
from .measurement_capture import _checksum


def pending(data):
    return [
        (run, item)
        for run in data.get("suggestion_runs", [])
        for item in run["suggestions"]
        if item["decision"] == "pending"
    ]


def execute(package, data, bindings, mappings, params, time_range):
    """Execute against detached inputs; retain the exact package and source identities."""
    missing = package.missing_requirements()
    if missing:
        raise ValueError(f"Missing model requirements: {missing}")
    root = Path(package._model_dir)
    if any(p.is_dir() and p.name != "__pycache__" for p in root.iterdir()):
        raise ValueError("This workflow requires a CMF package with top-level files only.")
    files = sorted(p for p in root.iterdir() if p.is_file())
    manifest = [{"file_name": p.name, "sha256": _checksum(p)} for p in files]
    source_inputs, runner_bindings = [], []
    for binding in bindings:
        source = next(s for s in data["sources"] if s["config"]["id"] == binding["source"])
        if not any(s["source"]["config"]["id"] == source["config"]["id"] for s in source_inputs):
            source_inputs.append(dict(source=deepcopy(source), sha256=_checksum(source["path"])))
        if source["kind"] == "signal":
            signal = SignalLoaderRegistry.default().load(
                Path(source["path"]), SignalSource(**source["config"])
            )
            signal.offset_ms = source["config"]["offset_ms"]
            runner_bindings.append(
                InputBinding(binding["name"], signal=signal, channel_map=binding["channels"])
            )
        else:
            if source["config"]["offset_ms"] != 0:
                raise ValueError("Video model inputs currently require a zero source offset.")
            runner_bindings.append(InputBinding(binding["name"], video_path=Path(source["path"])))
    requested_range = list(time_range)
    time_range = list(time_range)
    if package.config.inference_mode == "whole_signal":
        origins = []
        for binding in runner_bindings:
            if binding.signal is not None:
                times = binding.signal.get_time_ms()
                selected = times[(times >= time_range[0]) & (times <= time_range[1])]
                if not len(selected):
                    raise ValueError("No signal samples in the selected period.")
                origins.append(float(selected[0]))
        if origins:
            if not np.allclose(origins, origins[0], rtol=0, atol=1e-6):
                raise ValueError(
                    "Whole-signal model inputs must start on the same aligned sample time."
                )
            time_range[0] = origins[0]
    result = InferenceRunner(
        package, runner_bindings, [OutputMapping(**m) for m in mappings], params
    ).run(tuple(time_range))
    for retained in source_inputs:
        if _checksum(retained["source"]["path"]) != retained["sha256"]:
            raise ValueError("A recording changed during model execution.")
    if manifest != [{"file_name": p.name, "sha256": _checksum(p)} for p in files]:
        raise ValueError("The model package changed during execution.")
    suggestions = []
    for annotation in result.annotations:
        # Outputs outside the requested timeline must not be silently clipped.
        if not time_range[0] <= annotation.start_ms <= annotation.end_ms <= time_range[1]:
            raise ValueError("Model produced annotations outside the selected time period.")
        annotation = replace(annotation, id=uuid.uuid4().hex, ghost=False)
        suggestions.append(dict(annotation=asdict(annotation), decision="pending"))
    return dict(
        id=uuid.uuid4().hex,
        kind="model",
        name=package.name,
        package=dict(
            file_name=Path(package.path).name,
            manifest=manifest,
            scope="Retained top-level CMF package files",
            digest_scope="manifest",
        ),
        execution=dict(
            config=asdict(package.config),
            bindings=bindings,
            outputs=mappings,
            parameters=params,
            time_range=list(time_range),
            requested_time_range=requested_range,
        ),
        sources=source_inputs,
        suggestions=suggestions,
    )


def admit(workspace, run):
    def change(data):
        data.setdefault("suggestion_runs", []).append(deepcopy(run))

    workspace.change(change)


def revise(workspace, identifier, annotation):
    """Save a pending edit without changing the original model output or accepting it."""
    from .annotation_workspace import AnnotationWorkspace

    draft = asdict(replace(annotation, id=identifier, ghost=False))
    check = deepcopy(workspace.data)
    check["annotations"] = [draft]
    check["suggestion_runs"] = []
    AnnotationWorkspace(check)

    def change(data):
        item = next(item for _, item in pending(data) if item["annotation"]["id"] == identifier)
        item["draft"] = draft

    workspace.change(change)


def decide(workspace, identifier, action, annotation=None):
    if action not in ("accept", "modify", "reject", "reject_remaining"):
        raise ValueError("Unknown suggestion decision.")

    def change(data):
        item = next(item for _, item in pending(data) if item["annotation"]["id"] == identifier)
        item["decision"] = action
        if action in ("accept", "modify"):
            result = (
                deepcopy(item.get("draft", item["annotation"]))
                if annotation is None
                else asdict(annotation)
            )
            result.update(id=identifier, ghost=False)
            if result != item["annotation"]:
                item["decision"] = "modify"
            data["annotations"].append(result)
            item["output_ids"] = [identifier]

    workspace.change(change)


def assist(workspace, annotation):
    from .rule_engine import RuleEngine

    engine = RuleEngine(workspace.schema)
    effects, violations = engine.on_create(annotation, workspace.store)
    if effects:
        admit(
            workspace,
            dict(
                id=uuid.uuid4().hex,
                kind="rule",
                name="Protocol suggestions",
                parent=asdict(annotation),
                protocol=deepcopy(workspace.data["protocol"]),
                suggestions=[
                    dict(annotation=asdict(replace(e.annotation, ghost=False)), decision="pending")
                    for e in effects
                ],
            ),
        )
    return [v.message for v in violations] + [v.message for v in engine.validate(workspace.store)]
