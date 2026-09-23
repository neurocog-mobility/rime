"""Native review of frozen annotation inputs on one Video 1 timeline."""

from copy import deepcopy
from pathlib import Path
from dataclasses import asdict
import math
import uuid

from .annotation_workspace import AnnotationWorkspace
from .annotations import Annotation
from .exchange import activity, agent, entity, _union
from .measurement_capture import capture_annotation_basis, annotation_values, _checksum, _identity


def load_input(path):
    workspace = AnnotationWorkspace.open(path)
    video = next(s for s in workspace.data["sources"] if s["kind"] == "video")
    return dict(
        path=str(workspace.path),
        data=deepcopy(workspace.data),
        video_sha256=_checksum(video["path"]),
    )


def compatible(candidate, inputs):
    if any(candidate["path"] == item["path"] for item in inputs):
        raise ValueError("This workspace has already been added.")
    if inputs:
        if candidate["data"]["protocol"] != inputs[0]["data"]["protocol"]:
            raise ValueError("Different protocol.")
        if candidate["video_sha256"] != inputs[0]["video_sha256"]:
            raise ValueError("Different Video 1.")


def _namespace(nodes, basis, prefix):
    names = {identifier: prefix + str(i) for i, identifier in enumerate(nodes)}

    def remap(value):
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [remap(item) for item in value]
        return names.get(value, value) if isinstance(value, str) else value

    return {names[k]: remap(v) for k, v in nodes.items()}, names[basis]


