# Signal Configuration

RIME can display one or more physiological signal channels alongside video. Signals are aligned to the timeline and used as input by AI detection models.

## Supported formats

CSV files with a header row are supported. Each column represents a channel. Timestamps can be provided as a dedicated column (in seconds or milliseconds) or inferred from the sampling rate.

## Adding signals to a session

Signals are linked during the [Session Wizard](session-wizard.md) or added later via **Session → Configure Signals**.

## Channel mapping

For each signal file, specify:

- **Channel columns** — which CSV columns to display
- **Sampling rate** — in Hz
- **Time column** — the column containing timestamps (or inferred from sample rate)
- **Time unit** — seconds, milliseconds, samples
- **Display label** — the name shown on the timeline track

## Viewing signals

- Each channel appears as a separate track below the timeline
- Scroll to zoom; drag to pan
- Channels can be shown/hidden via the signal track header

## Signal track display settings

Amplitude scaling, colour, and track height are adjustable via right-click on the signal track header.
