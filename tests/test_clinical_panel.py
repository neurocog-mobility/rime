from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rime_core.context import WorkingContext
from rime_core.coverage import CoverageSpec
from rime_core.session import ClinicalMetricSpec, VideoConfig
from rime_ui.clinical_panel import ClinicalPanel


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_clinical_panel_reloading_lane_denominator_does_not_duplicate_rows(tmp_path: Path) -> None:
    _app()
    ctx = WorkingContext.create(
        session_dir=tmp_path / "clinical-session",
        name="Clinical",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    metric = ClinicalMetricSpec(
        name="FOG walking",
        numerator=[{"lane": "FOG", "label": "FOG"}],
        denominator_type="lane",
        denominator=[{"lane": "Tasks", "label": "Walk"}],
    )
    ctx.update_clinical_metrics([metric])

    reopened = WorkingContext.open(ctx.session.session_dir)
    panel = ClinicalPanel()
    panel.refresh(reopened, 30_000.0)

    assert len(panel._denominator_rows) == 1
    assert panel._denominator_rows[0].spec() == CoverageSpec(lane="Tasks", label="Walk")

    panel._load_saved_metric_from_row(0)

    assert len(panel._denominator_rows) == 1
    assert panel._denominator_rows[0].spec() == CoverageSpec(lane="Tasks", label="Walk")

    panel._load_metric(metric)

    assert len(panel._denominator_rows) == 1
    assert panel._denominator_rows[0].spec() == CoverageSpec(lane="Tasks", label="Walk")


def test_clinical_panel_only_offers_interval_non_notes_lanes(tmp_path: Path) -> None:
    _app()
    ctx = WorkingContext.create(
        session_dir=tmp_path / "clinical-lanes-session",
        name="Clinical Lanes",
        videos=[VideoConfig(path="video.mp4", role="primary")],
    )
    panel = ClinicalPanel()
    panel.refresh(ctx, 30_000.0)

    lane_names = [panel._numerator_rows[0].lane_combo.itemData(i) for i in range(panel._numerator_rows[0].lane_combo.count())]

    assert "FOG" in lane_names
    assert "Tasks" in lane_names
    assert "Steps" not in lane_names
    assert "Notes" not in lane_names
