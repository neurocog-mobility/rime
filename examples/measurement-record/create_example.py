"""Build native graph examples, using synthetic evidence only."""

from pathlib import Path
import copy
import hashlib
import xml.etree.ElementTree as ET

from rime_core.exchange import RimeDocument, activity, agent, calculate, entity, write_document

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "examples/workflows/records"


def identity(name):
    return "urn:rime:example:" + name


def annotation(name, start, end, lane="FOG", label="FOG"):
    return dict(id=name, start_ms=start, end_ms=end, event_type="interval", lane=lane, label=label)


def add_measurements(
    nodes, annotation_id, spans, operations=("percentage_coverage",), selection=None
):
    ann = next(n["rime:data"] for n in nodes if n["@id"] == annotation_id)
    observation = {"timeline": ann["timeline"], "intervals": spans}
    if selection:
        observation["selection"] = {
            "rule": "selected_annotations",
            "annotation_set": annotation_id,
            "annotation_ids": selection,
        }
    obs_id = annotation_id + ":observation"
    nodes.append(entity(obs_id, "ObservationPeriod", observation))
    roots = []
    for operation in operations:
        definition = dict(
            operation=operation,
            version="1",
            unit={"percentage_coverage": "%", "covered_duration": "s", "count": "count"}[operation],
            lane="FOG",
            label="FOG",
        )
        def_id, calc_id, result_id = (
            annotation_id + ":" + operation + "-" + part
            for part in ("definition", "calculation", "result")
        )
        nodes.extend(
            [
                entity(def_id, "CalculationDefinition", definition),
                activity(
                    calc_id,
                    "MeasurementCalculation",
                    [
                        ("annotations", annotation_id),
                        ("observation", obs_id),
                        ("definition", def_id),
                    ],
                    {"metadata": {"implementation": "RIME interval calculator 1"}},
                ),
                entity(
                    result_id,
                    "MeasurementResult",
                    calculate(ann["annotations"], spans, definition),
                    calc_id,
                ),
            ]
        )
        roots.append(result_id)
    return RimeDocument.create(nodes, roots)


def imported():
    path = ROOT / "examples/measurement-record/synthetic-annotations.eaf"
    xml = ET.fromstring(path.read_bytes())
    times = {
        n.attrib["TIME_SLOT_ID"]: int(n.attrib["TIME_VALUE"])
        for n in xml.findall("./TIME_ORDER/TIME_SLOT")
    }
    annotations = []
    for tier in xml.findall("TIER"):
        for a in tier.findall("./ANNOTATION/ALIGNABLE_ANNOTATION"):
            annotations.append(
                annotation(
                    a.attrib["ANNOTATION_ID"],
                    times[a.attrib["TIME_SLOT_REF1"]],
                    times[a.attrib["TIME_SLOT_REF2"]],
                    tier.attrib["TIER_ID"],
                    a.findtext("ANNOTATION_VALUE", ""),
                )
            )
    source_id, producer_id, ann_id = (
        identity("import-" + n) for n in ("eaf", "import", "annotations")
    )
    data = dict(
        annotations=annotations,
        timeline="EAF milliseconds",
        status="retained",
        review_status="unknown",
        research_context={"participant": "synthetic", "trial": "import-example"},
    )
    nodes = [
        entity(
            source_id,
            "Source",
            dict(
                source_kind="annotation_file",
                file_name=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                media_reference=Path(
                    xml.find("./HEADER/MEDIA_DESCRIPTOR").attrib["MEDIA_URL"]
                ).name,
                media_identity="unknown",
                original_author=xml.attrib.get("AUTHOR") or None,
            ),
        ),
        activity(
            producer_id,
            "AnnotationProduction",
            [
                (
                    "import_file",
                    source_id,
                    {"mapping": {"status": "known", "offset_ms": 0, "method": "import"}},
                )
            ],
            {
                "method": "import",
                "description": "EAF 3.0 alignable annotation import",
                "clinical_definition": {"status": "unknown"},
                "metadata": {
                    "original_annotation_history": "unknown",
                    "mapping": "Tier IDs, values and millisecond boundaries retained unchanged; media alignment not independently verified.",
                },
            },
        ),
        entity(ann_id, "AnnotationSet", data, producer_id),
    ]
    task = next(a for a in annotations if a["lane"] == "Task")
    return add_measurements(
        nodes,
        ann_id,
        [[task["start_ms"], task["end_ms"]]],
        ("percentage_coverage", "covered_duration", "count"),
        [task["id"]],
    )


