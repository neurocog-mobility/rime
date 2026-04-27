# Export & Reports

RIME can export session data in several formats for downstream analysis or archiving.

## Session report

**File → Export Report**

The session report is a structured summary of the session including:

- Session metadata (participant ID, date, condition)
- Annotation counts and durations per lane/label
- Coverage metrics
- Clinical outcome values
- IRR scores (if computed)

| Format | Use case |
|---|---|
| TSV | Import into R, Python, SPSS |
| JSON | Programmatic use; archiving |

## Exporting raw annotations

Raw annotation data (start time, end time, label, lane, rater) can be exported as a flat Parquet file for custom analysis. See [Annotation Export](../export/annotation-export.md).

## BIDS export

Annotations and signal data can be exported as a BIDS-aligned dataset. See [Dataset Export](../export/dataset-export.md).

!!! tip
    Export after saving a [checkpoint](../annotation/checkpoints.md) so the exported state is clearly versioned.
