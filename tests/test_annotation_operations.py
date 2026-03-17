from __future__ import annotations

from rime_core.annotation_ops import edit_annotation_label, split_annotation
from rime_core.annotations import Annotation, AnnotationStore


def _make_store() -> AnnotationStore:
    store = AnnotationStore()
    store.add(
        Annotation(
            id="ann1",
            lane="Tasks",
            label="Walk",
            start_ms=1000,
            end_ms=5000,
            source="manual",
            ghost=False,
            confidence=0.8,
        )
    )
    return store


def test_split_annotation() -> None:
    store = _make_store()

    result = split_annotation(store, "ann1", 3000)
    assert result is not None

    left, right = result
    assert left.start_ms == 1000
    assert left.end_ms == 3000
    assert right.start_ms == 3000
    assert right.end_ms == 5000
    assert left.lane == "Tasks"
    assert right.label == "Walk"
    assert left.confidence == 0.8
    assert right.confidence == 0.8
    assert left.event_type == "interval"
    assert right.event_type == "interval"


def test_split_preserves_store() -> None:
    store = _make_store()

    result = split_annotation(store, "ann1", 3000)
    assert result is not None
    left, right = result

    assert store.get("ann1") is None
    assert store.get(left.id) is not None
    assert store.get(right.id) is not None
    assert len(store.annotations) == 2


def test_split_at_boundary() -> None:
    store = _make_store()

    assert split_annotation(store, "ann1", 1000) is None
    assert split_annotation(store, "ann1", 5000) is None
    assert len(store.annotations) == 1
    assert store.get("ann1") is not None


def test_edit_annotation_label() -> None:
    store = _make_store()
    changed = edit_annotation_label(store, "ann1", "  Specific note text  ")
    assert changed is True

    ann = store.get("ann1")
    assert ann is not None
    assert ann.label == "Specific note text"


def test_split_preserves_event_type() -> None:
    store = AnnotationStore()
    store.add(
        Annotation(
            id="ann1",
            lane="Tasks",
            label="Walk",
            start_ms=1000,
            end_ms=5000,
            event_type="point",
        )
    )

    result = split_annotation(store, "ann1", 3000)
    assert result is not None

    left, right = result
    assert left.event_type == "point"
    assert right.event_type == "point"


def test_split_preserves_provenance_fields() -> None:
    store = AnnotationStore()
    store.add(
        Annotation(
            id="ann1",
            lane="Tasks",
            label="Walk",
            start_ms=1000,
            end_ms=5000,
            source="model:demo",
            confidence=0.8,
            human_modified=True,
            origin_confidence=0.9,
            origin_start_ms=900.0,
            origin_end_ms=5100.0,
        )
    )

    result = split_annotation(store, "ann1", 3000)
    assert result is not None

    left, right = result
    assert left.human_modified is True
    assert right.human_modified is True
    assert left.origin_confidence == 0.9
    assert right.origin_confidence == 0.9
    assert left.origin_start_ms == 900.0
    assert right.origin_end_ms == 5100.0
