# Checkpoints

Checkpoints let you save named snapshots of annotation progress within a session. This is useful for multi-day annotation, version control of annotation state, or marking a session as ready for review.

## Creating a checkpoint

**Session → Save Checkpoint** (or `Ctrl+Shift+S`)


- Enter a name (e.g. `first-pass`, `after-review`, `final`)
- Optional notes
- The checkpoint is saved inside the session folder

## Restoring a checkpoint

**Session → Manage Checkpoints** shows the list of saved checkpoints.

- Click any checkpoint to preview its annotation state
- Click **Restore** to revert the session to that snapshot

## When to use checkpoints

| Scenario | Checkpoint name suggestion |
|---|---|
| End of a session annotation pass | `pass-1` |
| Before making a large correction | `pre-correction` |
| Annotation complete, ready for IRR | `ready-for-irr` |
| After IRR resolution | `final` |

!!! tip
    Creating a checkpoint before loading a review layer is good practice — it preserves your independent annotation state.
