"""Signal loader registry for pluggable source formats."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rime_core.session import SignalConfig
from rime_core.signals import Signal, load_csv_signal


SignalLoader = Callable[[Path, SignalConfig], Signal]


class SignalLoaderError(Exception):
    """Raised when no loader is available or a loader fails."""


class SignalLoaderRegistry:
    """Dispatch signal loading by declared format."""

    def __init__(self) -> None:
        self._loaders: dict[str, SignalLoader] = {}

    @classmethod
    def default(cls) -> SignalLoaderRegistry:
        registry = cls()
        registry.register("csv", load_csv_signal)
        return registry

    def register(self, signal_format: str, loader: SignalLoader) -> None:
        """Register a loader for one signal format."""
        self._loaders[signal_format.casefold()] = loader

    def supported_formats(self) -> list[str]:
        """Return registered formats in sorted order."""
        return sorted(self._loaders)

    def can_load(self, signal_format: str) -> bool:
        """Return True if a loader is registered for the given format."""
        return signal_format.casefold() in self._loaders

    def load(self, path: Path, config: SignalConfig) -> Signal:
        """Load one signal using the declared format."""
        loader = self._loaders.get(config.format.casefold())
        if loader is None:
            raise SignalLoaderError(f"No signal loader registered for format '{config.format}'")
        try:
            return loader(path, config)
        except Exception as exc:  # pragma: no cover - exercised by failure tests
            raise SignalLoaderError(f"Failed to load signal '{config.path}': {exc}") from exc
