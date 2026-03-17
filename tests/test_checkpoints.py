from __future__ import annotations

from pathlib import Path

from rime_core.annotations import Annotation, AnnotationStore
from rime_core.checkpoints import (
    KIND_MANUAL,
    KIND_PRE_DESTRUCTIVE,
    KIND_RESTORE_GUARD,
    KIND_SESSION_OPEN,
    create_checkpoint,
    list_checkpoints,
    load_checkpoint,
)


def _store() -> AnnotationStore:
    store = AnnotationStore()
    store._session_id = "ses-123"
    store._session_name = "Demo"
    store.add(
        Annotation(
            id="a1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=200.0,
            source="manual",
        )
    )
    return store


def test_checkpoint_round_trip_includes_annotations_and_ui_state(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    entry = create_checkpoint(
        session_dir,
        _store(),
        label="Manual checkpoint",
        kind=KIND_MANUAL,
        snap_points=[125.0, 500.0],
        loop_region=(50.0, 250.0),
    )

    checkpoints = list_checkpoints(session_dir)
    assert checkpoints[0].id == entry.id

    snapshot = load_checkpoint(session_dir, entry.id)
    assert snapshot.entry.label == "Manual checkpoint"
    assert [annotation.id for annotation in snapshot.store.all()] == ["a1"]
    assert snapshot.snap_points == [125.0, 500.0]
    assert snapshot.loop_region == (50.0, 250.0)


def test_pre_destructive_checkpoints_are_capped(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    for index in range(12):
        create_checkpoint(
            session_dir,
            _store(),
            label=f"Clear {index}",
            kind=KIND_PRE_DESTRUCTIVE,
        )

    checkpoints = [entry for entry in list_checkpoints(session_dir) if entry.kind == KIND_PRE_DESTRUCTIVE]
    assert len(checkpoints) == 10


def test_restore_guard_checkpoints_have_separate_small_cap(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    create_checkpoint(session_dir, _store(), label="Session opened", kind=KIND_SESSION_OPEN)
    create_checkpoint(session_dir, _store(), label="Manual", kind=KIND_MANUAL)
    for index in range(3):
        create_checkpoint(
            session_dir,
            _store(),
            label=f"Before restore {index}",
            kind=KIND_RESTORE_GUARD,
        )

    checkpoints = list_checkpoints(session_dir)
    restore_guards = [entry for entry in checkpoints if entry.kind == KIND_RESTORE_GUARD]
    assert len(restore_guards) == 2
    assert any(entry.kind == KIND_SESSION_OPEN for entry in checkpoints)
    assert any(entry.kind == KIND_MANUAL for entry in checkpoints)