def synthetic(review=False):
    src, act, ann, person = (
        identity(("review-" if review else "manual-") + n)
        for n in ("synthetic-source", "production", "annotations", "reviewer")
    )
    nodes = [
        entity(
            src,
            "Source",
            {
                "source_kind": "recording",
                "modality": "video",
                "file_name": "synthetic.mp4",
                "sha256": None,
                "synthetic": True,
            },
        ),
        agent(person, "Synthetic researcher"),
        activity(
            act,
            "AnnotationProduction",
            [
                (
                    "recording",
                    src,
                    {"mapping": {"status": "known", "offset_ms": 0, "method": "manual_offset"}},
                )
            ],
            {
                "method": "manual",
                "description": "Synthetic manual annotation fixture",
                "clinical_definition": {
                    "status": "known",
                    "description": "Synthetic FOG intervals for software checks",
                },
            },
            [person],
        ),
        entity(
            ann,
            "AnnotationSet",
            dict(
                annotations=[annotation("a1", 10000, 16000), annotation("a2", 30000, 36000)],
                timeline="video1:ms",
                status="proposed" if review else "retained",
                review_status="unreviewed",
            ),
            act,
        ),
    ]
    if review:
        reviewed, reviewer_act = identity("reviewed"), identity("review")
        nodes.extend(
            [
                activity(
                    reviewer_act,
                    "AnnotationReview",
                    [("annotation_input", ann)],
                    {
                        "method": "verification",
                        "decisions": [
                            {
                                "action": "accept",
                                "inputs": [{"entity": ann, "annotation": "a1"}],
                                "outputs": ["r1"],
                                "extent": [[10000, 16000]],
                            },
                            {
                                "action": "reject_remaining",
                                "inputs": [{"entity": ann, "annotation": "a2"}],
                                "outputs": [],
                                "extent": [[30000, 36000]],
                            },
                        ],
                    },
                    [person],
                ),
                entity(
                    reviewed,
                    "AnnotationSet",
                    dict(
                        annotations=[annotation("r1", 10000, 16000)],
                        timeline="video1:ms",
                        status="retained",
                        review_status="complete",
                    ),
                    reviewer_act,
                ),
            ]
        )
        ann = reviewed
    return add_measurements(nodes, ann, [[0, 60000]])


def computational(review=False):
    """Explicit synthetic model fixture, not a claim of an executed detector."""
    doc = synthetic(review)
    nodes = copy.deepcopy(list(doc.nodes.values()))
    production = next(n for n in nodes if "rime:AnnotationProduction" in n["@type"])
    old_person = production["prov:wasAssociatedWith"][0]["@id"]
    model_id, package_id = identity("synthetic-model"), identity("synthetic-package")
    production["rime:data"].update(
        method="computational",
        description="Synthetic model-output fixture; no detector was executed",
        execution_specification={"fixture": True, "intervals_ms": [[10000, 16000], [30000, 36000]]},
    )
    production["prov:used"].append({"@id": package_id})
    production["prov:qualifiedUsage"].append(
        {
            "@type": "prov:Usage",
            "prov:entity": {"@id": package_id},
            "prov:hadRole": {"@id": "rime:model_package"},
        }
    )
    production["prov:wasAssociatedWith"] = [{"@id": model_id}]
    nodes += [
        agent(model_id, "Synthetic annotation model", "model"),
        entity(
            package_id,
            "Source",
            dict(
                source_kind="model_package",
                file_name="synthetic-package.zip",
                sha256=None,
                synthetic=True,
                manifest=[
                    {
                        "file_name": "fixture.json",
                        "sha256": hashlib.sha256(b"synthetic fixture").hexdigest(),
                    }
                ],
                scope="Synthetic fixture; not an executed or exchangeable detector",
                digest_scope="Archive unavailable for synthetic fixture",
            ),
        ),
    ]
    if not review:
        nodes = [n for n in nodes if n["@id"] != old_person]
    return RimeDocument.create(nodes, doc.records)


