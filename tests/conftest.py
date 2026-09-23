from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCES = (
    ROOT / "packages" / "rime-core" / "src",
    ROOT / "packages" / "rime-ui" / "src",
)

if os.environ.get("RIME_TEST_INSTALLED") != "1":
    for source_root in PACKAGE_SOURCES:
        source_path = str(source_root)
        if source_path not in sys.path:
            sys.path.insert(0, source_path)
else:
    import rime_core
    import rime_ui

    for module in (rime_core, rime_ui):
        assert not Path(module.__file__).resolve().is_relative_to(ROOT / "packages"), (
            "Installed-package checks must not import the checkout"
        )
