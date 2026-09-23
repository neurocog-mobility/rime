"""Native inspector integration: real files and retained data, never UI fixtures."""

import importlib.util
import json
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QFileDialog

from rime_core.exchange import write_document
from rime_core.record_comparison import record_nodes, _links
from rime_core.record_overlay import recover_record
from rime_core.record_inspection import inspection_graph, verify_record
from rime_ui.presentation.records import RecordWindow

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "inspector_examples", ROOT / "examples/measurement-record/create_example.py"
)
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def settle(app, window):
    deadline = time.monotonic() + 15
    while window.records.busy:
        assert time.monotonic() < deadline, "Inspector operation timed out"
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def window(app):
    w = RecordWindow()
    w.show()
    yield w
    settle(app, w)
    w.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def native_file(tmp_path):
    p = tmp_path / "manual.rime"
    write_document(p, examples.synthetic())
    return p


@pytest.mark.parametrize(
    "category,annotation_equal,result_equal",
    [
        ("annotation_output", True, True),
        ("measurement_output_only", False, True),
        ("neither", False, False),
    ],
)
def test_synthetic_convergence_and_lossless_graph(category, annotation_equal, result_equal):
    a, b = examples.convergence_pair(category)
    graph = inspection_graph(a, a.records[0], b, b.records[0])
    assert (graph["roots"]["a"] == graph["roots"]["b"]) == result_equal

    def event_set(side):
        _, native = record_nodes(a if side == "a" else b)
        result = native[(a if side == "a" else b).records[0]]
        calc = native[result["prov:wasGeneratedBy"]["@id"]]
        target = next(
            u["prov:entity"]["@id"]
            for u in calc["prov:qualifiedUsage"]
            if u["prov:hadRole"]["@id"] == "rime:annotations"
        )
        return next(
            n["id"]
            for n in graph["nodes"]
            if side in n["originals"] and n["originals"][side]["@id"] == target
        )

    assert (event_set("a") == event_set("b")) == annotation_equal
    for side, document in [("a", a), ("b", b)]:
        assert recover_record(graph, side) == record_nodes(document)
        # Display-omitted links remain in the audit, with the original usage attributes.
        expected = [
            (owner, relation, role, target, json.dumps(attrs, sort_keys=True))
            for owner, n in record_nodes(document)[1].items()
            for relation, role, target, attrs in _links(n)
        ]
        actual = [
            (
                e["originals"][side]["owner"],
                e["relation"],
                e["role"],
                e["originals"][side]["target"],
                json.dumps(e["originals"][side]["attributes"], sort_keys=True),
            )
            for e in graph["edges"]
            if side in e["sides"]
        ]
        assert sorted(expected) == sorted(actual)
        assert verify_record(document, document.records[0])["matches"]


def test_open_verify_and_plain_annotations(window, app, native_file):
    original = native_file.read_bytes()
    assert window.open_path(native_file)
    settle(app, window)
    assert len(window.records.documents) == 1
    model = window.records.record.model
    annotation = next(
        n for n in model["nodes"] if "rime:AnnotationSet" in n["originals"]["a"]["@type"]
    )
    window.records.record.graph.choose(annotation["id"])
    text = window.records.record.text.toPlainText()
    assert "10–16 s" in text and "30–36 s" in text
    assert window.records.record.text.isReadOnly()
    window.records.verify()
    settle(app, window)
    assert "matches saved result" in window.statusBar().currentMessage()
    assert native_file.read_bytes() == original


@pytest.mark.parametrize(
    "damage", ["malformed", "missing_reference", "wrong_result", "unsupported", "duplicate_key"]
)
def test_failed_open_preserves_existing_record(window, app, native_file, tmp_path, damage):
    window.open_path(native_file)
    settle(app, window)
    old = window.records.record.model
    payload = json.loads(native_file.read_text())
    if damage == "wrong_result":
        next(n for n in payload["@graph"] if "rime:MeasurementResult" in n["@type"])["rime:data"][
            "value"
        ] = 999
    elif damage == "missing_reference":
        payload["@graph"].pop(0)
    elif damage == "unsupported":
        payload["rime:version"] = "0.1"
    content = "{" if damage == "malformed" else json.dumps(payload)
    if damage == "duplicate_key":
        content = content.replace(
            '"rime:version": "1.1"', '"rime:version": "1.1", "rime:version": "1.1"'
        )
    invalid = tmp_path / "invalid.rime"
    invalid.write_text(content)
    errors = []
    window.records.error.connect(errors.append)
    window.open_path(invalid)
    settle(app, window)
    assert errors and len(window.records.documents) == 1
    assert window.records.record.model is old
    assert window.records.open_button.isEnabled()
    window.error_dialog.accept()