class ReviewWorkspace(AnnotationWorkspace):
    format = "rime-review-workspace"
    version = "0.2"

    @classmethod
    def create_review(cls, name, reviewer, candidates):
        if not candidates:
            raise ValueError("Add at least one annotation workspace.")
        for i, candidate in enumerate(candidates):
            compatible(candidate, candidates[:i])
        identifier = uuid.uuid4().hex
        retained = []
        for index, item in enumerate(candidates):
            state = deepcopy(item["data"])
            # Video 1 defines the same zero in every compatible input.
            state["id"] = identifier
            import cv2

            video = next(s for s in state["sources"] if s["kind"] == "video")
            if _checksum(video["path"]) != item["video_sha256"]:
                raise ValueError("Video 1 changed after the workspace was added.")
            reader = cv2.VideoCapture(video["path"])
            fps = reader.get(cv2.CAP_PROP_FPS)
            duration = reader.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000 if fps > 0 else 0
            reader.release()
            if duration <= 0:
                raise ValueError("Cannot read Video 1 duration.")
            nodes, basis = capture_annotation_basis(state, duration)
            nodes, basis = _namespace(nodes, basis, f"urn:rime:review:{identifier}:input:{index}:")
            retained.append(
                dict(
                    name=state["rater"] or state["name"],
                    workspace_id=item["data"]["id"],
                    research_context=state["research_context"],
                    annotations=annotation_values(state["annotations"]),
                    nodes=nodes,
                    basis=basis,
                    video_sha256=item["video_sha256"],
                )
            )
        first = candidates[0]["data"]
        return cls(
            dict(
                format=cls.format,
                version=cls.version,
                id=identifier,
                name=name,
                rater=reviewer,
                protocol=deepcopy(first["protocol"]),
                research_context=deepcopy(first["research_context"]),
                sources=deepcopy(first["sources"]),
                imports=[],
                annotations=[],
                view={},
                review_inputs=retained,
                review_evidence=[
                    dict(source=deepcopy(source), sha256=_checksum(source["path"]))
                    for source in first["sources"]
                ],
                review_cases=[],
                review_decisions={},
                duration_ms=duration,
            )
        )

    def validate(self):
        super().validate()
        if not self.data.get("rater", "").strip():
            raise ValueError("Enter the reviewer name.")
        if not self.data.get("review_inputs"):
            raise ValueError("A review needs at least one input.")
        cases = self.data["review_cases"]
        if len({c["id"] for c in cases}) != len(cases):
            raise ValueError("Duplicate review region.")
        if set(self.data["review_decisions"]) - {c["id"] for c in cases}:
            raise ValueError("Unknown review region.")
        expected = [
            a
            for c in cases
            for a in self.data["review_decisions"].get(c["id"], {}).get("annotations", [])
        ]
        if self.data["annotations"] != expected:
            raise ValueError("Reviewer annotations must follow saved decisions.")
        if set(self.data["review_decisions"]) != {c["id"] for c in cases}:
            raise ValueError("Every saved decision must have its selected inputs and output.")
        for case in cases:
            lane = self.schema.get_lane(case["lane"])
            if not lane or case["label"] not in lane.labels:
                raise ValueError("Unknown review lane or label.")
            for ref in case["inputs"]:
                value = self.input_annotation(ref)
                if (value["lane"], value["label"], value["event_type"]) != (
                    case["lane"],
                    case["label"],
                    case["event_type"],
                ):
                    raise ValueError("Selected inputs must share a lane, label and event type.")
                source = self.data["review_inputs"][ref["index"]]
                if not any(a["id"] == ref["annotation"] for a in source["annotations"]):
                    raise ValueError("Unknown input annotation.")

    def shared_input_warnings(self):
        cases = self.data["review_cases"]
        refs = {c["id"]: {(r["index"], r["annotation"]) for r in c["inputs"]} for c in cases}
        return {
            c["id"]: "Shares input annotations with "
            + ", ".join(
                f"Decision {i + 1}"
                for i, other in enumerate(cases)
                if other["id"] != c["id"] and refs[c["id"]] & refs[other["id"]]
            )
            + "."
            for c in cases
            if any(other != c["id"] and refs[c["id"]] & values for other, values in refs.items())
        }

    def cases(self, lane, label):
        return [c for c in self.data["review_cases"] if c["lane"] == lane and c["label"] == label]

    def verify_evidence(self):
        for retained in self.data["review_evidence"]:
            path = retained["source"]["path"]
            if _checksum(path) != retained["sha256"]:
                raise ValueError(f"Review evidence has changed: {Path(path).name}")

    def input_annotation(self, ref):
        try:
            return next(
                a
                for a in self.data["review_inputs"][ref["index"]]["annotations"]
                if a["id"] == ref["annotation"]
            )
        except (IndexError, KeyError, StopIteration):
            raise ValueError("Unknown input annotation.") from None

    def input_refs(self, lane=None, label=None, unresolved=False):
        assigned = {
            (r["index"], r["annotation"]) for c in self.data["review_cases"] for r in c["inputs"]
        }
        refs = [
            dict(index=i, annotation=a["id"])
            for i, item in enumerate(self.data["review_inputs"])
            for a in item["annotations"]
            if (lane is None or a["lane"] == lane)
            and (label is None or a["label"] == label)
            and (not unresolved or (i, a["id"]) not in assigned)
        ]
        return sorted(
            refs, key=lambda r: (self.input_annotation(r)["start_ms"], r["index"], r["annotation"])
        )

    def selection(self, refs, identifier=None):
        if not refs:
            raise ValueError("Select at least one input annotation.")
        values = [self.input_annotation(r) for r in refs]
        if len({(a["lane"], a["label"], a["event_type"]) for a in values}) != 1:
            raise ValueError("Select annotations from one lane and label.")
        a = values[0]
        return dict(
            id=identifier or uuid.uuid4().hex,
            lane=a["lane"],
            label=a["label"],
            event_type=a["event_type"],
            start_ms=min(a["start_ms"] for a in values),
            end_ms=max(a["end_ms"] for a in values),
            inputs=deepcopy(refs),
        )

    def spans(self, case, choice, custom=()):
        sets = [[] for _ in self.data["review_inputs"]]
        for ref in case["inputs"]:
            a = next(
                a
                for a in self.data["review_inputs"][ref["index"]]["annotations"]
                if a["id"] == ref["annotation"]
            )
            sets[ref["index"]].append([a["start_ms"], a["end_ms"]])
        if choice.startswith("input:"):
            selected = sets[int(choice.split(":")[1])]
            if not selected:
                raise ValueError("No selected annotations from this input.")
            return deepcopy(selected)
        if choice == "custom":
            return [list(span) for span in custom]
        if choice == "no_event":
            return []
        sets = [spans for spans in sets if spans]
        if not sets:
            raise ValueError("Select input annotations or use custom boundaries.")
        if choice not in ("mean", "union", "intersection"):
            raise ValueError("Choose a review decision.")
        if choice == "mean":
            if any(len(spans) != 1 for spans in sets):
                raise ValueError(
                    "Average requires one selected annotation per participating input."
                )
            return [[sum(s[0][i] for s in sets) / len(sets) for i in (0, 1)]]
        if case["event_type"] == "point":
            values = [{a for a, b in spans} for spans in sets]
            result = set.union(*values) if choice == "union" else set.intersection(*values)
            return [[t, t] for t in sorted(result)]
        if choice == "union":
            return _union([span for spans in sets for span in spans])
        if choice == "intersection":
            result = sets[0]
            for spans in sets[1:]:
                result = [
                    [max(a, c), min(b, d)]
                    for a, b in result
                    for c, d in spans
                    if max(a, c) < min(b, d)
                ]
            return _union(result)
        raise ValueError("Choose a review decision.")

    def save_decision(self, case, choice, custom=(), note=""):
        case = deepcopy(case)
        case_id = case["id"]
        spans = self.spans(case, choice, custom)
        annotations = []
        for i, (start, end) in enumerate(spans):
            if not all(
                math.isfinite(t) and 0 <= t <= self.data["duration_ms"] for t in (start, end)
            ):
                raise ValueError("Boundaries must fall within Video 1.")
            annotations.append(
                asdict(
                    Annotation(
                        f"{case_id}:{i}",
                        case["lane"],
                        case["label"],
                        start,
                        end,
                        event_type=case["event_type"],
                    )
                )
            )

        def update(data):
            existing = next(
                (i for i, c in enumerate(data["review_cases"]) if c["id"] == case_id), None
            )
            if existing is None:
                data["review_cases"].append(case)
            else:
                data["review_cases"][existing] = case
            data["review_decisions"][case_id] = dict(
                choice=choice, annotations=annotations, note=note
            )
            self._output(data)

        self.change(update)

    @staticmethod
    def _output(data):
        data["annotations"] = [
            a
            for c in data["review_cases"]
            for a in data["review_decisions"].get(c["id"], {}).get("annotations", [])
        ]

    def unresolved(self, case_id):
        def update(data):
            data["review_decisions"].pop(case_id, None)
            data["review_cases"] = [c for c in data["review_cases"] if c["id"] != case_id]
            self._output(data)

        self.change(update)


