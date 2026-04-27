# Labels & Lanes

## What is a lane?

A lane is a horizontal row on the timeline representing one dimension of annotation — for example, a FOG lane, a gait phase lane, or a context lane. Lanes are defined by the [protocol schema](../study-setup/protocol-schema.md).

## The annotation hierarchy (L1–L5)

RIME supports up to five levels of nested annotation lanes. This allows coarse and fine-grained annotations to coexist and relate to each other — for example, L1 for task boundaries, L2 for FOG episodes, L3 for FOG subtypes.

| Level | Typical use |
|---|---|
| L1 | Task / walking bout |
| L2 | Gait phase or context |
| L3 | Primary event (e.g. FOG episode) |
| L4 | Event subtype |
| L5 | Fine-grained detail or notes |

## Labels within a lane

Each lane has a defined set of valid labels (e.g. `FOG`, `Trembling-in-Place`, `Akinesia`). Only labels defined in the schema are available in the label dialog.

## Point events vs. interval annotations

RIME supports both interval annotations (with a start and end time, e.g. a FOG episode) and point annotations (instantaneous events, e.g. a step detection marker). The annotation type is declared per lane in the schema.
