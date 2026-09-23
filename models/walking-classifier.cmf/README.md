# Walking Classifier

ONNX-backed walking classifier for RIME.

- Inputs: left and right ankle 3-axis accelerometer signals
- Output: `walking_probability`
- Runtime: `wrapper.py` calling `onnxruntime`

This demo package keeps the public input contract simple for the app and handles
feature extraction in the wrapper. For each ankle window it:

1. Optionally converts `m/s^2 -> g`
2. Interpolates short NaN gaps
3. Computes acceleration magnitude
4. Subtracts the window median to produce a dynamic-magnitude trace

The exported ONNX graph receives one dynamic-magnitude channel per ankle and
returns a walking probability for each 3 s window with 1 s stride.
