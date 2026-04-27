# Dataset Export

RIME can export windowed signal clips and video segments aligned to annotations. This is useful for building training datasets, manual clip review, or sharing specific episodes with collaborators.

## Signal clips

**File → Export Signal Clips**

Exports a Parquet file of raw signal samples sliced around each annotation, with optional padding.

### Output format

One row per sample, with columns:

| Column | Description |
|---|---|
| `annotation_id` | Links each sample back to the annotation |
| `time_offset_ms` | Time relative to annotation onset (negative = pre-onset padding) |
| `<channel>` | One column per signal channel (e.g. `acc_x`, `acc_y`, `acc_z`) |

For example, a 2-second FOG episode from a 3-axis accelerometer with 500 ms padding produces ~384 rows (at 128 Hz) with columns `annotation_id`, `time_offset_ms`, `acc_x`, `acc_y`, `acc_z`.

### Large sessions

For sessions with many annotations or high-density signals, the export is automatically split into numbered part files (`clips_signal_001.parquet`, `clips_signal_002.parquet`, ...) to keep individual files under a manageable row count.

### Loading in Python

```python
import pandas as pd
from pathlib import Path

# Single file
clips = pd.read_parquet("clips_acc_lower_limb.parquet")

# Multiple part files
clips = pd.concat(
    [pd.read_parquet(p) for p in sorted(Path("export/").glob("clips_acc_lower_limb_part*.parquet"))]
)

# Pivot to per-annotation arrays
for ann_id, group in clips.groupby("annotation_id"):
    signal = group.sort_values("time_offset_ms")[["acc_x", "acc_y", "acc_z"]].values
    # signal.shape → (n_samples, 3)
```

---

## Video clips

**File → Export Video Clips**

Exports one `.mp4` clip per annotation, trimmed to the annotation interval with optional padding. Requires `ffmpeg` on PATH.

### Output

Clips are written to `clips_video/` in the selected output directory. Each file is named:

```
<annotation_id>_<label>_<start_ms>ms.mp4
```

For example: `a3f1b2c4_FOG_12400ms.mp4`

If exporting all video roles (primary + secondary cameras), clips are prefixed with the video role: `primary_a3f1b2c4_FOG_12400ms.mp4`.

### Requirements

`ffmpeg` must be installed and available on PATH:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

RIME also checks common Homebrew paths (`/opt/homebrew/bin/ffmpeg`, `/usr/local/bin/ffmpeg`) as a fallback.

### Padding

A padding of 500 ms before and after each annotation is applied by default. Adjust this in the export dialog. Padding is clipped to the start/end of the video — no black frames are added.
