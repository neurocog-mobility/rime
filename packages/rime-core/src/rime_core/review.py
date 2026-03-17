"""External review-layer loading helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rime_core.annotations import Annotation, AnnotationStore


ReviewMode = Literal["pending", "reference"]


@dataclass
class ReviewLayer:
    """A named set of external annotations loaded for comparison or resolution."""

    source: str
    mode: ReviewMode
    annotations: list[Annotation]
    label: str


def load_review_layer(
    store: AnnotationStore,
    layer: ReviewLayer,
) -> list[Annotation]:
    """Load external annotations into the working store or defer unsupported modes."""
    if layer.mode == "pending":
        for annotation in layer.annotations:
            annotation.ghost = True
            store.add(annotation)
        return layer.annotations

    if layer.mode == "reference":
        raise NotImplementedError("Reference layer mode is not yet implemented")

    raise ValueError(f"Unsupported review mode: {layer.mode}")
