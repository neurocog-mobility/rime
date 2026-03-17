"""Annotation editing operations."""

from __future__ import annotations

from dataclasses import replace

from rime_core.annotations import AnnotationStore, generate_id


def split_annotation(
    store: AnnotationStore, ann_id: str, split_ms: float
) -> tuple | None:
    """Split one annotation at a given time, replacing it with two siblings."""
    ann = store.get(ann_id)
    if ann is None:
        return None
    if split_ms <= ann.start_ms or split_ms >= ann.end_ms:
        return None

    left = replace(ann, id=generate_id(), start_ms=ann.start_ms, end_ms=split_ms)
    right = replace(ann, id=generate_id(), start_ms=split_ms, end_ms=ann.end_ms)

    store.remove(ann_id)
    store.add(left)
    store.add(right)
    return left, right


def edit_annotation_label(store: AnnotationStore, ann_id: str, new_label: str) -> bool:
    """Update label text for an existing annotation."""
    ann = store.get(ann_id)
    text = new_label.strip()
    if ann is None or not text:
        return False
    ann.label = text
    return True
