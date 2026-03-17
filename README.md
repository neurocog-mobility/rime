# RIME

> **Multimodal (Video + Signals) Annotator with Smart Copilot for Parkinson's Disease Research**

## Quick Start

```bash
# Create virtual environment (already done)
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Launch the application
rime
# or: python -m rime

# Launch and open a session directly
rime --open sample-data/ses-01/session.json
# or: python -m rime --open sample-data/ses-01/session.json
```

## Open Sample Session

1. Launch RIME
2. File → Open Session (Ctrl+O)
3. Navigate to `sample-data/ses-01/session.json`

## Project Structure

```
rime/
├── src/rime/
│   ├── core/           # Data models (Session, Signal, Annotations)
│   ├── ui/             # PySide6 widgets (MainWindow, Timeline, Player)
│   └── app.py          # Application entry point
├── sample-data/        # Example sessions
└── docs/               # Specifications
```

## v0.1 Features

- [x] Session loading (session.json manifest)
- [x] CSV signal loading with time unit conversion
- [x] L1-L5 annotation hierarchy
- [x] Basic video player with playback controls
- [x] Timeline widget (stub with swimlane placeholders)
- [ ] Signal plotting
- [ ] Multi-view video sync
- [ ] CMF model loading

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
ruff format src/
```
