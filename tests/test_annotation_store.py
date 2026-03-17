from __future__ import annotations

from pathlib import Path

from rime_core.annotations import Annotation, AnnotationStore


def test_add_remove() -> None:
    store = AnnotationStore()
    ann = Annotation(id="a1", lane="Tasks", label="Walk", start_ms=0, end_ms=1000)

    store.add(ann)
    assert store.get("a1") == ann

    store.remove("a1")
    assert store.get("a1") is None


def test_get_by_lane() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="Tasks", label="Walk", start_ms=0, end_ms=1000))
    store.add(Annotation(id="a2", lane="FOG", label="FOG", start_ms=10, end_ms=20))

    result = store.get_by_lane("FOG")
    assert [ann.id for ann in result] == ["a2"]


def test_get_at_time() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="Tasks", label="Walk", start_ms=0, end_ms=1000))
    store.add(Annotation(id="a2", lane="FOG", label="FOG", start_ms=500, end_ms=1500))

    at_750 = store.get_at_time(750)
    assert {ann.id for ann in at_750} == {"a1", "a2"}

    fog_only = store.get_at_time(750, lane_name="FOG")
    assert [ann.id for ann in fog_only] == ["a2"]


def test_get_overlapping() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="a1", lane="Tasks", label="Walk", start_ms=0, end_ms=1000))
    store.add(Annotation(id="a2", lane="Tasks", label="Turns", start_ms=1200, end_ms=1800))
    store.add(Annotation(id="a3", lane="FOG", label="FOG", start_ms=900, end_ms=1300))

    overlaps = store.get_overlapping(800, 1250)
    assert {ann.id for ann in overlaps} == {"a1", "a2", "a3"}

    tasks_only = store.get_overlapping(800, 1250, lane_name="Tasks")
    assert {ann.id for ann in tasks_only} == {"a1", "a2"}


def test_serialization_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "annotations.json"

    store = AnnotationStore()
    store._session_id = "s1"
    store._session_name = "Session 1"
    store.add(
        Annotation(
            id="a1",
            lane="Manifestations",
            label="Akinetic",
            start_ms=100,
            end_ms=400,
            event_type="point",
            source="rule:auto_create",
            ghost=True,
            confidence=0.72,
            human_modified=True,
            origin_confidence=0.81,
            origin_start_ms=95.0,
            origin_end_ms=410.0,
        )
    )
    store.save(path)

    loaded = AnnotationStore.load(path)
    loaded_ann = loaded.get("a1")
    assert loaded_ann is not None
    assert loaded_ann.lane == "Manifestations"
    assert loaded_ann.event_type == "point"
    assert loaded_ann.ghost is True
    assert loaded_ann.source == "rule:auto_create"
    assert loaded_ann.confidence == 0.72
    assert loaded_ann.human_modified is True
    assert loaded_ann.origin_confidence == 0.81
    assert loaded_ann.origin_start_ms == 95.0
    assert loaded_ann.origin_end_ms == 410.0
    assert loaded._session_id == "s1"
    assert loaded._session_name == "Session 1"


def test_load_defaults_confidence_to_one(tmp_path: Path) -> None:
    path = tmp_path / "annotations.json"
    path.write_text(
        (
            '{'
            '"version":"1.0",'
            '"session":{"id":"s1","name":"Session 1"},'
            '"annotations":[{"id":"a1","lane":"FOG","label":"FOG","start_ms":0,"end_ms":10}]'
            '}'
        ),
        encoding="utf-8",
    )

    loaded = AnnotationStore.load(path)
    loaded_ann = loaded.get("a1")
    assert loaded_ann is not None
    assert loaded_ann.event_type == "interval"
    assert loaded_ann.confidence == 1.0
    assert loaded_ann.human_modified is False
    assert loaded_ann.origin_confidence is None
    assert loaded_ann.origin_start_ms is None
    assert loaded_ann.origin_end_ms is None
