# Movement Detector (Video)

Whole-signal video movement detector using an OpenCV CSRT tracker.

- Input: one video stream
- Output: `moving_bouts` interval array
- Runtime: Python wrapper

The wrapper tracks a user-selected subject box from the first frame, converts frame-to-frame centroid displacement into a normalized movement signal, smooths it, thresholds it, and merges nearby bouts.

The `movement_threshold` is camera-dependent: distant hallway views tend to need much smaller values than close-up recordings because the subject occupies fewer pixels and per-frame displacement is correspondingly smaller.