def test_open_cancel_has_no_effect(window, app, native_file, monkeypatch):
    window.open_path(native_file)
    settle(app, window)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    window.open_file()
    assert len(window.records.documents) == 1 and not window.records.busy


def test_multi_measurement_comparison_selection_and_removal(window, app, tmp_path):
    single = examples.synthetic()
    # Add three independent calculations to the same retained annotation basis.
    base = [
        n
        for n in single.nodes.values()
        if not any(
            t in n["@type"]
            for t in (
                "rime:MeasurementResult",
                "rime:MeasurementCalculation",
                "rime:CalculationDefinition",
                "rime:ObservationPeriod",
            )
        )
    ]
    ann = next(n["@id"] for n in base if "rime:AnnotationSet" in n["@type"])
    doc = examples.add_measurements(
        base, ann, [[0, 60000]], ("percentage_coverage", "covered_duration", "count")
    )
    p = tmp_path / "three.rime"
    write_document(p, doc)
    window.open_path(p)
    settle(app, window)
    model = window.records.record.model
    assert (
        len([n for n in model["nodes"] if "rime:MeasurementResult" in n["originals"]["a"]["@type"]])
        == 1
    )
    window.open_path(p)
    settle(app, window)
    assert not window.open_path(p)
    window.records.selectors[1].setCurrentIndex(2)
    settle(app, window)
    graph = window.records.record.model
    assert graph["comparison"] and graph["numerical_comparison"]["status"] == "not_applicable"
    assert window.records.record.graph.isVisible()
    window.records.record.graph.choose(graph["roots"]["b"])
    assert "measurement_definition_differs" in window.records.record.text.toPlainText()
    window.records.remove_buttons[0].click()
    settle(app, window)
    assert window.records.documents[0].selected["root"] == doc.records[2]
    assert not window.records.record.model["comparison"]
    window.records.remove_buttons[0].click()
    assert not window.records.documents and window.records.empty.isVisible()


def test_collapse_keeps_other_records_shared_dependencies(window, app, tmp_path):
    for side, doc in zip("ab", examples.convergence_pair("neither")):
        path = tmp_path / f"neither.{side}.rime"
        write_document(path, doc)
        window.open_path(path)
        settle(app, window)
    model = window.records.record.model
    calc = next(
        n
        for n in model["nodes"]
        if n["sides"] == ["a"] and "rime:MeasurementCalculation" in n["originals"]["a"]["@type"]
    )
    graph = window.records.record.graph
    graph.branch_buttons[calc["id"]].click()
    app.processEvents()
    assert graph.branch_buttons[calc["id"]].text() == "+"
    shared_definition = next(
        n
        for n in model["nodes"]
        if len(n["sides"]) == 2 and "rime:CalculationDefinition" in n["originals"]["a"]["@type"]
    )
    assert shared_definition["id"] in graph.nodes
    graph.expand_all()
    assert set(graph.nodes) == {n["id"] for n in model["nodes"]}


def test_cli_accepts_real_record_path():
    from rime_ui.app import _parse_args

    args, _ = _parse_args(["--open", "/tmp/example.rime"])
    assert args.open == "/tmp/example.rime"


@pytest.mark.parametrize(
    "name",
    [
        "synthetic-manual",
        "synthetic-review",
        "synthetic-model",
        "synthetic-model-review",
        "synthetic-adjudication",
        "synthetic-import",
    ],
)
def test_each_native_route_opens_and_exposes_all_node_details(window, app, name, tmp_path):
    path = tmp_path / (name + ".rime")
    factory = {
        "synthetic-manual": examples.synthetic,
        "synthetic-review": lambda: examples.synthetic(True),
        "synthetic-model": examples.computational,
        "synthetic-model-review": lambda: examples.computational(True),
        "synthetic-adjudication": examples.adjudication,
        "synthetic-import": examples.imported,
    }[name]
    write_document(path, factory())
    window.open_path(path)
    settle(app, window)
    assert len(window.records.documents) == 1
    for i, summary in enumerate(window.records.documents[0].summaries):
        window.records.selectors[0].setCurrentIndex(i)
        settle(app, window)
        graph = window.records.record.graph
        for node in window.records.record.model["nodes"]:
            graph.choose(node["id"])
            assert node["originals"]["a"]["@id"] in window.records.record.text.toPlainText()


def test_close_during_background_load_does_not_admit_result(app, native_file, monkeypatch):
    import threading
    from rime_ui.presentation import records

    finished, release = threading.Event(), threading.Event()
    original = records.load_document

    def delayed(path):
        release.wait(5)
        try:
            return original(path)
        finally:
            finished.set()

    monkeypatch.setattr(records, "load_document", delayed)
    w = RecordWindow()
    w.show()
    w.open_path(native_file)
    w.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    release.set()
    assert finished.wait(5)
    app.processEvents()
