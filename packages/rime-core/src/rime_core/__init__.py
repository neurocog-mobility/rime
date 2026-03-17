"""Core data models, loaders, and rule/import utilities."""

from rime_core.annotations import Annotation, AnnotationStore, generate_id
from rime_core.annotation_ops import edit_annotation_label, split_annotation
from rime_core.cmf import CMFConfig, CMFLoader, CMFPackage, CMFValidationError
from rime_core.coverage import CoverageResult, CoverageSpec, compute_coverage
from rime_core.context import WorkingContext
from rime_core.evaluation import EvalResult, evaluate_model
from rime_core.elan_import import (
    ImportResult,
    TierMapping,
    auto_map_tiers,
    extract_media_files,
    import_eaf,
    import_session_from_elan,
    normalize_label,
)
from rime_core.export import (
    ExportError,
    ExporterRegistry,
    export_irr_report,
    export_parquet,
    export_session_report,
    export_signal_clips,
    export_video_clips,
)
from rime_core.irr import IRRLabelResult, IRRResult, compute_irr
from rime_core.inference import InferenceError, InferenceResult, InferenceRunner
from rime_core.inference import InputBinding, OutputMapping, OutputPredictions
from rime_core.loaders import SignalLoaderError, SignalLoaderRegistry
from rime_core.review import ReviewLayer, load_review_layer
from rime_core.rule_engine import RuleEngine, SideEffect, Violation
from rime_core.schema import (
    LaneSchema,
    ProtocolSchema,
    SchemaValidationError,
    suggest_next_schema_version,
)
from rime_core.settings import AppSettings, load_settings, save_settings
from rime_core.session import (
    ModelSettings,
    ClinicalMetricSpec,
    DEFAULT_PANEL_VISIBILITY,
    MAX_SESSION_VIDEOS,
    normalize_session_videos,
    Session,
    SessionProvenance,
    SignalConfig,
    SubjectInfo,
    VideoConfig,
    create_session,
    load_session,
    save_session,
)
from rime_core.signals import Signal, detect_signal_config, load_csv_signal

__all__ = [
    "Annotation",
    "AnnotationStore",
    "generate_id",
    "split_annotation",
    "edit_annotation_label",
    "CMFConfig",
    "CMFPackage",
    "CMFLoader",
    "CMFValidationError",
    "CoverageSpec",
    "CoverageResult",
    "compute_coverage",
    "InferenceResult",
    "InferenceRunner",
    "InferenceError",
    "InputBinding",
    "OutputMapping",
    "OutputPredictions",
    "LaneSchema",
    "ProtocolSchema",
    "SignalLoaderRegistry",
    "SignalLoaderError",
    "SchemaValidationError",
    "suggest_next_schema_version",
    "AppSettings",
    "load_settings",
    "save_settings",
    "WorkingContext",
    "EvalResult",
    "evaluate_model",
    "IRRLabelResult",
    "IRRResult",
    "compute_irr",
    "ExporterRegistry",
    "ExportError",
    "export_irr_report",
    "export_parquet",
    "export_session_report",
    "export_signal_clips",
    "export_video_clips",
    "ReviewLayer",
    "load_review_layer",
    "RuleEngine",
    "SideEffect",
    "Violation",
    "TierMapping",
    "ImportResult",
    "auto_map_tiers",
    "normalize_label",
    "extract_media_files",
    "import_eaf",
    "import_session_from_elan",
    "Session",
    "ModelSettings",
    "ClinicalMetricSpec",
    "DEFAULT_PANEL_VISIBILITY",
    "MAX_SESSION_VIDEOS",
    "normalize_session_videos",
    "SessionProvenance",
    "VideoConfig",
    "SignalConfig",
    "SubjectInfo",
    "create_session",
    "save_session",
    "load_session",
    "Signal",
    "detect_signal_config",
    "load_csv_signal",
]
