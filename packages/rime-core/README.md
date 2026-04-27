# neurocog-rime-core

`neurocog-rime-core` is the headless domain layer for RIME. It provides session models, protocol schemas, annotation storage, rule evaluation, signal loading, ELAN import, export utilities, IRR/coverage/evaluation metrics, and CMF-based model inference helpers.

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

from rime_core.annotation import AnnotationStore
from rime_core.schema import ProtocolSchema
from rime_core.sessions import VideoConfig, create_session
from rime_core.workspace import WorkingContext

session = create_session(
    session_dir=Path("example-session"),
    name="Example Session",
    videos=[VideoConfig(path="video.mp4", role="primary")],
)

context = WorkingContext.open(session.session_dir)
schema = ProtocolSchema.default()
store = AnnotationStore()

print(session.name)
print(context.session.session_dir)
print(schema.get_lane_names()[:3])
print(len(store.all()))
```

## Main Modules

- `rime_core.annotation`: annotations, review, and rule helpers
- `rime_core.analysis`: coverage, IRR, and model-evaluation utilities
- `rime_core.io`: import/export and signal-loading helpers
- `rime_core.modeling`: CMF package loading and inference
- `rime_core.sessions`: session dataclasses and persistence
- `rime_core.workspace`: live session orchestration
