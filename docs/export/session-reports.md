# Session Reports

The session report is a human-readable TSV summary of a single session. It is the primary output for clinical record-keeping and progress tracking.

**File → Export Report**

## What's included

The report has two sections:

**Annotation summary** — one row per lane/label combination:

| Column | Description |
|---|---|
| `Lane` | Annotation lane |
| `Label` | Label within that lane, or `(all)` for lane totals |
| `Episodes` | Number of annotations |
| `Total_ms` | Union duration (overlapping intervals counted once) |
| `Mean_ms` | Mean episode duration |
| `Pct_of_session` | Total duration as % of recording |

**Clinical metrics** — one row per metric defined in the session schema:

| Column | Description |
|---|---|
| `Metric` | Metric name from schema |
| `Value_pct` | Result as a percentage |
| `Numerator_ms` / `Numerator_episodes` | Matching annotation time and count |
| `Denominator_ms` / `Denominator_episodes` | Reference time and count |

## Format

Reports are exported as tab-separated `.txt` files with a `#`-prefixed header block:

```
# RIME Session Report
# Session:    PD_042_visit2
# Rater:      rater_1
# Subject:    PD_042
# Condition:  ON
# Duration:   12m 34s (754000 ms)
# Generated:  2026-03-19T10:22:01Z

Lane    Label    Episodes    Total_ms    Mean_ms    Pct_of_session
FOG     (all)    14          42300       3021       5.6
FOG     FOG      14          42300       3021       5.6
Tasks   (all)    3           312000      104000     41.4
Tasks   Walk     3           312000      104000     41.4
...
```

The header block is ignored by `pandas.read_csv(..., comment='#', sep='\t')`.

!!! tip
    Export after saving a [checkpoint](../annotation/checkpoints.md) so the exported state is clearly versioned.
