# Labels & Lanes

## What is a lane?

A lane is a horizontal row on the timeline representing one dimension of annotation — for example, a FOG lane, a gait phase lane, or a context lane. Lanes are defined by the [protocol schema](../study-setup/protocol-schema.md).

## Ordering and groups

The protocol assigns each lane a level and can group lanes. These are study-defined;
there is no universal five-level hierarchy. GP-FOG includes Tasks, FOG and more
detailed lanes.

## Labels within a lane

Each lane has a defined set of valid labels (e.g. `FOG`, `Trembling-in-Place`, `Akinesia`). Only labels defined in the schema are available in the label dialog.

## Point events vs. interval annotations

RIME supports both interval annotations (with a start and end time, e.g. a FOG episode) and point annotations (instantaneous events, e.g. a step detection marker). The annotation type is declared per lane in the schema.