def capture_review_basis(data):
    nodes = {k: deepcopy(v) for item in data["review_inputs"] for k, v in item["nodes"].items()}
    decisions = []
    workspace = ReviewWorkspace(data)
    unresolved = [workspace.selection([r]) for r in workspace.input_refs(unresolved=True)]
    for case in [*data["review_cases"], *unresolved]:
        saved = data["review_decisions"].get(case["id"])
        spans = (
            [[case["start_ms"], case["end_ms"]]]
            if case["event_type"] == "interval"
            else [[0, data["duration_ms"]]]
        )
        choice = saved["choice"] if saved else "unresolved"
        action = "accept" if choice.startswith("input:") else choice
        if saved and not saved["annotations"] and action not in ("unresolved", "no_event"):
            action = "no_event"
        outputs = [] if not saved else [a["id"] for a in saved["annotations"]]
        if saved and saved["annotations"] and case["event_type"] == "interval":
            spans = _union(spans + [[a["start_ms"], a["end_ms"]] for a in saved["annotations"]])
        decisions.append(
            dict(
                action=action,
                extent=spans,
                inputs=[
                    dict(
                        entity=data["review_inputs"][r["index"]]["basis"],
                        annotation=r["annotation"],
                    )
                    for r in case["inputs"]
                ],
                outputs=outputs,
                note=saved.get("note", "") if saved else "Not yet resolved.",
            )
        )
    reviewer = agent(_identity("reviewer", data["rater"]), data["rater"])
    nodes[reviewer["@id"]] = reviewer
    content = dict(
        method="verification" if len(data["review_inputs"]) == 1 else "adjudication",
        decisions=decisions,
        metadata={
            "protocol": data["protocol"],
            "decision_choices": {
                key: value["choice"] for key, value in data["review_decisions"].items()
            },
            "source_configurations": [item["source"]["config"] for item in data["review_evidence"]],
        },
    )
    inputs = [("annotation_input", item["basis"]) for item in data["review_inputs"]]
    for retained in data["review_evidence"]:
        source = retained["source"]
        attributes = dict(
            source_kind="recording",
            modality=source["kind"],
            file_name=Path(source["path"]).name,
            sha256=retained["sha256"],
        )
        ref = entity(_identity("review-evidence", attributes), "Source", attributes)
        nodes[ref["@id"]] = ref
        inputs.append(
            (
                "recording",
                ref["@id"],
                {
                    "mapping": dict(
                        status="known",
                        offset_ms=source["config"]["offset_ms"],
                        method="manual_offset",
                    )
                },
            )
        )
    review = activity(
        _identity("review", [inputs, content, reviewer]),
        "AnnotationReview",
        inputs,
        content,
        [reviewer["@id"]],
    )
    nodes[review["@id"]] = review
    output = dict(
        annotations=annotation_values(data["annotations"]),
        timeline="urn:rime:timeline:" + data["id"],
        status="retained",
        review_status="complete" if not unresolved else "incomplete",
        research_context=data["research_context"],
    )
    result = entity(
        _identity("review-output", [output, review["@id"]]), "AnnotationSet", output, review["@id"]
    )
    nodes[result["@id"]] = result
    return nodes, result["@id"]
