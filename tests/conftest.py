from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCES = (
    ROOT / "packages" / "rime-core" / "src",
    ROOT / "packages" / "rime-ui" / "src",
)

for source_root in PACKAGE_SOURCES:
    source_path = str(source_root)
    if source_path not in sys.path:
        sys.path.insert(0, source_path)
