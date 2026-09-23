# CMF in Practice

This page walks through two real `.cmf` packages to show how CMF handles different model types end to end:

- **Welch Freeze Index exemplar** — a fixed signal estimator plus a fitted classifier
- **Walking Classifier** — a trained ONNX model, two input streams, explicit tensor shapes

---

## Example 1: Welch Freeze Index exemplar

### The model

The exemplar computes a three-second Welch Freeze Index and applies a fixed
one-feature logistic classifier. It is the same signal estimator used in the
Welch freeze-index feature. The classifier makes that score
usable within CMF's probability-to-interval workflow; it is a
development-calibrated demonstration operator, not a clinically validated FOG
detector.

### Package structure

```
freeze-index.cmf/
├── SHA256SUMS
├── classifier.json
├── config.json
├── labels.json
├── README.md
└── wrapper.py
```

`wrapper.py` contains the complete Welch estimator. `classifier.json` stores
the fitted logistic coefficient, intercept, decision-rule record, and
provenance.

---

### config.json walkthrough

```json
{
  "cmf_version": "1.1",
  "name": "Welch Freeze Index exemplar",
  "version": "3.0.0",
  "description": "Windowed FOG annotation exemplar using the same three-second Welch Freeze Index estimator as the packaged feature implementation and a fixed one-feature logistic classifier calibrated on the FOG-COA development corpus."
}
```

The `name` and `description` are what appear in RIME's model browser. The `cmf_version` tells RIME how to interpret the rest of the file.

---

### Inputs

```json
"inputs": [
  {
    "name": "accel_window",
    "type": "signal",
    "channels": ["acc_z"],
    "sampling_rate_hz": 128,
    "description": "Vertical acceleration proxy from the left-shank sensor; bind the physical vertical axis explicitly."
  }
]
```

RIME uses this to:

1. Check whether the current session has a compatible signal before offering the model
2. Verify the declared 128 Hz sampling rate and slice complete windows before calling `wrapper.py`

The wrapper receives `inputs["accel_window"]` as a NumPy array with no parsing required.

---

### Outputs

```json
"outputs": [
  {
    "name": "fog_probability",
    "type": "probability",
    "labels": ["no_fog", "fog"]
  }
]
```

`type: probability` tells RIME the model returns a value in [0, 1] per window. RIME thresholds this to create annotation intervals.

The three output types across the bundled models illustrate the range:

| Model | Output type | What it produces |
|---|---|---|
| Welch Freeze Index exemplar | `probability` | Confidence score per window → intervals |
| Walking Classifier | `probability` | Confidence score per window → intervals |
| Step Detector | `point` | Discrete timestamps (heel strikes) |

---

### Inference mode

```json
"inference": {
  "mode": "windowed",
  "window_size_ms": 3000,
  "stride_ms": 500,
  "window_anchor": "start",
  "terminal_window": "drop",
  "threshold": 0.5,
  "postprocessing": {
    "merge_gap_ms": 0,
    "min_duration_ms": 0
  }
}
```

`mode: windowed` means RIME slides a complete 3-second window over the signal
in 500 ms steps, timestamps it at the window start, and drops any terminal
partial window. Values greater than or equal to the conventional probability
cutoff of 0.50 are positive. Their complete window extents are unioned into
annotations; the zero merge gap adds no bridge between separated extents, and
the zero minimum duration removes none of the reconstructed intervals.

---

### Fixed estimator profile

```json
"parameters": []
```

The estimator itself has no hidden runtime controls: Welch preprocessing, the
0.5–3 Hz and 3–8 Hz bands, log-ratio scaling, and the absence of score smoothing
are fixed in the package declaration. Window size, stride, decision threshold,
merge gap, and minimum duration remain explicit CMF execution declarations.

---

### Output mapping

```json
"output_mappings": [
  {
    "output_name": "fog_probability",
    "lane": "FOG",
    "label": "FOG"
  }
]
```

This tells RIME where to display the model's output: thresholded intervals go into the **FOG** annotation lane, labeled **FOG**. If that lane doesn't exist yet, RIME creates it.

---

### wrapper.py walkthrough

The wrapper implements a single class with two methods:

```python
class CMFModel:
    def __init__(self, model_dir: str) -> None:
        # Load the declared defaults and fitted classifier artifact
        ...

    def predict(self, inputs, params=None) -> dict[str, np.ndarray]:
        # Compute the three-second Welch log band-power ratio
        # Apply the stored logistic classifier
        # Return {"fog_probability": array([p])}
        ...
```

