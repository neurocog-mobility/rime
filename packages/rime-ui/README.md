# neurocog-rime-ui

`neurocog-rime-ui` is the Qt desktop application for RIME. It builds on `rime_core` to provide session creation, timeline-based annotation, schema-aware editing, model review, signal visualization, comparison workflows, and export tooling.

## Install

```bash
pip install neurocog-rime-ui
```

For local development:

```bash
pip install -e packages/rime-core
pip install -e packages/rime-ui
```

Optional extras:

```bash
pip install -e "packages/rime-ui[docs]"
```

## Quick Start

```bash
rime
python -m rime_ui
```

Open assets directly on launch:

```bash
rime --open /path/to/session.json
rime --open /path/to/session.json --compare /path/to/comparison_session.json
rime --open /path/to/session.json --model /path/to/model.rime
```

Typical workflow:

1. Create or open a session.
2. Load videos and optional signals.
3. Annotate against the active protocol schema.
4. Review pending ghost annotations from model output.
5. Export reports, Parquet datasets, or media clips.
