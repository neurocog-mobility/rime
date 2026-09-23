"""Application operations on native scientific objects and a local workspace."""

from __future__ import annotations

import copy
import logging
import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rime_core.annotations import Annotation, AnnotationStore, ConfidenceType, generate_id
from rime_core.measurements import MeasurementDefinition, MeasurementRecord
from rime_core.records.revisions import CapturedRevision
from rime_core.cmf import CMFLoader, CMFPackage
from rime_core.common.time import time_values_to_seconds
from rime_core.io.exporters import ExporterRegistry
from rime_core.inference import (
    InferenceError,
    InferenceResult,
    InferenceRunner,
    InputBinding,
    OutputMapping,
)
from rime_core.loaders import SignalLoaderRegistry
from rime_core.records import (
    AnnotationSet,
    CalculationTemplate,
    RecordingCatalog,
    ResearchContext,
    SignalSource,
    VideoSource,
)
from rime_core.rule_engine import RuleEngine, Violation
from rime_core.schema import ProtocolSchema
from rime_core.signals import Signal
from rime_core.workspace.models import WorkspaceSession, MAX_VIDEO_VIEWS, SignalSelection
from rime_core.workspace.storage import (
    copy_workspace,
    load_workspace,
    save_workspace,
    require_empty_destination,
)

logger = logging.getLogger(__name__)
ContextCallback = Callable[..., None]


def _confidence_type_for_source(source: str) -> ConfidenceType:
    if source.startswith(("model:", "corrected:")):
        return "model_probability"
    return "human_rating" if source == "manual" else "not_recorded"


