from __future__ import annotations

import pytest

from rime_core import Annotation, evaluate_model


def test_perfect_prediction_scores_are_one() -> None:
    predictions = [
        Annotation(
            id="p1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=500.0,
            source="model:demo",
            ghost=True,
        )
    ]
    ground_truth = [
        Annotation(
            id="g1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=500.0,
            source="manual",
        )
    ]

    result = evaluate_model(predictions, ground_truth, duration_ms=1000.0)

    assert result.model_name == "demo"
    assert result.iou == 1.0
    assert result.f1 == 1.0
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.onset_error_ms == 0.0
    assert result.onset_error_sd_ms == float("inf")
    assert result.n_tp == 1
    assert result.n_fp == 0
    assert result.n_fn == 0


def test_no_predictions_gives_zero_recall_and_f1() -> None:
    ground_truth = [
        Annotation(
            id="g1",
            lane="FOG",
            label="FOG",
            start_ms=100.0,
            end_ms=500.0,
            source="manual",
        )
    ]

    result = evaluate_model([], ground_truth, duration_ms=1000.0)

    assert result.iou == 0.0
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.f1 == 0.0
    assert result.onset_error_ms == float("inf")
    assert result.onset_error_sd_ms == float("inf")
    assert result.n_episodes_model == 0
    assert result.n_episodes_human == 1
    assert result.n_tp == 0
    assert result.n_fp == 0
    assert result.n_fn == 1


def test_partial_overlap_matches_manual_calculation() -> None:
    predictions = [
        Annotation(
            id="p1",
            lane="FOG",
            label="FOG",
            start_ms=400.0,
            end_ms=800.0,
            source="model:demo",
        )
    ]
    ground_truth = [
        Annotation(
            id="g1",
            lane="FOG",
            label="FOG",
            start_ms=200.0,
            end_ms=600.0,
            source="manual",
        )
    ]

    result = evaluate_model(predictions, ground_truth, duration_ms=1000.0)

    assert result.iou == pytest.approx(200.0 / 600.0)
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(0.5)
    assert result.f1 == pytest.approx(0.5)
    assert result.onset_error_ms == 200.0
    assert result.onset_error_sd_ms == float("inf")
    assert result.n_tp == 1
    assert result.n_fp == 0
    assert result.n_fn == 0


def test_point_event_evaluation_uses_tolerance_matching() -> None:
    predictions = [
        Annotation(
            id="p1",
            lane="Steps",
            label="step",
            start_ms=1000.0,
            end_ms=1000.0,
            event_type="point",
            source="model:demo",
        ),
        Annotation(
            id="p2",
            lane="Steps",
            label="step",
            start_ms=1800.0,
            end_ms=1800.0,
            event_type="point",
            source="model:demo",
        ),
    ]
    ground_truth = [
        Annotation(
            id="g1",
            lane="Steps",
            label="step",
            start_ms=900.0,
            end_ms=900.0,
            event_type="point",
        ),
        Annotation(
            id="g2",
            lane="Steps",
            label="step",
            start_ms=2500.0,
            end_ms=2500.0,
            event_type="point",
        ),
    ]

    result = evaluate_model(predictions, ground_truth, duration_ms=5000.0, tolerance_ms=150.0)

    assert result.model_name == "demo"
    assert result.iou == 0.0
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(0.5)
    assert result.f1 == pytest.approx(0.5)
    assert result.onset_error_ms == pytest.approx((100.0 + 700.0) / 2.0)
    assert result.onset_error_sd_ms == pytest.approx(300.0)
    assert result.n_tp == 1
    assert result.n_fp == 1
    assert result.n_fn == 1
