# Freeze Index

Windowed freeze-of-gait probability model based on the Freeze Index described in Moore et al. (2008).

- Input: one vertical accelerometer channel sampled at 128 Hz
- Output: `fog_probability`
- Runtime: Python wrapper

The wrapper computes a Welch power spectral density on each 6 s window, forms the freeze-to-locomotor power ratio, and maps that value to a probability with a configurable sigmoid.

# References

Moore, S. T., MacDougall, H. G., & Ondo, W. G. (2008). Ambulatory monitoring of freezing of gait in Parkinson's disease. Journal of neuroscience methods, 167(2), 340-348.