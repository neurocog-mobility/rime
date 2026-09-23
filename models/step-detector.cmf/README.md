# Step Detector

Whole-signal heel-strike detector for ankle accelerometry based on smoothed acceleration magnitude and adaptive peak picking.

- Input: 3-axis ankle accelerometer sampled at 128 Hz
- Output: point events in `step_times`
- Runtime: Python wrapper

The wrapper computes vector magnitude, smooths it with a Savitzky-Golay filter, subtracts a median baseline, estimates a rolling standard-deviation threshold, and returns peak times as step events.
