# Welch Freeze Index CMF example

Example package for the signal → probability → interval workflow. Bind a 128 Hz
acceleration channel; the wrapper computes a Welch freeze index and applies the
fixed logistic mapping in `classifier.json`. Configure the threshold, window,
stride and episode reconstruction through the native Run model dialog.

The included classifier was development-calibrated on FOG recordings and is not
an externally validated clinical detector. Treat this as an integration example.
`SHA256SUMS` identifies the four runtime files. Calibration is not performed by
this package. The manuscript retains its own fixed runtime copy and provenance.
