# Duration, percentage and count

The Measurements section computes selected protocol measures over the configured
observation period. Its **Configure…** button selects measures and time scope.

- **Covered duration:** the union of matching intervals within eligible time, in seconds. Overlap is counted once.
- **Percentage coverage:** covered duration divided by eligible duration, multiplied by 100.
- **Count:** one per retained matching annotation contributing within eligible time. Separate overlapping annotations remain separate contributors.

For GP-FOG these are Total time frozen, Percentage time frozen and FOG episode
count, with Tasks defining the default observation period. A count represents
clinical episodes only if the study's annotation practice assigns one annotation
per episode.

An empty observation period gives an undefined result. No matching events in a
nonempty period gives zero; that does not establish complete review or clinical
absence. Pending suggestions and unresolved review inputs do not contribute.
Point annotations support count, not duration or percentage.

See [measurements](clinical-metrics.md) for capture and inspection and the
[native contract](../measurement-records/rime-specification.md) for exact semantics.
