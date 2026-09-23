# CMF 1.1 specification

The Common Model Format (CMF) is an executable annotation-operator contract. A conforming invocation combines a CMF package, declared input bindings, and active parameter values to transform source data into schema-typed annotations.

The specification fixes execution. It does not assert that the packaged model or its outputs are clinically valid.

## Package contract

A CMF package is a directory or zip archive ending in `.cmf`. It contains:

- `config.json`, the machine-readable operator declaration;
- `labels.json`, the declared label metadata;
- the runtime entry point declared by `runtime.entry`;
- every weight, lookup, or other artifact required by that entry point.

`config.json` declares:

| Component | Required content |
|---|---|
| Identity | `cmf_version`, model `name`, and package `version` |
| Runtime | supported runtime type and packaged entry point |
| Inputs | input names, modalities, channels, sampling rates, and shapes where fixed |
| Outputs | output names, types, labels, and shapes where fixed |
| Execution | whole-signal or windowed mode and its temporal semantics |
| Decision | threshold and, for windowed outputs, interval reconstruction settings |
| Parameters | names, types, defaults, and permitted values of exposed model parameters |
| Mapping | output name to annotation lane and label |
| Requirements | external runtime dependencies not bundled with the package |

The invocation record supplies the concrete source and channel bindings, active parameter values, and any permitted output-mapping overrides. A stochastic runtime must expose and fix its random seed as a declared parameter; otherwise it is not deterministic under this conformance definition.

## Windowed execution

A CMF 1.1 windowed declaration requires:

```json
{
  "mode": "windowed",
  "window_size_ms": 3000,
  "stride_ms": 500,
  "window_anchor": "start",
  "terminal_window": "drop",
  "threshold": 0.9,
  "postprocessing": {
    "merge_gap_ms": 0,
    "min_duration_ms": 0
  }
}
```

CMF 1.1 currently defines one canonical schedule:

1. The first complete window begins at the first sample in the selected execution range.
2. Subsequent windows advance by `stride_ms` after conversion to the bound input's sampling grid.
3. Each result is timestamped at its window start.
4. A terminal partial window is dropped and is never padded implicitly.
5. Multiple bound inputs must resolve to the same window-start timeline.

## Probability and classification reconstruction

For a mapped windowed probability or classification output:

1. A decision is positive when its value is greater than or equal to `threshold`.
2. A positive decision covers the complete half-open input window `[start, start + window_size_ms)`.
3. Overlapping or touching positive windows are unioned.
4. Separate reconstructed intervals are bridged when their gap is less than or equal to `merge_gap_ms`.
5. Intervals shorter than `min_duration_ms` are removed after union and bridging.
6. Annotation confidence is the mean of the positive decision values contributing to the interval; bridged negative decisions do not contribute.
7. The declared output mapping assigns the resulting interval to its annotation lane and label.

Whole-signal interval and point outputs are emitted by the packaged runtime and mapped directly after bounds validation.

## Backward compatibility

CMF 1.0 windowed packages remain loadable with these defaults:

- `window_anchor = "start"`;
- `terminal_window = "drop"`;
- `merge_gap_ms = 0`;
- `min_duration_ms = 0`.

CMF 1.1 windowed packages must declare these values explicitly. Negative merge gaps or minimum durations are invalid.

## Sufficiency and conformance

For deterministic runtimes, a complete package plus identical bindings, parameter values, source data, coordinate registration, and execution range is sufficient to determine:

- the window timeline;
- model inputs and raw outputs;
- threshold decisions;
- reconstructed interval or point annotations;
- their lane, label, confidence, and provenance source.

Two conforming runners disagree if these canonical outputs differ beyond the numerical tolerance declared for the evaluation. Such a disagreement falsifies either runner conformance or the completeness of this specification.
