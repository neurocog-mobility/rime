# Installation

These guides describe the v0.2 development application. To use the current checkout,
install from the repository root with Python 3.10 or later:

```sh
python -m venv .venv
source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -e packages/rime-core -e packages/rime-ui
rime
```

For the published packages, use `pip install neurocog-rime-core neurocog-rime-ui`;
the published release may differ from this development guide.

Open a workspace or measurement document directly:

```sh
rime --open /path/to/workspace.json
rime --open /path/to/measurements.rime
```

`python -m rime_ui` is an alternative launcher. Start with
[your first workspace](first-session.md) or the [examples](../examples.md).
