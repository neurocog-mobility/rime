# Clinical Metrics

The Clinical panel aggregates annotation data into named clinical outcome metrics for the session.

## Opening the Clinical panel

**View → Clinical Panel**

## What the panel shows

### Coverage metrics

Named coverage ratios as defined in the schema (e.g. %TF — percentage of time frozen). See [Coverage](coverage.md).

### Episode statistics

- Number of FOG episodes
- Mean / median episode duration
- Longest episode

## Defining clinical metrics in the schema

Clinical metric definitions live in the session schema under `clinical_metrics`. Each metric specifies a name, a numerator (lane/label selector), and a denominator type (`session` for total recording duration, or `lane` to use a labelled interval as the denominator).

```json
"clinical_metrics": [
  {
    "name": "%TF (session)",
    "numerator": [{"lane": "FOG"}],
    "denominator_type": "session"
  },
  {
    "name": "%TF (task)",
    "numerator": [{"lane": "FOG"}],
    "denominator_type": "lane",
    "denominator": [{"lane": "Tasks", "label": "Walk"}]
  }
]
```

## Exporting clinical metrics

Clinical metric values are included in the session report. See [Export & Reports](export.md).
