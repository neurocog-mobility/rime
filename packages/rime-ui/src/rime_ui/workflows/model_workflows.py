"""Model loading, configuration, and inference workflows for the main window."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QDialog, QMessageBox

from rime_core import CMFPackage, CMFValidationError, InputBinding, ModelSettings, OutputMapping
from rime_core.annotations import Annotation
from rime_core.inference import InferenceError
from rime_core.signals import Signal
from rime_ui.dialogs.model_loader_dialog import ModelLoaderDialog
from rime_ui.dialogs.model_settings_dialog import ModelSettingsDialog

if TYPE_CHECKING:
    from rime_ui.windows.main_window import RimeMainWindow


class ModelWorkflowHelper:
    """Own the model-specific workflows that would otherwise crowd the main window."""

    def __init__(self, window: RimeMainWindow) -> None:
        self.window = window

    def load_model_from_dialog(self) -> None:
        package = ModelLoaderDialog.choose_loaded_package(self.window)
        if package is None:
            return
        self.register_loaded_model(package)

    def load_model_path(self, model_path: str | Path) -> bool:
        model_path = str(model_path)
        if Path(model_path).suffix != ".rime":
            QMessageBox.warning(
                self.window,
                "Model Error",
                "Select a model package folder ending in .rime.",
            )
            return False

        try:
            if self.window.context is not None:
                package = self.window.context.load_model(model_path)
            else:
                from rime_core import CMFLoader

                package = CMFLoader.load(model_path)
            return self.register_loaded_model(package)
        except CMFValidationError as exc:
            QMessageBox.critical(self.window, "Model Error", f"Failed to load model:\n{exc}")
        except Exception as exc:
            QMessageBox.critical(
                self.window,
                "Model Error",
                f"Unexpected model load failure:\n{exc}",
            )
        return False

    def register_loaded_model(self, package: CMFPackage) -> bool:
        if (
            self.window.context is not None
            and self.window.context.loaded_models.get(package.name) is not package
        ):
            self.window.context.register_model_package(package)
        self.window._loaded_models[package.name] = package
        self.window._active_model_name = package.name
        self.window._last_inference_results.pop(package.name, None)
        self._persist_model_path(package)
        self.window._update_model_actions()
        self.window._refresh_model_panel()
        self._warn_missing_requirements_for_loaded_models([package])
        self.window.statusBar().showMessage(f"Loaded model: {package.name}", 3000)
        return True

    def current_model(self, model_name: str | None = None) -> CMFPackage | None:
        if model_name is not None:
            return self.window._loaded_models.get(model_name)
        if (
            self.window._active_model_name
            and self.window._active_model_name in self.window._loaded_models
        ):
            return self.window._loaded_models[self.window._active_model_name]
        if not self.window._loaded_models:
            return None
        return next(iter(self.window._loaded_models.values()))

    def unload_model(self, model_name: str) -> None:
        if model_name not in self.window._loaded_models:
            return
        self.window._loaded_models.pop(model_name)
        self.window._last_inference_results.pop(model_name, None)
        self._remove_persisted_model_path(model_name)
        if self.window.context is not None:
            try:
                self.window.context.unload_model(model_name)
            except KeyError:
                pass
        if self.window._active_model_name == model_name:
            self.window._active_model_name = next(iter(self.window._loaded_models), None)
        self.window._update_model_actions()
        self.window._refresh_model_panel()
        self.window.statusBar().showMessage(f"Unloaded model: {model_name}", 3000)

    def restore_session_models(self) -> list[str]:
        if self.window.session is None or self.window.context is None:
            return []

        missing_models: list[str] = []
        restored_models: list[CMFPackage] = []
        removed_any = False
        for model_name in list(self.window.session.model_paths):
            model_path = self.window.session.get_model_path(model_name)
            if model_path is None or not model_path.exists():
                self.window.session.model_paths.pop(model_name, None)
                missing_models.append(model_name)
                removed_any = True
                continue
            try:
                package = self.window.context.load_model(model_path)
            except Exception:
                self.window.session.model_paths.pop(model_name, None)
                missing_models.append(model_name)
                removed_any = True
                continue
            if package.name != model_name:
                self.window.session.model_paths.pop(model_name, None)
                self.window.session.model_paths[package.name] = self.window._normalize_path_for_session(
                    str(model_path)
                )
                removed_any = True
            if self.window.context.loaded_models.get(package.name) is not package:
                self.window.context.register_model_package(package)
            self.window._loaded_models[package.name] = package
            self.window._last_inference_results.pop(package.name, None)
            self.window._active_model_name = package.name
            restored_models.append(package)

        if removed_any:
            self.window.context.save()
        self._warn_missing_requirements_for_loaded_models(restored_models, restored=True)
        return missing_models

    def _warn_missing_requirements_for_loaded_models(
        self,
        packages: list[CMFPackage],
        *,
        restored: bool = False,
    ) -> None:
        sections: list[str] = []
        for package in packages:
            missing_requirements = getattr(package, "missing_requirements", None)
            if missing_requirements is None:
                continue
            missing = missing_requirements()
            if not missing:
                continue
            lines = [f"{package.name}:"]
            for item in missing:
                lines.append(
                    "- "
                    + f"{item.requirement.package} (import: {item.requirement.import_name})"
                )
                lines.append(f"  Install with: {item.requirement.install_hint}")
            sections.append("\n".join(lines))
        if not sections:
            return

        intro = (
            "Some restored models declare missing Python dependencies."
            if restored
            else "This model declares missing Python dependencies."
        )
        QMessageBox.warning(
            self.window,
            "Model Requirements",
            intro
            + "\n\n"
            + "\n\n".join(sections)
            + "\n\nInference may fail until these packages are installed.",
        )

    def run_inference(self, model_name: str | None = None) -> None:
        if self.window.context is None or self.window.session is None:
            QMessageBox.warning(
                self.window,
                "Warning",
                "Open a session before running inference.",
            )
            return
        model = self.current_model(model_name)
        if model is None:
            QMessageBox.warning(
                self.window,
                "Warning",
                "Load a model before running inference.",
            )
            return
        self.window._active_model_name = model.name
        if not model.config.output_mappings:
            QMessageBox.warning(
                self.window,
                "Warning",
                "This model does not define any output mappings in config.json.",
            )
            return

        if not self.ensure_model_settings_ready(model):
            return
        settings = self.current_model_settings(model.name)
        bindings: list[InputBinding] = []
        for input_config in model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            if not input_name:
                QMessageBox.warning(
                    self.window,
                    "Warning",
                    "Model input is missing a name.",
                )
                return
            bindings.append(self.binding_from_settings(model, input_config, settings))

        try:
            result = self.window.context.run_inference(
                bindings,
                self.build_output_mappings(model, settings),
                model_name=model.name,
                params=self.build_model_params(model, settings),
                time_range=self.window.timeline.get_loop_region(),
            )
            self.window._last_inference_results[model.name] = result
            self.window._refresh_annotations_after_change()
            self.window.statusBar().showMessage(
                f"Inference complete: {len(result.annotations)} ghost annotations",
                4000,
            )
        except InferenceError as exc:
            QMessageBox.critical(self.window, "Inference Error", str(exc))
        except Exception as exc:
            QMessageBox.critical(
                self.window,
                "Inference Error",
                f"Failed to run inference:\n{exc}",
            )

    def edit_model_settings(self, model_name: str | None = None) -> None:
        if self.window.context is None or self.window.session is None:
            QMessageBox.warning(
                self.window,
                "Warning",
                "Open a session before editing model settings.",
            )
            return
        model = self.current_model(model_name)
        if model is None:
            QMessageBox.warning(
                self.window,
                "Warning",
                "Load a model before editing model settings.",
            )
            return
        self.window._active_model_name = model.name

        dialog = ModelSettingsDialog(
            model=model,
            schema=self.window._current_schema(),
            session=self.window.session,
            signals=self.window.context.signals,
            settings=self.current_model_settings(model.name),
            parent=self.window,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.window.context.save()
        self.window._refresh_model_panel()
        self.window.statusBar().showMessage("Model settings saved.", 3000)

    def current_model_settings(self, model_name: str) -> ModelSettings:
        if self.window.session is None:
            return ModelSettings()
        return self.window.session.model_settings.setdefault(model_name, ModelSettings())

    def build_model_params(
        self,
        model: CMFPackage,
        settings: ModelSettings,
    ) -> dict[str, object]:
        defaults = {str(entry["name"]): entry.get("default") for entry in model.config.parameters}
        filtered = {name: settings.params[name] for name in defaults if name in settings.params}
        defaults.update(filtered)
        settings.params = dict(defaults)
        return defaults

    def build_output_mappings(
        self,
        model: CMFPackage,
        settings: ModelSettings,
    ) -> list[OutputMapping]:
        overrides = {
            str(entry.get("output_name", "")): entry
            for entry in settings.output_mappings
            if isinstance(entry, dict)
        }
        resolved: list[dict[str, str]] = []
        mappings: list[OutputMapping] = []
        for default in model.config.output_mappings:
            merged = dict(default)
            merged.update(overrides.get(default["output_name"], {}))
            resolved.append(
                {
                    "output_name": merged["output_name"],
                    "lane": merged["lane"],
                    "label": merged["label"],
                }
            )
            mappings.append(
                OutputMapping(
                    output_name=merged["output_name"],
                    lane=merged["lane"],
                    label=merged["label"],
                )
            )
        settings.output_mappings = resolved
        return mappings

    def pending_model_ghosts(self, model_name: str) -> list[Annotation]:
        if model_name not in self.window._loaded_models:
            return []
        source = f"model:{model_name}"
        return sorted(
            [
                annotation
                for annotation in self.window.annotations.all()
                if annotation.ghost and annotation.source == source
            ],
            key=lambda annotation: (annotation.start_ms, annotation.end_ms, annotation.id),
        )

    def review_pending_ghosts(self, model_name: str | None = None) -> None:
        model = self.current_model(model_name)
        if model is None:
            return
        self.window._active_model_name = model.name
        pending = self.pending_model_ghosts(model.name)
        if not pending:
            return
        first = pending[0]
        self.window.timeline.select_annotation(first.id)
        self.window.timeline.seek_to(first.start_ms)
        self.window._update_toolbar_state(has_annotation=True, has_snap=False, has_ghost=True)

    def ensure_model_settings_ready(self, model: CMFPackage) -> bool:
        settings = self.current_model_settings(model.name)
        missing = self.missing_model_settings(model, settings)
        if not missing:
            return True

        message = (
            "This model needs settings before it can run:\n- "
            + "\n- ".join(missing)
            + "\n\nThe model settings dialog will open now."
        )
        QMessageBox.information(self.window, "Model Settings Required", message)
        self.edit_model_settings(model.name)
        return not self.missing_model_settings(model, self.current_model_settings(model.name))

    def missing_model_settings(
        self,
        model: CMFPackage,
        settings: ModelSettings,
    ) -> list[str]:
        missing: list[str] = []
        if self.window.context is None or self.window.session is None:
            return ["No active model session"]

        for input_config in model.config.inputs:
            input_name = str(input_config.get("name", "")).strip()
            input_type = str(input_config.get("type", "signal")).casefold()
            binding_mode = str(input_config.get("binding_mode", "channel_map")).casefold()
            source_value = settings.input_sources.get(input_name)
            if not source_value:
                missing.append(f"{input_name}: source")
                continue

            if input_type == "video":
                if not Path(source_value).exists():
                    missing.append(f"{input_name}: source path not found")
                continue

            signal = self.window.context.signals.get(source_value)
            if signal is None:
                missing.append(f"{input_name}: selected signal not loaded")
                continue
            if binding_mode == "source_only":
                required_channels = [str(channel) for channel in input_config.get("channels", [])]
                missing_channels = [
                    channel for channel in required_channels if channel not in signal.channels
                ]
                if missing_channels:
                    missing.append(f"{input_name}: missing channels {', '.join(missing_channels)}")
                continue
            channel_map = settings.input_bindings.get(input_name, {})
            for model_channel in [str(channel) for channel in input_config.get("channels", [])]:
                signal_column = channel_map.get(model_channel)
                if not signal_column:
                    missing.append(f"{input_name}: {model_channel}")
                    continue
                if signal_column not in signal.channels:
                    missing.append(f"{input_name}: {model_channel}->{signal_column}")
        return missing

    def binding_from_settings(
        self,
        model: CMFPackage,
        input_config: dict,
        settings: ModelSettings,
    ) -> InputBinding:
        if self.window.context is None or self.window.session is None:
            raise InferenceError("Session context is not available for model inference")

        input_name = str(input_config.get("name", "")).strip()
        input_type = str(input_config.get("type", "signal")).casefold()
        source_value = settings.input_sources.get(input_name)
        if not source_value:
            raise InferenceError(f"Missing source for model input '{input_name}'")

        if input_type == "video":
            return InputBinding(input_name=input_name, video_path=Path(source_value))

        signal = self.window.context.signals.get(source_value)
        if signal is None:
            raise InferenceError(
                f"Selected signal '{source_value}' for input '{input_name}' is not loaded"
            )
        binding_mode = str(input_config.get("binding_mode", "channel_map")).casefold()
        channel_map = (
            {}
            if binding_mode == "source_only"
            else dict(settings.input_bindings.get(input_name, {}))
        )
        required_channels = [str(channel) for channel in input_config.get("channels", [])]
        expected_rate = input_config.get("sampling_rate_hz", input_config.get("sample_rate_hz"))
        if expected_rate is not None and not np.isclose(signal.sampling_rate_hz, float(expected_rate)):
            signal = self.resample_signal_for_input(
                signal,
                input_name=input_name,
                required_channels=required_channels,
                channel_map=channel_map,
                target_rate_hz=float(expected_rate),
            )
        return InputBinding(
            input_name=input_name,
            signal=signal,
            channel_map=channel_map or None,
        )

    def resample_signal_for_input(
        self,
        signal: Signal,
        *,
        input_name: str,
        required_channels: list[str],
        channel_map: dict[str, str],
        target_rate_hz: float,
    ) -> Signal:
        source_time_ms = signal.get_time_ms()
        if len(source_time_ms) == 0:
            return Signal(
                name=f"{signal.name}:{input_name}@{target_rate_hz:g}Hz",
                data=pd.DataFrame({}),
                sampling_rate_hz=target_rate_hz,
                time_column="sample",
                channels=[],
                offset_ms=signal.offset_ms,
                time_reference="sample_index",
            )

        duration_ms = float(source_time_ms[-1] - source_time_ms[0])
        sample_count = max(1, int(round(duration_ms * target_rate_hz / 1000.0)) + 1)
        target_time_ms = (
            np.arange(sample_count, dtype=np.float64) / target_rate_hz * 1000.0 + source_time_ms[0]
        )

        data: dict[str, np.ndarray] = {}
        used_columns: list[str] = []
        for model_channel in required_channels:
            signal_column = channel_map.get(model_channel, model_channel)
            used_columns.append(signal_column)
            values = signal.get_channel(signal_column).astype(np.float64, copy=False)
            data[signal_column] = np.interp(target_time_ms, source_time_ms, values).astype(
                np.float32
            )

        return Signal(
            name=f"{signal.name}:{input_name}@{target_rate_hz:g}Hz",
            data=pd.DataFrame(data),
            sampling_rate_hz=target_rate_hz,
            time_column="sample",
            channels=used_columns,
            offset_ms=signal.offset_ms,
            time_reference="sample_index",
        )

    def _persist_model_path(self, package: CMFPackage) -> None:
        if self.window.session is None or self.window.context is None:
            return
        model_path = str(Path(package.path).expanduser().resolve())
        self.window.session.model_paths[package.name] = self.window._normalize_path_for_session(
            model_path
        )
        self.window.context.save()

    def _remove_persisted_model_path(self, model_name: str) -> None:
        if self.window.session is None or self.window.context is None:
            return
        if self.window.session.model_paths.pop(model_name, None) is not None:
            self.window.context.save()
