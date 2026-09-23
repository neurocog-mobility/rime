# RIME

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19804970.svg)](https://doi.org/10.5281/zenodo.19804970)
[![PyPI](https://img.shields.io/pypi/v/neurocog-rime-core)](https://pypi.org/project/neurocog-rime-core/)

RIME (Reproducible Interval-derived Measurement Exchange) represents measurements and their derivations. Its reference application supports multimodal annotation, review, and inspection/comparison of `.rime` records. The headless core implements the record contract and calculations.

## Install

```bash
pip install neurocog-rime-core neurocog-rime-ui
```

## Repository Layout

This repo is organized as two installable Python packages:

- `packages/rime-core`: headless library published as `neurocog-rime-core`
- `packages/rime-ui`: Qt desktop app published as `neurocog-rime-ui`

## Install For Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e packages/rime-core
pip install -e packages/rime-ui
```

## Launch The App

```bash
rime
python -m rime_ui
```

On the v0.2 development branch, open a workspace directly:

```bash
rime --open /path/to/workspace.json
```

## Quick Start

1. Install both packages.
2. Launch `rime`.
3. Use **File → New workspace** or open `workspace.json`.
4. Load a protocol schema and media/signals as needed.
5. Annotate, review suggestions or rater inputs, and save immutable `.rime` measurement records.

The v0.2 desktop uses native annotation and review workspaces and an independent
record inspector. See the [compact synthetic workflows](examples/workflows/README.md)
for launch commands and manual checks. Software tests do not require research data.

Local research/manuscript work and real-data demos are excluded from the software
repository; public examples use synthetic evidence.

## Core Package Overview

`rime_core` is grouped into a few focused areas:

- `rime_core.annotation`: annotations, rule engine, review helpers
- `rime_core.analysis`: coverage, IRR, evaluation
- `rime_core.io`: import/export and signal-loading helpers
- `rime_core.modeling`: CMF package loading and inference
- `rime_core.records`: annotation sets, source descriptions, timelines, and research context
- `rime_core.workspace`: live working-session orchestration

## Development

Run the test suite from the repo root (install `pytest` in the environment first):

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

For release checks, install the built wheels in a fresh environment and set
`RIME_TEST_INSTALLED=1` when running the suite; this prevents the test setup from
substituting checkout sources for installed packages.

Build docs locally:

```bash
mkdocs serve
```

## Docs

Project documentation lives in [`docs/`](docs/) and is configured with [`mkdocs.yml`](mkdocs.yml).

## Citation

If you use RIME in your research, please cite:

```bibtex
@software{zafar2026rime,
  author    = {Zafar, Abdullah and Casagrande Pinto, Arthur Eduardo and Homagain, Abhishesh and Howe, Erika and Ehgoetz Martens, Kaylena},
  title     = {RIME: Open-source multimodal signal annotation, modeling, and benchmarking for Parkinson's research},
  year      = {2026},
  doi       = {10.5281/zenodo.19804970},
  url       = {https://doi.org/10.5281/zenodo.19804970}
}
```
