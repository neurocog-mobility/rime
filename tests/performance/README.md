# v0.2 performance and UI cleanup — 2026-09-21

Run from the repository root:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python tests/check_v02_performance.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --durations=15
```

The final regression suite passed **388 tests**. Focused lint checks passed for the
new performance harness, shell, extracted controls, and shell tests. Existing core
and active timeline/media/model/review tests are retained. Tests of deleted UI
implementations were removed; the overview tests now exercise the active widget,
and native shell tests replace the prototype tests. Signal-label expectations now
include the channel, matching the active control.

## Workloads and observed results

macOS 26.1 arm64, Python 3.14.2, offscreen Qt. Median of three repeats in milliseconds;
see [raw results](v02-results.json) for maxima, platform details and file sizes.
These are synthetic smoke measurements, not hardware-independent release thresholds.

| Retained annotations | Three-measure preview | Capture | Equal-record overlay | Timeline paint |
| --- | --- | --- | --- | --- |
| 100 | 0.56 | 14.3 | 8.93 | 2.16 |
| 1000 | 6.06 | 64.69 | 56.09 | 16.91 |
| 10000 | 45.67 | 583.65 | 574.26 | 163.41 |

The harness also exercises save/open, edit/undo, document read/write, recalculation,
inspection-graph construction and rendering. It asserts calculated values and
recalculation consistency. Record sources are synthetic 1 MiB files; capture timing
therefore does not characterize hashing multi-gigabyte recordings. Overlay timings
use identical records; they do not characterize large adjudication histories or
many mismatched graph nodes.

A 30-minute 100 Hz, three-channel synthetic CSV (180,000 rows) loaded in about
61 ms; configuring and rendering its signal widget took about 92 ms. Two synthetic
640×360 MJPEG videos delivered 58 frames each in 2.006 seconds (28.9 fps each) with
zero position difference at the end of this short observation. This checks Qt frame
delivery using CPU conversion; it does not establish sustained synchronization,
high-resolution codec performance, audio behavior, or physical display frame rate.

The timeline stress run exposed repeated full-store scans for each annotation's
row geometry. Source lists are now cached per lane for one paint event only. A
regression test verifies one scan per lane and refreshed rows after suggestions
change. At 10,000 annotations, roughly 163 ms per paint remains a density limit;
smooth interactive playback at that density is not established.

## Cleanup boundaries

Removed the unused older windows, panels, workflow helpers and their exclusive
dialogs/widgets; removed precomputed prototype measurements, simulated source and
annotation views, fake progress screens, preview CLI/menu routes, and the launch
shortcut into a local review example. Shared boundary and bounding-box editors
were extracted and preserved. Start, new/open workspace, review, model execution,
measurement export and independent record inspection use the native interfaces.
The existing open-workspace view remains reachable from View → Annotations after
returning to Start.

No source recordings, manuscript files, notes, example datasets, or scientific
core APIs were deleted. The subsequent folder cleanup replaced study-derived test fixtures with synthetic
records. Software tests no longer require manuscript or notes directories. User documentation and release packaging remain separate tasks.

Current working copies removed in this pass, including pre-existing modifications,
were backed up outside the repository at `/tmp/rime-obsolete-ui-backup.tar.gz`;
the old model-settings dialog is additionally preserved at
`/tmp/rime-model-settings-before-cleanup.py`. These are local recovery copies,
not release assets.
