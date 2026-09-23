# neurocog-rime-core

`neurocog-rime-core` is the headless domain layer for RIME. It provides native clinical objects, protocol schemas, annotation storage, rule evaluation, signal loading, ELAN import, export utilities, IRR/coverage/evaluation metrics, and CMF-based model inference helpers.

## Install

```bash
pip install neurocog-rime-core
```

For local development:

```bash
pip install -e packages/rime-core
```

Optional extras:

```bash
pip install -e "packages/rime-core[onnx,video]"
```

## Quick Start

```python
from pathlib import Path
from rime_core import WorkingContext, ResearchContext

context = WorkingContext.create_workspace(
    Path("example-workspace"), "Example",
    research=ResearchContext(participant_id="SYNTHETIC"),
)
annotation, _ = context.create_annotation("FOG", "FOG", 1000, 2000)
reopened = WorkingContext.open(context.workspace.path)
print(reopened.annotation_set.id, reopened.store.get(annotation.id))
```

## Main Modules

- `rime_core.annotation`: annotations, review, and rule helpers
- `rime_core.analysis`: coverage, IRR, and model-evaluation utilities
- `rime_core.io`: import/export and signal-loading helpers
- `rime_core.modeling`: CMF package loading and inference
- `rime_core.records`: scientific objects with their own identities
- `rime_core.workspace`: local persistence and operations coordinating scientific objects
