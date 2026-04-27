"""Grouped annotation-domain API."""

from rime_core.annotation_ops import edit_annotation_label, split_annotation
from rime_core.annotations import Annotation, AnnotationStore, generate_id
from rime_core.review import ReviewLayer, load_review_layer
from rime_core.rule_engine import RuleEngine, SideEffect, Violation

__all__ = [
    "Annotation",
    "AnnotationStore",
    "ReviewLayer",
    "RuleEngine",
    "SideEffect",
    "Violation",
    "edit_annotation_label",
    "generate_id",
    "load_review_layer",
    "split_annotation",
]