def adjudication():
    doc = synthetic(True)
    nodes = copy.deepcopy(list(doc.nodes.values()))
    production = next(n for n in nodes if "rime:AnnotationProduction" in n["@type"])
    annotations = next(
        n for n in nodes if n.get("prov:wasGeneratedBy") == {"@id": production["@id"]}
    )
    second_production, second_annotations = copy.deepcopy(production), copy.deepcopy(annotations)
    second_production["@id"] = identity("second-production")
    second_annotations["@id"] = identity("second-annotations")
    second_annotations["prov:wasGeneratedBy"] = {"@id": second_production["@id"]}
    second_person = identity("second-person")
    second_production["prov:wasAssociatedWith"] = [{"@id": second_person}]
    review = next(n for n in nodes if "rime:AnnotationReview" in n["@type"])
    review["rime:data"]["method"] = "adjudication"
    review["prov:used"].append({"@id": second_annotations["@id"]})
    review["prov:qualifiedUsage"].append(
        {
            "@type": "prov:Usage",
            "prov:entity": {"@id": second_annotations["@id"]},
            "prov:hadRole": {"@id": "rime:annotation_input"},
        }
    )
    for decision in review["rime:data"]["decisions"]:
        decision["inputs"] += [
            dict(entity=second_annotations["@id"], annotation=r["annotation"])
            for r in list(decision["inputs"])
        ]
    return RimeDocument.create(
        nodes
        + [second_production, second_annotations, agent(second_person, "Second synthetic rater")],
        doc.records,
    )


def convergence_pair(category, *, operation="count"):
    """Same-source computational branches with explicit output convergence."""

    def make(side):
        source, production, annotations = (
            identity("comparison-" + n)
            for n in ("source", "production-" + side, "annotations-" + side)
        )
        spans = [(1000, 3000), (6000, 8000)]
        if side == "b" and category == "measurement_output_only":
            spans = [(2000, 4000), (7000, 9000)]
        elif side == "b" and category == "neither":
            spans = [(1000, 2000)]
        model, package = identity("comparison-model"), identity("comparison-package")
        nodes = [
            entity(
                source,
                "Source",
                dict(
                    source_kind="recording",
                    modality="signal",
                    file_name="synthetic.csv",
                    sha256="1" * 64,
                ),
            ),
            agent(model, "Synthetic model", "model"),
            entity(
                package,
                "Source",
                dict(
                    source_kind="model_package",
                    file_name="synthetic.cmf",
                    sha256=None,
                    synthetic=True,
                    manifest=[{"file_name": "fixture.json", "sha256": "2" * 64}],
                    scope="Synthetic example",
                    digest_scope="Synthetic fixture archive unavailable",
                ),
            ),
            activity(
                production,
                "AnnotationProduction",
                [
                    (
                        "recording",
                        source,
                        {"mapping": {"status": "known", "offset_ms": 0, "method": "manual_offset"}},
                    ),
                    ("model_package", package),
                ],
                dict(
                    method="computational",
                    description="Synthetic comparison branch",
                    clinical_definition={"status": "known", "description": "Synthetic events"},
                    execution_specification={"threshold": 0.5 if side == "a" else 0.6},
                ),
                [model],
            ),
            entity(
                annotations,
                "AnnotationSet",
                dict(
                    annotations=[
                        annotation(str(i), start, end) for i, (start, end) in enumerate(spans)
                    ],
                    timeline="synthetic:ms",
                    status="retained",
                    review_status="unreviewed",
                ),
                production,
            ),
        ]
        return add_measurements(nodes, annotations, [[0, 10000]], (operation,))

    return make("a"), make("b")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, doc in [
        ("synthetic-import", imported()),
        ("synthetic-manual", synthetic()),
        ("synthetic-review", synthetic(True)),
        ("synthetic-model", computational()),
        ("synthetic-model-review", computational(True)),
        ("synthetic-adjudication", adjudication()),
    ]:
        path = OUT / (name + ".rime")
        write_document(path, doc)
        print(path)


if __name__ == "__main__":
    main()
