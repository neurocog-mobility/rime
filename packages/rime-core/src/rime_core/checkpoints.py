"""Checkpoint storage for destructive annotation recovery."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from rime_core.annotations import AnnotationStore


PRE_DESTRUCTIVE_LIMIT = 10
RESTORE_GUARD_LIMIT = 2

KIND_SESSION_OPEN = "session_open"
KIND_PRE_DESTRUCTIVE = "pre_destructive"
KIND_MANUAL = "manual"
KIND_RESTORE_GUARD = "restore_guard"


@dataclass
class CheckpointEntry:
    id: str
    label: str
    kind: str
    created: str
    snapshot_file: str


@dataclass
class CheckpointSnapshot:
    entry: CheckpointEntry
    store: AnnotationStore
    snap_points: list[float]
    loop_region: tuple[float, float] | None


def create_checkpoint(
    session_dir: Path | str,
    store: AnnotationStore,
    *,
    label: str,
    kind: str,
    snap_points: list[float] | None = None,
    loop_region: tuple[float, float] | None = None,
) -> CheckpointEntry:
    """Persist one checkpoint snapshot and update the manifest."""
    session_path = Path(session_dir)
    created = _utc_now_iso()
    checkpoint_id = f"chk-{uuid.uuid4().hex[:10]}"
    entry = CheckpointEntry(
        id=checkpoint_id,
        label=label,
        kind=kind,
        created=created,
        snapshot_file=f"{checkpoint_id}.json",
    )
    payload = {
        "entry": asdict(entry),
        "annotations": store.to_dict(),
        "state": {
            "snap_points": [float(value) for value in (snap_points or [])],
            "loop_region": list(loop_region) if loop_region is not None else None,
        },
    }

    checkpoints_path = _checkpoints_dir(session_path)
    checkpoints_path.mkdir(parents=True, exist_ok=True)
    with open(checkpoints_path / entry.snapshot_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    entries = _load_manifest_entries(session_path)
    entries.append(entry)
    entries = _apply_retention(session_path, entries)
    _save_manifest_entries(session_path, entries)
    return entry


def list_checkpoints(session_dir: Path | str) -> list[CheckpointEntry]:
    """Return checkpoints newest-first."""
    entries = _load_manifest_entries(Path(session_dir))
    return sorted(entries, key=lambda entry: entry.created, reverse=True)


def load_checkpoint(session_dir: Path | str, checkpoint_id: str) -> CheckpointSnapshot:
    """Load one checkpoint snapshot by ID."""
    session_path = Path(session_dir)
    entries = {entry.id: entry for entry in _load_manifest_entries(session_path)}
    if checkpoint_id not in entries:
        raise KeyError(f"Checkpoint '{checkpoint_id}' not found")
    entry = entries[checkpoint_id]
    snapshot_path = _checkpoints_dir(session_path) / entry.snapshot_file
    with open(snapshot_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    state = data.get("state", {})
    loop_region_raw = state.get("loop_region")
    loop_region = None
    if isinstance(loop_region_raw, list) and len(loop_region_raw) == 2:
        loop_region = (float(loop_region_raw[0]), float(loop_region_raw[1]))

    return CheckpointSnapshot(
        entry=entry,
        store=AnnotationStore.from_dict(data.get("annotations", {})),
        snap_points=[float(value) for value in state.get("snap_points", [])],
        loop_region=loop_region,
    )


def count_checkpoints_by_kind(session_dir: Path | str, kind: str) -> int:
    return sum(1 for entry in _load_manifest_entries(Path(session_dir)) if entry.kind == kind)


def _apply_retention(session_dir: Path, entries: list[CheckpointEntry]) -> list[CheckpointEntry]:
    retained = list(entries)
    retained = _trim_kind(session_dir, retained, KIND_PRE_DESTRUCTIVE, PRE_DESTRUCTIVE_LIMIT)
    retained = _trim_kind(session_dir, retained, KIND_RESTORE_GUARD, RESTORE_GUARD_LIMIT)
    return retained


def _trim_kind(
    session_dir: Path,
    entries: list[CheckpointEntry],
    kind: str,
    limit: int,
) -> list[CheckpointEntry]:
    matching = sorted(
        [entry for entry in entries if entry.kind == kind],
        key=lambda entry: entry.created,
        reverse=True,
    )
    to_remove = matching[limit:]
    if not to_remove:
        return entries
    remove_ids = {entry.id for entry in to_remove}
    for entry in to_remove:
        snapshot_path = _checkpoints_dir(session_dir) / entry.snapshot_file
        if snapshot_path.exists():
            snapshot_path.unlink()
    return [entry for entry in entries if entry.id not in remove_ids]


def _manifest_path(session_dir: Path) -> Path:
    return _checkpoints_dir(session_dir) / "manifest.json"


def _checkpoints_dir(session_dir: Path) -> Path:
    return session_dir / "checkpoints"


def _load_manifest_entries(session_dir: Path) -> list[CheckpointEntry]:
    manifest_path = _manifest_path(session_dir)
    if not manifest_path.exists():
        return []
    with open(manifest_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return [
        CheckpointEntry(
            id=item["id"],
            label=item.get("label", ""),
            kind=item.get("kind", KIND_MANUAL),
            created=item.get("created", ""),
            snapshot_file=item.get("snapshot_file", ""),
        )
        for item in data.get("checkpoints", [])
        if isinstance(item, dict) and item.get("id")
    ]


def _save_manifest_entries(session_dir: Path, entries: list[CheckpointEntry]) -> None:
    manifest_path = _manifest_path(session_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0",
        "checkpoints": [asdict(entry) for entry in sorted(entries, key=lambda item: item.created)],
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
