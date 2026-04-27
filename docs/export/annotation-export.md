# Annotation Export

RIME exports annotations as a flat Parquet file — one row per annotation. This is the primary format for downstream analysis, model benchmarking, and archiving.

**File → Export Annotations**

## Columns

### Identity

| Column | Type | Description |
|---|---|---|
| `annotation_id` | `str` | Unique annotation ID |
| `session_id` | `str` | Session UUID |
| `session_name` | `str` | Human-readable session name |
| `subject_id` | `str` | Participant identifier |
| `rater` | `str` | Annotator name |
| `export_timestamp` | `str` | ISO 8601 UTC timestamp of this export |

### Annotation

| Column | Type | Description |
|---|---|---|
| `lane` | `str` | Annotation lane (e.g. `FOG`, `Tasks`) |
| `label` | `str` | Label within the lane (e.g. `FOG`, `Walk`) |
| `event_type` | `str` | `interval` or `point` |
| `start_ms` | `float` | Onset in milliseconds from session start |
| `end_ms` | `float` | Offset in milliseconds (same as `start_ms` for points) |
| `duration_ms` | `float` | Duration in milliseconds |

### Provenance

| Column | Type | Description |
|---|---|---|
| `source` | `str` | Where the annotation came from — see below |
| `confidence` | `float` | Current confidence score (1.0 for manual annotations) |
| `human_modified` | `bool` | `True` if a model annotation was subsequently edited by a rater |
| `origin_confidence` | `float \| null` | Model's original confidence before any human adjustment |
| `origin_start_ms` | `float \| null` | Model's original onset before any human adjustment |
| `origin_end_ms` | `float \| null` | Model's original offset before any human adjustment |
| `ghost` | `bool` | `True` if the annotation was never accepted (excluded from exports by default) |

## The `source` field

`source` identifies the origin of every annotation:

| Value | Meaning |
|---|---|
| `manual` | Created by a rater directly |
| `corrected` | Accepted from a model suggestion, then edited |
| `elan_import` | Imported from an ELAN `.eaf` file |
| `model:<name>` | Accepted from model `<name>` without modification |

## Provenance example

When a model produces an annotation and a rater later adjusts its boundaries:

| Field | Value |
|---|---|
| `source` | `corrected` |
| `start_ms` | `12400` ← rater's adjusted onset |
| `end_ms` | `15800` ← rater's adjusted offset |
| `human_modified` | `True` |
| `origin_start_ms` | `12100` ← model's original onset |
| `origin_end_ms` | `16200` ← model's original offset |
| `origin_confidence` | `0.94` ← model's confidence at inference time |

This lets you reconstruct both what the model predicted and what the rater accepted, in the same row.

## Filtering ghost annotations

Ghost annotations (model suggestions not yet reviewed) are excluded from exports by default. To include them, enable **Include unreviewed suggestions** in the export dialog. Ghost rows have `ghost = True` and can be filtered out in analysis:

```python
import pandas as pd

df = pd.read_parquet("session_annotations.parquet")
accepted = df[~df["ghost"]]
```

## Loading in Python

```python
import pandas as pd

df = pd.read_parquet("session_annotations.parquet")

# All accepted FOG episodes
fog = df[(df["lane"] == "FOG") & (~df["ghost"])]

# Model annotations that were subsequently edited
edited = df[df["human_modified"]]

# Compute onset correction (rater vs model)
edited["onset_correction_ms"] = edited["start_ms"] - edited["origin_start_ms"]
```
