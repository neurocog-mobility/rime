# Coverage

Coverage quantifies how much of a reference period (e.g. a walking task) is occupied by a target event (e.g. a FOG episode). It is the primary derived measure for many clinical outcome calculations in RIME.

## What coverage means

```
coverage = total duration of [target annotations] / total duration of [reference annotations]
```

For example: *FOG duration as a fraction of total walking time.*

## Configuring a coverage spec

Coverage is defined by two lane/label selectors:

- **Numerator** — the event you are measuring (e.g. lane: `fog`, label: `FOG`)
- **Denominator** — the reference period (e.g. lane: `task`, label: `Walking`)


## Output

| Field | Description |
|---|---|
| Ratio | Numerator ÷ Denominator (0–1) |
| Percent | Ratio × 100 |
| Numerator duration (ms) | Total merged duration of target events |
| Denominator duration (ms) | Total merged duration of reference periods |
| Numerator episodes | Count of discrete target events |
| Denominator episodes | Count of discrete reference periods |

## Multiple coverage specs

A session can have multiple named coverage specs (e.g. FOG/Walking, TiP/Walking, FOG/Total). These are defined in the [schema](../study-setup/protocol-schema.md) and displayed together in the Clinical panel.
