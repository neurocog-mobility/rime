# Save and reopen work

| File | Purpose | Save action |
|---|---|---|
| Annotation workspace JSON | Editable annotations, protocol, source settings and suggestion decisions | **File → Save workspace** |
| Review workspace JSON | Frozen input information and saved reviewer decisions | **File → Save review** |
| `.rime` document | Captured measurements and retained derivations | **Save records…** |

Save explicitly during work; edits are not automatically written to disk. Closing
with unsaved changes prompts you to save, discard or cancel. Open workspace JSON
to resume. Undo/redo is for the current editing session, not a persisted action log.

Workspaces reference external recordings, which must remain available. Copying the
JSON does not copy media. Saved file paths are relative to the workspace JSON,
so move the workspace and evidence together, preserving their layout. Old `session.json`
and prototype `working/` snapshots are unsupported.

The record inspector opens `.rime` files without recordings or a workspace. Later
workspace edits do not alter an exported document; use separate filenames to retain
multiple captures. See [measurements](../clinical-analysis/clinical-metrics.md).
