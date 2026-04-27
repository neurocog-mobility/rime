"""Grouped model packaging and inference API."""

from rime_core.cmf import (
    CMFConfig,
    CMFLoader,
    CMFMissingRequirement,
    CMFPackage,
    CMFRequirement,
    CMFValidationError,
)
from rime_core.inference import (
    InferenceError,
    InferenceResult,
    InferenceRunner,
    InputBinding,
    OutputMapping,
    OutputPredictions,
    VideoInput,
)

__all__ = [
    "CMFConfig",
    "CMFLoader",
    "CMFMissingRequirement",
    "CMFPackage",
    "CMFRequirement",
    "CMFValidationError",
    "InferenceError",
    "InferenceResult",
    "InferenceRunner",
    "InputBinding",
    "OutputMapping",
    "OutputPredictions",
    "VideoInput",
]
