# Installation

## Requirements

- Python 3.10 or later
- A virtual environment manager (recommended: `venv` or `conda`)

## Install

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install RIME
pip install neurocog-rime-core neurocog-rime-ui
```

## Launch

```bash
rime
```

To open a specific session directly:

```bash
rime --open path/to/session.json
```

## Install from source

```bash
pip install "neurocog-rime-core @ git+https://github.com/neurocog-mobility/rime.git#subdirectory=packages/rime-core"
pip install "neurocog-rime-ui @ git+https://github.com/neurocog-mobility/rime.git#subdirectory=packages/rime-ui"
rime
```

## Verify installation

If RIME launches and shows an empty main window, installation is successful.
