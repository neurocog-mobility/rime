from __future__ import annotations

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.rule_engine import RuleEngine
from rime_core.schema import ProtocolSchema


def _engine() -> RuleEngine:
    return RuleEngine(ProtocolSchema.default())


def test_auto_create_on_fog() -> None:
    store = AnnotationStore()
    fog = Annotation(id="f1", lane="FOG", label="FOG", start_ms=100, end_ms=500)
    store.add(fog)

    side_effects, violations = _engine().on_create(fog, store)
    assert not violations
    lanes = {effect.annotation.lane for effect in side_effects}
    assert lanes == {"Core", "Manifestations"}


def test_ghost_flag() -> None:
    store = AnnotationStore()
    fog = Annotation(id="f1", lane="FOG", label="FOG", start_ms=100, end_ms=500)
    store.add(fog)

    side_effects, _ = _engine().on_create(fog, store)
    by_lane = {effect.annotation.lane: effect.annotation for effect in side_effects}
    assert by_lane["Manifestations"].ghost is True
    assert by_lane["Core"].ghost is True


def test_auto_create_source() -> None:
    store = AnnotationStore()
    fog = Annotation(id="f1", lane="FOG", label="FOG", start_ms=100, end_ms=500)
    store.add(fog)

    side_effects, _ = _engine().on_create(fog, store)
    assert all(effect.annotation.source == "rule:auto_create" for effect in side_effects)


def test_must_be_subset_of() -> None:
    store = AnnotationStore()
    core = Annotation(id="c1", lane="Core", label="Core", start_ms=100, end_ms=400)

    _, violations = _engine().on_create(core, store)
    assert any(v.rule_action == "must_be_subset_of" for v in violations)


def test_must_be_subset_of_passes() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="f1", lane="FOG", label="FOG", start_ms=0, end_ms=500))
    core = Annotation(id="c1", lane="Core", label="Core", start_ms=100, end_ms=400)

    _, violations = _engine().on_create(core, store)
    assert not any(v.rule_action == "must_be_subset_of" for v in violations)


def test_must_not_overlap() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="f1", lane="FOG", label="FOG", start_ms=0, end_ms=1000))
    store.add(
        Annotation(
            id="x1",
            lane="Festination",
            label="propulsion",
            start_ms=300,
            end_ms=500,
        )
    )
    core = Annotation(id="c1", lane="Core", label="Core", start_ms=200, end_ms=600)

    _, violations = _engine().on_create(core, store)
    overlap = [v for v in violations if v.rule_action == "must_not_overlap"]
    assert overlap
    assert overlap[0].can_auto_fix is True


def test_must_not_overlap_passes() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="f1", lane="FOG", label="FOG", start_ms=0, end_ms=1000))
    store.add(
        Annotation(
            id="x1",
            lane="Festination",
            label="propulsion",
            start_ms=700,
            end_ms=900,
        )
    )
    core = Annotation(id="c1", lane="Core", label="Core", start_ms=200, end_ms=600)

    _, violations = _engine().on_create(core, store)
    assert not any(v.rule_action == "must_not_overlap" for v in violations)


def test_coincidence_violation() -> None:
    store = AnnotationStore()
    store.add(
        Annotation(
            id="m1",
            lane="Manifestations",
            label="Akinetic",
            start_ms=100,
            end_ms=200,
        )
    )

    violations = _engine().validate(store)
    assert violations
    assert violations[0].rule_action == "coincidence"
    assert violations[0].can_auto_fix is True
    assert violations[0].fix_annotation is not None


def test_coincidence_passes() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="c1", lane="Core", label="Core", start_ms=0, end_ms=300))
    store.add(
        Annotation(
            id="m1",
            lane="Manifestations",
            label="Akinetic",
            start_ms=100,
            end_ms=200,
        )
    )

    violations = _engine().validate(store)
    assert not violations


def test_on_import_batch() -> None:
    store = AnnotationStore()
    store.add(Annotation(id="f1", lane="FOG", label="FOG", start_ms=0, end_ms=100))
    store.add(Annotation(id="f2", lane="FOG", label="FOG", start_ms=200, end_ms=300))

    side_effects, _ = _engine().on_import(store)
    assert len(side_effects) == 4
    assert len(store.get_by_lane("Core")) == 2
    assert len(store.get_by_lane("Manifestations")) == 2
