"""Local editing state. Scientific objects live in rime_core.records."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rime_core.records import new_id, SignalSource

MAX_VIDEO_VIEWS = 2
DEFAULT_PANEL_VISIBILITY = {
    "annotation_list": True,
    "model_runner": True,
    "model_evaluation": True,
    "clinical_outcomes": True,
    "irr_panel": True,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ModelSettings:
    params: dict[str, Any] = field(default_factory=dict)
    input_sources: dict[str, str] = field(default_factory=dict)
    input_bindings: dict[str, dict[str, str]] = field(default_factory=dict)
    output_mappings: list[dict[str, str]] = field(default_factory=list)


@dataclass
class WorkspaceView:
    snap_points: list[float] = field(default_factory=list)
    signal_display_combined: bool = True
    display_channels: dict[str, list[str]] = field(default_factory=dict)
    panel_visibility: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_PANEL_VISIBILITY)
    )
    dock_layout_state: str = ""


@dataclass
class WorkspaceSession:
    root: Path
    name: str
    id: str = field(default_factory=lambda: new_id("workspace"))
    created: str = field(default_factory=now)
    modified: str = field(default_factory=now)
    source_locations: dict[str, str] = field(default_factory=dict)
    model_paths: dict[str, str] = field(default_factory=dict)
    model_settings: dict[str, ModelSettings] = field(default_factory=dict)
    view: WorkspaceView = field(default_factory=WorkspaceView)
    working_state: str = ""

    @property
    def path(self) -> Path:
        return self.root / "workspace.json"

    def source_path(self, source_id: str) -> Path | None:
        location = self.source_locations.get(source_id)
        return (self.root / Path(location).expanduser()).resolve() if location else None

    def resolved_source_locations(self) -> dict[str, str]:
        return {
            key: str(self.source_path(key))
            for key in self.source_locations
            if self.source_path(key) is not None
        }

    def model_path(self, name: str) -> Path | None:
        location = self.model_paths.get(name)
        return (self.root / Path(location).expanduser()).resolve() if location else None


@dataclass
class SignalSelection:
    """Import form result: a local file, its interpretation, and display choices."""

    path: str
    source: SignalSource
    display_channels: list[str] = field(default_factory=list)
