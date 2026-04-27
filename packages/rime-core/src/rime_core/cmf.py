"""CMF package loading for model-assisted annotation."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import zipfile

import numpy as np


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CMFRequirement:
    """One declared Python dependency for a CMF package."""

    package: str
    import_name: str
    install_hint: str


@dataclass(frozen=True)
class CMFMissingRequirement:
    """A declared dependency that could not be imported in the current environment."""

    requirement: CMFRequirement


@dataclass
class CMFConfig:
    """Parsed config.json from a CMF package."""

    cmf_version: str
    name: str
    version: str
    description: str
    license: str
    runtime_type: str
    runtime_entry: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    inference_mode: str
    window_size_ms: int | None
    stride_ms: int | None
    threshold: float
    parameters: list[dict[str, Any]]
    labels: dict[str, Any]
    output_mappings: list[dict[str, str]]
    requirements: list[CMFRequirement] = field(default_factory=list)


@dataclass
class CMFPackage:
    """A loaded, ready-to-run CMF model package."""

    path: Path
    config: CMFConfig
    _runner: Any
    _model_dir: Path
    _temp_dir: TemporaryDirectory[str] | None = None

    @property
    def name(self) -> str:
        return self.config.name

    def missing_requirements(self) -> list[CMFMissingRequirement]:
        """Return declared dependencies that are not importable in the current environment."""
        missing: list[CMFMissingRequirement] = []
        for requirement in self.config.requirements:
            try:
                if importlib.util.find_spec(requirement.import_name) is None:
                    missing.append(CMFMissingRequirement(requirement=requirement))
            except (ImportError, ModuleNotFoundError, ValueError):
                missing.append(CMFMissingRequirement(requirement=requirement))
        return missing

    def predict(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, np.ndarray]:
        """Run inference with the underlying runtime."""
        runner = self._runner or CMFLoader._load_runner(self._model_dir, self.config)
        self._runner = runner
        signature = inspect.signature(runner.predict)
        if len(signature.parameters) >= 2:
            outputs = runner.predict(inputs, params or {})
        else:
            outputs = runner.predict(inputs)
        if not isinstance(outputs, dict):
            raise TypeError("CMF wrapper predict() must return a dict[str, np.ndarray]")
        return {name: np.asarray(value) for name, value in outputs.items()}


class CMFValidationError(Exception):
    """Raised when a CMF package is missing required metadata or runtime files."""


class CMFLoader:
    """Load CMF packages from directories or zip archives."""

    @staticmethod
    def load(path: str | Path) -> CMFPackage:
        """Load a single .rime package (directory or zip)."""
        source_path = Path(path).expanduser()
        if not source_path.exists():
            raise CMFValidationError(f"CMF package not found: {source_path}")

        temp_dir: TemporaryDirectory[str] | None = None
        if source_path.is_dir():
            model_dir = CMFLoader._resolve_package_root(source_path)
        else:
            if not zipfile.is_zipfile(source_path):
                raise CMFValidationError(f"CMF package is not a directory or zip archive: {source_path}")
            temp_dir = TemporaryDirectory(prefix="rime-cmf-")
            with zipfile.ZipFile(source_path) as archive:
                archive.extractall(temp_dir.name)
            model_dir = CMFLoader._resolve_package_root(Path(temp_dir.name))

        config = CMFLoader._load_config(model_dir)
        return CMFPackage(
            path=source_path,
            config=config,
            _runner=None,
            _model_dir=model_dir,
            _temp_dir=temp_dir,
        )

    @staticmethod
    def scan(models_dir: str | Path) -> list[CMFPackage]:
        """Scan a directory for .rime packages and load all valid ones."""
        root = Path(models_dir).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"Models directory not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Models path is not a directory: {root}")

        packages: list[CMFPackage] = []
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not CMFLoader._looks_like_package(child):
                continue
            try:
                packages.append(CMFLoader.load(child))
            except CMFValidationError as exc:
                logger.warning("Skipping invalid CMF package %s: %s", child, exc)
        return packages

    @staticmethod
    def _looks_like_package(path: Path) -> bool:
        if path.is_dir():
            return path.suffix == ".rime" or (path / "config.json").exists()
        return path.suffix in {".rime", ".zip"} and path.is_file()

    @staticmethod
    def _resolve_package_root(path: Path) -> Path:
        if (path / "config.json").exists():
            return path

        children = [child for child in path.iterdir() if child.is_dir()]
        if len(children) == 1 and (children[0] / "config.json").exists():
            return children[0]

        raise CMFValidationError(f"config.json not found in CMF package: {path}")

    @staticmethod
    def _load_config(model_dir: Path) -> CMFConfig:
        config_path = model_dir / "config.json"
        labels_path = model_dir / "labels.json"

        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CMFValidationError(f"Missing config.json in {model_dir}") from exc
        except json.JSONDecodeError as exc:
            raise CMFValidationError(f"Invalid config.json in {model_dir}: {exc}") from exc

        try:
            labels = json.loads(labels_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CMFValidationError(f"Missing labels.json in {model_dir}") from exc
        except json.JSONDecodeError as exc:
            raise CMFValidationError(f"Invalid labels.json in {model_dir}: {exc}") from exc
        if not isinstance(labels, dict):
            raise CMFValidationError(f"labels.json must contain a JSON object in {model_dir}")

        runtime = raw.get("runtime", {})
        inference = raw.get("inference", {})

        runtime_type = raw.get("runtime_type", runtime.get("type"))
        runtime_entry = raw.get("runtime_entry", runtime.get("entry"))
        if runtime_type == "python_script":
            runtime_type = "wrapper"

        if runtime_type != "wrapper":
            raise CMFValidationError(
                f"Unsupported runtime type '{runtime_type}' in {config_path}; only 'wrapper' is supported"
            )

        inputs = CMFLoader._require_list(raw, "inputs", config_path)
        outputs = CMFLoader._require_list(raw, "outputs", config_path)
        cmf_version = CMFLoader._require_str(raw, "cmf_version", config_path, fallback_key="schema_version")
        name = CMFLoader._require_str(raw, "name", config_path)
        version = CMFLoader._require_str(raw, "version", config_path)
        runtime_entry = CMFLoader._require_str(
            {"runtime_entry": runtime_entry},
            "runtime_entry",
            config_path,
        )
        inference_mode = str(inference.get("mode", "whole_signal")).casefold()
        if inference_mode not in {"whole_signal", "windowed"}:
            raise CMFValidationError(
                f"Invalid inference mode '{inference_mode}' in {config_path}"
            )
        if inference_mode == "windowed":
            window_size_ms = CMFLoader._require_int(
                {"window_size_ms": raw.get("window_size_ms", inference.get("window_size_ms"))},
                "window_size_ms",
                config_path,
            )
            stride_ms = CMFLoader._require_int(
                {"stride_ms": raw.get("stride_ms", inference.get("stride_ms"))},
                "stride_ms",
                config_path,
            )
        else:
            window_size_ms = None
            stride_ms = None
        threshold = CMFLoader._require_float(
            {"threshold": raw.get("threshold", inference.get("threshold"))},
            "threshold",
            config_path,
        )
        raw_parameters = raw.get("parameters", [])
        if not isinstance(raw_parameters, list):
            raise CMFValidationError(f"'parameters' must be a list in {config_path}")
        parameters: list[dict[str, Any]] = []
        for entry in raw_parameters:
            if not isinstance(entry, dict):
                raise CMFValidationError(
                    f"Each 'parameters' entry must be an object in {config_path}"
                )
            if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                raise CMFValidationError(
                    f"'parameters' entry missing required key 'name' in {config_path}"
                )
            if not isinstance(entry.get("type"), str) or not entry["type"].strip():
                raise CMFValidationError(
                    f"'parameters' entry missing required key 'type' in {config_path}"
                )
            parameters.append(dict(entry))
        raw_mappings = raw.get("output_mappings", [])
        if not isinstance(raw_mappings, list):
            raise CMFValidationError(f"'output_mappings' must be a list in {config_path}")
        output_mappings: list[dict[str, str]] = []
        for entry in raw_mappings:
            if not isinstance(entry, dict):
                raise CMFValidationError(
                    f"Each 'output_mappings' entry must be an object in {config_path}"
                )
            for key in ("output_name", "lane", "label"):
                if not isinstance(entry.get(key), str) or not entry[key].strip():
                    raise CMFValidationError(
                        f"'output_mappings' entry missing required key '{key}' in {config_path}"
                    )
            output_mappings.append(
                {
                    "output_name": entry["output_name"],
                    "lane": entry["lane"],
                    "label": entry["label"],
                }
            )
        requirements = CMFLoader._load_requirements(raw, config_path)

        entry_path = model_dir / runtime_entry
        if not entry_path.exists():
            raise CMFValidationError(f"Runtime entry '{runtime_entry}' not found in {model_dir}")

        return CMFConfig(
            cmf_version=cmf_version,
            name=name,
            version=version,
            description=str(raw.get("description", "")),
            license=str(raw.get("license", "")),
            runtime_type=runtime_type,
            runtime_entry=runtime_entry,
            inputs=inputs,
            outputs=outputs,
            inference_mode=inference_mode,
            window_size_ms=window_size_ms,
            stride_ms=stride_ms,
            threshold=threshold,
            parameters=parameters,
            labels=labels,
            output_mappings=output_mappings,
            requirements=requirements,
        )

    @staticmethod
    def _load_runner(model_dir: Path, config: CMFConfig) -> Any:
        entry_path = model_dir / config.runtime_entry
        spec = importlib.util.spec_from_file_location(
            f"rime_cmf_{model_dir.stem}_{abs(hash(entry_path))}",
            entry_path,
        )
        if spec is None or spec.loader is None:
            raise CMFValidationError(f"Unable to import wrapper module: {entry_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model_cls = getattr(module, "CMFModel", None)
        if model_cls is None:
            raise CMFValidationError(
                f"Wrapper module must define CMFModel: {entry_path}"
            )

        return CMFLoader._instantiate_wrapper(model_cls, model_dir)

    @staticmethod
    def _instantiate_wrapper(model_cls: type[Any], model_dir: Path) -> Any:
        attempts = (
            lambda: model_cls(str(model_dir)),
            lambda: model_cls(model_dir=str(model_dir)),
            lambda: model_cls(config_path=str(model_dir / "config.json")),
            lambda: model_cls(),
        )
        last_error: TypeError | None = None
        for attempt in attempts:
            try:
                return attempt()
            except TypeError as exc:
                last_error = exc
        raise CMFValidationError(
            f"Unable to instantiate wrapper class {model_cls.__name__}: {last_error}"
        )

    @staticmethod
    def _require_str(
        raw: dict[str, Any],
        key: str,
        config_path: Path,
        fallback_key: str | None = None,
    ) -> str:
        value = raw.get(key)
        if value is None and fallback_key is not None:
            value = raw.get(fallback_key)
        if not isinstance(value, str) or not value.strip():
            raise CMFValidationError(f"Missing or invalid '{key}' in {config_path}")
        return value

    @staticmethod
    def _require_list(raw: dict[str, Any], key: str, config_path: Path) -> list[dict[str, Any]]:
        value = raw.get(key)
        if not isinstance(value, list) or not value:
            raise CMFValidationError(f"Missing or invalid '{key}' in {config_path}")
        if not all(isinstance(item, dict) for item in value):
            raise CMFValidationError(f"'{key}' must be a list of objects in {config_path}")
        return value

    @staticmethod
    def _require_int(raw: dict[str, Any], key: str, config_path: Path) -> int:
        value = raw.get(key)
        if not isinstance(value, int) or value <= 0:
            raise CMFValidationError(f"Missing or invalid '{key}' in {config_path}")
        return value

    @staticmethod
    def _require_float(raw: dict[str, Any], key: str, config_path: Path) -> float:
        value = raw.get(key)
        if not isinstance(value, (int, float)):
            raise CMFValidationError(f"Missing or invalid '{key}' in {config_path}")
        return float(value)

    @staticmethod
    def _load_requirements(raw: dict[str, Any], config_path: Path) -> list[CMFRequirement]:
        value = raw.get("requirements", [])
        if value == []:
            return []
        if not isinstance(value, list):
            raise CMFValidationError(f"'requirements' must be a list in {config_path}")

        requirements: list[CMFRequirement] = []
        for entry in value:
            if not isinstance(entry, dict):
                raise CMFValidationError(
                    f"Each 'requirements' entry must be an object in {config_path}"
                )
            package = entry.get("package")
            import_name = entry.get("import")
            install_hint = entry.get("install_hint")
            if not isinstance(package, str) or not package.strip():
                raise CMFValidationError(
                    f"'requirements' entry missing required key 'package' in {config_path}"
                )
            if not isinstance(import_name, str) or not import_name.strip():
                raise CMFValidationError(
                    f"'requirements' entry missing required key 'import' in {config_path}"
                )
            if install_hint is None:
                install_hint = f"pip install {package}"
            if not isinstance(install_hint, str) or not install_hint.strip():
                raise CMFValidationError(
                    f"'requirements' entry has invalid 'install_hint' in {config_path}"
                )
            requirements.append(
                CMFRequirement(
                    package=package,
                    import_name=import_name,
                    install_hint=install_hint,
                )
            )
        return requirements
