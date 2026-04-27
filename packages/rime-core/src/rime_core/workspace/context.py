"""Stable core-facing API for one loaded working session."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rime_core.annotations import Annotation, AnnotationStore, generate_id
from rime_core.cmf import CMFLoader, CMFPackage
from rime_core.common.time import time_values_to_seconds
from rime_core.io.exporters import ExporterRegistry
from rime_core.inference import InferenceError, InferenceResult, InferenceRunner, InputBinding, OutputMapping
from rime_core.loaders import SignalLoaderRegistry
from rime_core.rule_engine import RuleEngine, Violation
from rime_core.schema import ProtocolSchema
from rime_core.sessions import (
    ClinicalMetricSpec,
    Session,
    SignalConfig,
    SubjectInfo,
    VideoConfig,
    create_session,
    load_session,
    save_session,
)
from rime_core.signals import Signal


logger = logging.getLogger(__name__)

ContextCallback = Callable[..., None]


@dataclass
class WorkingContext:
    """Owns the live core state for one open session."""

    session: Session
    schema: ProtocolSchema
    store: AnnotationStore
    signals: dict[str, Signal]
    rule_engine: RuleEngine
    loaded_models: dict[str, CMFPackage] = field(default_factory=dict)
    loader_registry: SignalLoaderRegistry = field(default_factory=SignalLoaderRegistry.default)
    exporter_registry: ExporterRegistry = field(default_factory=ExporterRegistry.default)
    _callbacks: dict[str, list[ContextCallback]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        loader_registry: SignalLoaderRegistry | None = None,
    ) -> WorkingContext:
        """Open a working context from an existing session on disk."""
        registry = loader_registry or SignalLoaderRegistry.default()
        session = load_session(path)
        schema = cls._load_schema_for_session(session)
        store = cls._load_annotations(session)
        signals = cls._load_signals(session, registry)
        return cls(
            session=session,
            schema=schema,
            store=store,
            signals=signals,
            rule_engine=RuleEngine(schema),
            loader_registry=registry,
            exporter_registry=ExporterRegistry.default(),
        )

    @classmethod
    def create(
        cls,
        session_dir: Path | str,
        name: str,
        *,
        schema: ProtocolSchema | None = None,
        videos: list | None = None,
        signals: list | None = None,
        subject: SubjectInfo | None = None,
        loader_registry: SignalLoaderRegistry | None = None,
    ) -> WorkingContext:
        """Create a new session and return its working context."""
        resolved_schema = schema or ProtocolSchema.default()
        registry = loader_registry or SignalLoaderRegistry.default()
        session = create_session(
            session_dir=Path(session_dir),
            name=name,
            videos=videos or [],
            signals=signals or [],
            subject=subject,
        )
        store = AnnotationStore()
        store._session_id = session.id
        store._session_name = session.name
        return cls(
            session=session,
            schema=resolved_schema,
            store=store,
            signals={},
            rule_engine=RuleEngine(resolved_schema),
            loader_registry=registry,
            exporter_registry=ExporterRegistry.default(),
        )

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

        self._autosave()
        self._emit("store_changed", self.store)
        return annotation

    def validate(self) -> list[Violation]:
        """Run the rule engine validation pass."""
        return self.rule_engine.validate(self.store)

    def save(self) -> None:
        """Persist session metadata and annotations to disk."""
        save_session(self.session)
        annotations_path = self.session.session_dir / "annotations" / "annotations.json"
        self.store.save(annotations_path)

    def replace_store(self, store: AnnotationStore) -> None:
        """Replace the live annotation store and persist it."""
        self.store = store
        self._autosave()
        self._emit("store_changed", self.store)

    def update_clinical_metrics(self, metrics: list[ClinicalMetricSpec]) -> None:
        """Persist the session's saved clinical metrics."""
        self.session.clinical_metrics = list(metrics)
        save_session(self.session)

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
            self.session,
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
            errors.append(
                f"Signal missing required channels: {', '.join(sorted(missing))}"
            )

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

    def set_source_offset(self, source_type: str, source_path: str, offset_ms: float) -> None:
        """Persist a manual offset update for a signal or video source."""
        resolved_offset = float(offset_ms)
        if source_type == "signal":
            config = self._find_signal_config(source_path)
            if config is None:
                raise KeyError(f"Signal '{source_path}' not found")
            config.offset_ms = resolved_offset
            self._update_loaded_signal_offset(config)
            self._autosave()
            self._emit("signals_changed", self.signals)
            return
        if source_type == "video":
            config = self._find_video_config(source_path)
            if config is None:
                raise KeyError(f"Video '{source_path}' not found")
            config.offset_ms = resolved_offset
            self._autosave()
            self._emit("session_changed", self.session)
            return
        raise ValueError(f"Unsupported source type '{source_type}'")

    def _resolve_model(self, model_name: str | None) -> CMFPackage | None:
        if model_name is None:
            return self.loaded_model
        return self.loaded_models.get(model_name)

    @staticmethod
    def _load_schema_for_session(session: Session) -> ProtocolSchema:
        if session.schema_path:
            schema_path = Path(session.schema_path)
            if not schema_path.is_absolute():
                schema_path = session.session_dir / schema_path
            return ProtocolSchema.load(schema_path)
        return ProtocolSchema.default()

    @staticmethod
    def _load_annotations(session: Session) -> AnnotationStore:
        annotations_path = session.session_dir / "annotations" / "annotations.json"
        if annotations_path.exists():
            return AnnotationStore.load(annotations_path)

        store = AnnotationStore()
        store._session_id = session.id
        store._session_name = session.name
        return store

    @classmethod
    def _load_signals(
        cls,
        session: Session,
        loader_registry: SignalLoaderRegistry,
    ) -> dict[str, Signal]:
        loaded: dict[str, Signal] = {}
        for config in session.signals:
            try:
                signal = loader_registry.load(session.get_signal_path(config), config)
            except Exception as exc:
                logger.warning("Could not load signal '%s': %s", config.path, exc)
                continue
            cls._apply_session_time_alignment(signal, config, session)
            loaded[cls._signal_key(config, signal)] = signal
        return loaded

    @staticmethod
    def _apply_session_time_alignment(signal: Signal, config, session: Session) -> None:
        if config.time_reference != "utc_epoch":
            signal.offset_ms = config.offset_ms
            return

        if not session.session_start_utc:
            logger.warning(
                "Signal %s uses utc_epoch timestamps but session_start_utc is not set; "
                "treating first sample as t=0",
                config.path,
            )
            signal.offset_ms = config.offset_ms
            return

        session_start_s = WorkingContext._parse_utc_iso(session.session_start_utc)
        signal_start_s = WorkingContext._read_first_timestamp_as_epoch_s(signal)
        signal.offset_ms = (signal_start_s - session_start_s) * 1000.0 + config.offset_ms

    @staticmethod
    def _signal_key(config, signal: Signal) -> str:
        return config.name or signal.name or Path(config.path).stem

    def _find_signal_config(self, source_path: str) -> SignalConfig | None:
        for config in self.session.signals:
            if config.path == source_path:
                return config
        return None

    def _find_video_config(self, source_path: str) -> VideoConfig | None:
        for config in self.session.videos:
            if config.path == source_path:
                return config
        return None

    def _update_loaded_signal_offset(self, config: SignalConfig) -> None:
        expected_name = config.name or Path(config.path).stem
        for signal in self.signals.values():
            if signal.name not in {expected_name, config.name, Path(config.path).stem}:
                continue
            self._apply_session_time_alignment(signal, config, self.session)

    @staticmethod
    def _parse_utc_iso(value: str) -> float:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

    @staticmethod
    def _read_first_timestamp_as_epoch_s(signal: Signal) -> float:
        if signal.time_column not in signal.data.columns:
            raise ValueError(f"UTC signal requires time column '{signal.time_column}'")

        first_value = float(signal.data[signal.time_column].iloc[0])
        return float(time_values_to_seconds(first_value, signal.time_unit))
