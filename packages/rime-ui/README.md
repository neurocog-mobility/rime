# neurocog-rime-ui

`neurocog-rime-ui` is the Qt desktop application for RIME. It builds on `rime_core` to provide workspace creation, timeline-based annotation, schema-aware editing, model review, signal visualization, comparison workflows, and export tooling.

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

Open a native record directly:

```bash
rime --open /path/to/measurement.rime
```

The compact inspector reads and validates real profile 1.1 documents, inspects retained nodes,
recalculates measurements, and overlays two selected records. Open… inside the inspector adds
a second document. It does not load media or execute model packages.

Open annotation or review workspace JSON with the same `--open` option.
See [workflow examples](../../examples/workflows/README.md) for populated workspaces
and pairs of records to compare.
