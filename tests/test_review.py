from __future__ import annotations

from rime_core import Annotation, AnnotationStore, ReviewLayer, load_review_layer


def test_pending_review_layer_adds_annotations_as_ghosts() -> None:
    store = AnnotationStore()
    annotations = [
        Annotation(
            id="a1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=300.0,
            source="model:freeze-index",
            ghost=False,
        ),
        Annotation(
            id="a2",
            lane="Manifestations",
            label="Akinetic",
            start_ms=120.0,
            end_ms=280.0,
            source="rater:user_a",
            ghost=False,
        ),
    ]
    layer = ReviewLayer(
        source="model:freeze-index",
        mode="pending",
        annotations=annotations,
        label="Freeze Index",
    )

    loaded = load_review_layer(store, layer)

    assert loaded == annotations
    assert store.get("a1") is not None
    assert store.get("a2") is not None
    assert store.get("a1").ghost is True
    assert store.get("a2").ghost is True


def test_pending_review_layer_preserves_source_verbatim() -> None:
    store = AnnotationStore()
    annotation = Annotation(
        id="a1",
        lane="FOG",
        label="FOG",
        start_ms=100.0,
        end_ms=300.0,
        source="gold_standard",
    )
    layer = ReviewLayer(
        source="gold_standard",
        mode="pending",
        annotations=[annotation],
        label="Gold Standard",
    )

    load_review_layer(store, layer)

    assert store.get("a1") is not None
    assert store.get("a1").source == "gold_standard"
