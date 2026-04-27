# RIME

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19804971.svg)](https://doi.org/10.5281/zenodo.19804971)
[![PyPI](https://img.shields.io/pypi/v/neurocog-rime-core)](https://pypi.org/project/neurocog-rime-core/)

RIME is a multimodal annotation toolkit for Parkinson's disease research. It combines a headless core package for sessions, schemas, annotation logic, import/export, and model orchestration with a Qt desktop application for interactive review and labeling.

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

Open a session directly:

```bash
rime --open /path/to/session.json
rime --open /path/to/session.json --compare /path/to/comparison_session.json
rime --open /path/to/session.json --model /path/to/model.rime
```

## Quick Start

1. Install both packages.
2. Launch `rime`.
3. Create or open a session.
4. Load a protocol schema and media/signals as needed.
5. Annotate in the UI, review pending ghost annotations, and export reports or datasets.

## Core Package Overview

`rime_core` is grouped into a few focused areas:

- `rime_core.annotation`: annotations, rule engine, review helpers
- `rime_core.analysis`: coverage, IRR, evaluation
- `rime_core.io`: import/export and signal-loading helpers
- `rime_core.modeling`: CMF package loading and inference
- `rime_core.sessions`: session models and persistence
- `rime_core.workspace`: live working-session orchestration

## Development

Run the test suite from the repo root:

```bash
.venv/bin/pytest
```

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
  doi       = {10.5281/zenodo.19804971},
  url       = {https://doi.org/10.5281/zenodo.19804971}
}
```
