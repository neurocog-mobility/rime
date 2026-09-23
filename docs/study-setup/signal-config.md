# Signal configuration

Add signal CSV files with **Add signals…** during workspace setup. The confirmation
dialog shows detected channels and lets you set the time column, sampling rate,
time reference, time unit and initial display channels.

Time reference distinguishes relative time, UTC epoch and sample index. Units
include seconds, milliseconds, microseconds and nanoseconds. Match these settings
to the actual file; a plausible-looking plot does not verify timestamp semantics.

In the workspace, **View → Choose signal channels…** changes the visible channels.
The same menu can show channels together or switch the displayed channel. Signal
plots share the annotation timeline's visible time range; use the Playback/Zoom
ruler to navigate.

**Alignment…** previews constant source offsets live. Synchronization notes can
record methods performed before loading, even with zero offset. These declarations
are retained with the workspace and exported measurement derivation.