@dataclass
class WorkingContext:
    """Coordinates editing; each object retains its own bounded responsibility."""

    workspace: WorkspaceSession
    research: ResearchContext
    recordings: RecordingCatalog
    annotation_set: AnnotationSet
    calculation_templates: list[CalculationTemplate] = field(default_factory=list)
    measurements: list[MeasurementRecord] = field(default_factory=list)
    signals: dict[str, Signal] = field(default_factory=dict)
    loaded_models: dict[str, CMFPackage] = field(default_factory=dict)
    loader_registry: SignalLoaderRegistry = field(default_factory=SignalLoaderRegistry.default)
    exporter_registry: ExporterRegistry = field(default_factory=ExporterRegistry.default)
    _callbacks: dict[str, list[ContextCallback]] = field(default_factory=lambda: defaultdict(list))

    @property
    def store(self) -> AnnotationStore:
        return self.annotation_set.annotations

    @property
    def schema(self) -> ProtocolSchema:
        return self.annotation_set.protocol

    @property
    def rule_engine(self) -> RuleEngine:
        return RuleEngine(self.schema)

    @classmethod
    def open(
        cls, path: str | Path, *, loader_registry: SignalLoaderRegistry | None = None
    ) -> WorkingContext:
        workspace, research, recordings, annotation_set, templates, measurements = load_workspace(path)
        context = cls(
            workspace,
            research,
            recordings,
            annotation_set,
            templates,
            measurements,
            loader_registry=loader_registry or SignalLoaderRegistry.default(),
        )
        context.reload_signals()
        return context

    @classmethod
    def create_workspace(
        cls,
        directory: Path | str,
        name: str,
        *,
        schema: ProtocolSchema | None = None,
        videos: list[tuple[Path | str, VideoSource]] | None = None,
        signals: list[SignalSelection] | None = None,
        research: ResearchContext | None = None,
        rater: str = "",
        loader_registry: SignalLoaderRegistry | None = None,
    ) -> WorkingContext:
        directory = Path(directory).expanduser().resolve()
        require_empty_destination(directory)
        recordings = RecordingCatalog()
        context = cls(
            WorkspaceSession(directory, name.strip() or directory.name),
            research or ResearchContext(),
            recordings,
            AnnotationSet(recordings.timeline.id, schema or ProtocolSchema.default(), rater=rater),
            loader_registry=loader_registry or SignalLoaderRegistry.default(),
        )
        for path, source in videos or []:
            context.add_video(path, copy.deepcopy(source))
        for selection in signals or []:
            source = context.add_signal(selection.path, copy.deepcopy(selection.source))
            context.workspace.view.display_channels[source.id] = list(selection.display_channels)
        context.save()
        context.reload_signals()
        return context

    def save_workspace_copy(self, destination: Path | str) -> WorkingContext:
        return copy_workspace(self, destination)

    def current_revision(self) -> CapturedRevision:
        return CapturedRevision.capture(self.research, self.recordings, self.annotation_set)

    def capture_measurement(self, definition: MeasurementDefinition) -> MeasurementRecord:
        record = MeasurementRecord.capture(self.current_revision(), definition)
        self.measurements.append(record)
        try:
            self.save()
        except Exception:
            self.measurements.remove(record)
            raise
        self._emit("measurements_changed", self.measurements)
        return record

    def add_video(self, path: Path | str, source: VideoSource | None = None) -> VideoSource:
        resolved = (self.workspace.root / Path(path).expanduser()).resolve()
        for existing in self.recordings.videos:
            if self.workspace.source_path(existing.id) == resolved:
                return existing
        if len(self.recordings.videos) >= MAX_VIDEO_VIEWS:
            raise ValueError("The desktop supports two video views.")
        source = source or VideoSource()
        source.file_name = resolved.name
        source.role = "primary" if not self.recordings.videos else "secondary"
        self.recordings.videos.append(source)
        self.workspace.source_locations[source.id] = str(resolved)
        return source

    def add_signal(self, path: Path | str, source: SignalSource) -> SignalSource:
        resolved = (self.workspace.root / Path(path).expanduser()).resolve()
        for existing in self.recordings.signals:
            if self.workspace.source_path(existing.id) == resolved:
                return existing
        source.file_name = resolved.name
        self.recordings.signals.append(source)
        self.workspace.source_locations[source.id] = str(resolved)
        return source

    def subscribe(self, event: str, callback: ContextCallback) -> None:
        """Subscribe to context events."""
        self._callbacks[event].append(callback)

    @property
    def loaded_model(self) -> CMFPackage | None:
        if not self.loaded_models:
            return None
        return next(iter(self.loaded_models.values()))

    @loaded_model.setter
    def loaded_model(self, package: CMFPackage | None) -> None:
        if package is None:
            self.loaded_models.clear()
            return
        self.loaded_models = {package.name: package}

    def create_annotation(
        self,
        lane: str,
        label: str,
        start_ms: float,
        end_ms: float,
        *,
        source: str = "manual",
        ghost: bool = False,
        confidence: float = 1.0,
        confidence_type: ConfidenceType | None = None,
    ) -> tuple[Annotation, list[Violation]]:
        """Create one annotation, apply rule side effects, and emit callbacks."""
        is_point_lane = self.schema.is_point_lane(lane)
        if is_point_lane:
            start_ms = end_ms = start_ms
        annotation = Annotation(
            id=generate_id(),
            lane=lane,
            label=label,
            start_ms=start_ms,
            end_ms=end_ms,
            event_type="point" if is_point_lane else "interval",
            source=source,
            ghost=ghost,
            confidence=confidence,
            confidence_type=confidence_type or _confidence_type_for_source(source),
        )
        side_effects, violations = self.rule_engine.on_create(annotation, self.store)
        self.store.add(annotation)
        for effect in side_effects:
            self.store.add(effect.annotation)

        self._autosave()
        self._emit("store_changed", self.store)
        if violations:
            self._emit("violations", violations)
        return annotation, violations

    def accept_ghost(self, ann_id: str) -> tuple[Annotation, list[Violation]]:
        """Accept a ghost annotation and run rules on the accepted annotation."""
        annotation = self.store.get(ann_id)
        if annotation is None:
            raise KeyError(f"Annotation '{ann_id}' not found")
        if not annotation.ghost:
            raise ValueError(f"Annotation '{ann_id}' is not a ghost")

        if annotation.source.startswith("model:"):
            annotation.source = annotation.source.replace("model:", "corrected:", 1)
        annotation.ghost = False
        side_effects, violations = self.rule_engine.on_create(annotation, self.store)
        for effect in side_effects:
            self.store.add(effect.annotation)
        self._autosave()
        self._emit("store_changed", self.store)
        if violations:
            self._emit("violations", violations)
        return annotation, violations

    def reject_ghost(self, ann_id: str) -> None:
        """Reject and remove a ghost annotation."""
        annotation = self.store.get(ann_id)
        if annotation is None:
            raise KeyError(f"Annotation '{ann_id}' not found")
        if not annotation.ghost:
            raise ValueError(f"Annotation '{ann_id}' is not a ghost")

        self.store.remove(ann_id)
        self._autosave()
        self._emit("store_changed", self.store)

    def delete_annotation(self, ann_id: str) -> None:
        """Delete any annotation from the store."""
        if self.store.get(ann_id) is None:
            raise KeyError(f"Annotation '{ann_id}' not found")
        self.store.remove(ann_id)
        self._autosave()
        self._emit("store_changed", self.store)

    def edit_annotation(
        self,
        ann_id: str,
        *,
        label: str | None = None,
        start_ms: float | None = None,
        end_ms: float | None = None,
        confidence: float | None = None,
    ) -> Annotation:
        """Edit a stored annotation in place and persist the change."""
        annotation = self.store.get(ann_id)
        if annotation is None:
            raise KeyError(f"Annotation '{ann_id}' not found")

        if annotation.source != "manual" and any(
            value is not None for value in (label, start_ms, end_ms, confidence)
        ):
            annotation.human_modified = True

        if label is not None:
            annotation.label = label
        if start_ms is not None:
            annotation.start_ms = start_ms
        if end_ms is not None:
            annotation.end_ms = end_ms
        if annotation.event_type == "point" or self.schema.is_point_lane(annotation.lane):
            point_time = annotation.start_ms if start_ms is not None else annotation.end_ms
            annotation.start_ms = point_time
            annotation.end_ms = point_time
            annotation.event_type = "point"
        if confidence is not None:
            annotation.confidence = max(0.0, min(1.0, confidence))
            annotation.confidence_type = "human_rating"

        self._autosave()
        self._emit("store_changed", self.store)
        return annotation

    def validate(self) -> list[Violation]:
        """Run the rule engine validation pass."""
        return self.rule_engine.validate(self.store)

    def save(self) -> None:
        """Atomically save native scientific objects and local workspace state."""
        save_workspace(self)

    def replace_store(self, store: AnnotationStore) -> None:
        """Replace the live annotation store and persist it."""
        self.annotation_set.annotations = store
        self._autosave()
        self._emit("store_changed", self.store)

    def update_clinical_metrics(self, metrics: list[CalculationTemplate]) -> None:
        """Persist the working calculation templates."""
        self.calculation_templates = list(metrics)
        self.save()

    def export(
        self,
        format_name: str,
        output_path: Path | str,
        *,
        include_ghost: bool = False,
    ) -> None:
        """Export annotations through the registered external exporter."""
        self.exporter_registry.export(
            format_name,
            self.store,
            self,
            Path(output_path),
            include_ghost,
        )

    def load_model(self, path: Path | str) -> CMFPackage:
        """Load a CMF package into the in-memory registry."""
        package = CMFLoader.load(path)
        return self.register_model_package(package)

    def register_model_package(self, package: CMFPackage) -> CMFPackage:
        """Register an already-loaded CMF package in the in-memory registry."""
        self.loaded_models[package.name] = package
        self._emit("model_loaded", package)
        return package

    def unload_model(self, model_name: str) -> None:
        """Unload one model from the in-memory registry."""
        if model_name not in self.loaded_models:
            raise KeyError(f"Model '{model_name}' is not loaded")
        self.loaded_models.pop(model_name)
        self._emit("model_unloaded", model_name)

    def check_signal_compatibility(
        self,
        input_name: str,
        signal: Signal,
        *,
        model_name: str | None = None,
    ) -> list[str]:
        """Check whether a signal satisfies one model input contract."""
        package = self._resolve_model(model_name)
        if package is None:
            return ["No model loaded"]

        input_configs = {cfg["name"]: cfg for cfg in package.config.inputs}
        if input_name not in input_configs:
            return [f"Model has no input named '{input_name}'"]

        config = input_configs[input_name]
        errors: list[str] = []
        required_channels = list(config.get("channels", []))
        missing = [channel for channel in required_channels if channel not in signal.channels]
        if missing:
            errors.append(f"Signal missing required channels: {', '.join(sorted(missing))}")

        expected_rate = config.get("sampling_rate_hz") or config.get("sample_rate_hz")
        if expected_rate is not None and signal.sampling_rate_hz != float(expected_rate):
            errors.append(
                f"Sampling rate mismatch: signal is {signal.sampling_rate_hz}Hz, "
                f"model requires {float(expected_rate)}Hz"
            )
        return errors

    def run_inference(
        self,
        input_bindings: list[InputBinding],
        output_mappings: list[OutputMapping],
        *,
        model_name: str | None = None,
        params: dict[str, Any] | None = None,
        time_range: tuple[float, float] | None = None,
    ) -> InferenceResult:
        """Run inference with the loaded model and add ghost annotations to the store."""
        package = self._resolve_model(model_name)
        if package is None:
            raise InferenceError("No model loaded. Call load_model() first.")

        result = InferenceRunner(
            package,
            input_bindings,
            output_mappings,
            params=params,
        ).run(time_range=time_range)
        for annotation in result.annotations:
            self.store.add(annotation)
        self._autosave()
        self._emit("store_changed", self.store)
        self._emit("inference_complete", result)
        return result

    def _emit(self, event: str, *args: Any) -> None:
        for callback in self._callbacks.get(event, []):
            callback(*args)

    def _autosave(self) -> None:
        self.save()

    def set_source_offset(self, source_type: str, source_id: str, offset_ms: float) -> None:
        """Persist a manual offset update for a signal or video source."""
        resolved_offset = float(offset_ms)
        if not math.isfinite(resolved_offset):
            raise ValueError("Offset must be finite.")
        if source_type == "signal":
            config = self._find_signal_config(source_id)
            if config is None:
                raise KeyError(f"Signal '{source_id}' not found")
            config.offset_ms = resolved_offset
            config.sync_method = "manual"
            self._update_loaded_signal_offset(config)
            self._autosave()
            self._emit("signals_changed", self.signals)
            return
        if source_type == "video":
            config = self._find_video_config(source_id)
            if config is None:
                raise KeyError(f"Video '{source_id}' not found")
            config.offset_ms = resolved_offset
            config.sync_method = "manual"
            self._autosave()
            self._emit("recordings_changed", self.recordings)
            return
        raise ValueError(f"Unsupported source type '{source_type}'")

    def _resolve_model(self, model_name: str | None) -> CMFPackage | None:
        if model_name is None:
            return self.loaded_model
        return self.loaded_models.get(model_name)

    def reload_signals(self) -> None:
        self.signals = {}
        for source in self.recordings.signals:
            path = self.workspace.source_path(source.id)
            if path is None:
                continue
            try:
                signal = self.loader_registry.load(path, source)
                signal.source_id = source.id
                signal.name = source.name or signal.name
                self.apply_time_alignment(signal, source)
                self.signals[source.id] = signal
            except Exception as exc:
                logger.warning("Could not load signal '%s': %s", source.file_name, exc)

    def apply_time_alignment(self, signal: Signal, source: SignalSource) -> None:
        if source.time_reference != "utc_epoch":
            signal.offset_ms = source.offset_ms
            return
        origin = self.recordings.timeline.origin_utc
        if not origin:
            logger.warning(
                "UTC signal %s has no timeline origin; using its first sample", source.file_name
            )
            signal.offset_ms = source.offset_ms
            return
        origin_s = datetime.fromisoformat(origin.replace("Z", "+00:00")).timestamp()
        first_s = float(
            time_values_to_seconds(float(signal.data[signal.time_column].iloc[0]), signal.time_unit)
        )
        signal.offset_ms = (first_s - origin_s) * 1000.0 + source.offset_ms

    def _find_signal_config(self, source_id: str) -> SignalSource | None:
        return next((item for item in self.recordings.signals if item.id == source_id), None)

    def _find_video_config(self, source_id: str) -> VideoSource | None:
        return next((item for item in self.recordings.videos if item.id == source_id), None)

    def _update_loaded_signal_offset(self, source: SignalSource) -> None:
        signal = self.signals.get(source.id)
        if signal is not None:
            self.apply_time_alignment(signal, source)