RIME calls `__init__` once when the model is loaded, then calls `predict` for each window. The contract is simple:

- **`inputs`** — a dict of `{input_name: np.ndarray}`, already resampled and shaped per `config.json`
- **`params`** — a dict of `{param_name: value}` reflecting current UI settings
- **returns** — a dict of `{output_name: np.ndarray}` matching the declared outputs

The wrapper doesn't need to know anything about RIME, sessions, or file formats.

---

### What RIME does with this

When you load the Welch Freeze Index exemplar on a session:

1. RIME reads `config.json` and checks the bound signal has the declared vertical proxy channel at 128 Hz
2. RIME slides the 3 s window over the signal in 500 ms steps
3. Each window is passed to `predict()` as `inputs["accel_window"]`
4. Returned probabilities are thresholded at the declared 0.50 cutoff and reconstructed using the declared window, merge-gap, and minimum-duration semantics
5. Intervals are written into the **FOG** lane as **FOG** annotations

The result appears in the timeline alongside manual annotations, ready for side-by-side comparison or model evaluation.

---

## Example 2: Walking Classifier (ONNX)

### The model

The **Walking Classifier** is a small 1D CNN trained to distinguish walking from non-walking using bilateral ankle accelerometry. Unlike the Freeze Index, it has no hand-crafted feature extraction as the ONNX weights encode everything learned from training data.

This example shows:

- A trained model with binary weights (`model.onnx`)
- Two separate input streams
- Explicit tensor shape declarations
- Preprocessing handled entirely inside the wrapper

### Package structure

```
walking-classifier.cmf/
├── config.json
├── model.onnx
└── wrapper.py
```

---

### Inputs

```json
"inputs": [
  {
    "name": "left_ankle",
    "type": "signal",
    "channels": ["acc_x", "acc_y", "acc_z"],
    "sampling_rate_hz": 100,
    "shape": [1, 300, 3],
    "description": "Left ankle 3-axis accelerometer at 100Hz over a 3 s window."
  },
  {
    "name": "right_ankle",
    "type": "signal",
    "channels": ["acc_x", "acc_y", "acc_z"],
    "sampling_rate_hz": 100,
    "shape": [1, 300, 3],
    "description": "Right ankle 3-axis accelerometer at 100Hz over a 3 s window."
  }
]
```

Two key differences from the Freeze Index:

**Multiple inputs.** RIME passes both `left_ankle` and `right_ankle` as separate arrays to `predict()`.

**Explicit `shape`.** `[1, 300, 3]` means batch=1, 300 time steps, 3 channels. RIME validates that the sliced window matches this before calling the wrapper. If the shapes don't match, the model won't be offered for that session.

---

### Outputs and inference mode

Same `probability` output type as the Freeze Index, with shorter windows (3 s, stride 1 s) appropriate for activity classification rather than event detection.

---

### Parameters

```json
{
  "name": "scale_to_g",
  "type": "bool",
  "label": "Convert m/s² to g",
  "default": true
}
```

A `bool` parameter is rendered as a checkbox in the UI. This handles the common case where different sensor systems record acceleration in different units. The conversion happens inside the wrapper before any inference.

---

### wrapper.py walkthrough

The ONNX wrapper lazy-loads the model session to avoid importing `onnxruntime` at startup:

```python
class CMFModel:
    def __init__(self, model_dir: str) -> None:
        # Stores path to model.onnx — does NOT load the ONNX session yet
        ...

    def predict(self, inputs, params=None) -> dict[str, np.ndarray]:
        left = self._prepare_ankle_input(inputs["left_ankle"], params)
        right = self._prepare_ankle_input(inputs["right_ankle"], params)
        outputs = self._get_session().run(
            ["walking_probability"],
            {"left_dynamic_magnitude": left, "right_dynamic_magnitude": right},
        )
        return {"walking_probability": np.asarray(outputs[0]).reshape(-1)}
```

All preprocessing (unit conversion, gravity removal via median subtraction, L2 magnitude) runs inside the wrapper. From RIME's perspective it just passes raw arrays in and receives a probability out.

---

### What RIME does with this

1. RIME checks both `left_ankle` and `right_ankle` can be satisfied from the session's signals
2. RIME slides a 3 s window (stride 1 s) over both signals simultaneously, keeping them time-aligned
3. Both windows are passed to `predict()` — the wrapper handles preprocessing and ONNX inference
4. Probabilities above 0.9 are merged into walking intervals in the **Tasks** lane, labeled **Walk**

---

## Writing your own model

To package your own detector as a `.cmf` file, see [Loading a Model](loading-a-model.md).
