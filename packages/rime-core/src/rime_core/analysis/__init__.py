"""Grouped analysis and QA helpers."""

from rime_core.coverage import CoverageResult, CoverageSpec, compute_coverage
from rime_core.evaluation import EvalResult, evaluate_model, evaluate_point_events
from rime_core.irr import IRRLabelResult, IRRResult, compute_irr, format_irr_value

__all__ = [
    "CoverageResult",
    "CoverageSpec",
    "EvalResult",
    "IRRLabelResult",
    "IRRResult",
    "compute_coverage",
    "compute_irr",
    "evaluate_model",
    "evaluate_point_events",
    "format_irr_value",
]
