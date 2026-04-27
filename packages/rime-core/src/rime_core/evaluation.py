"""Model-vs-human evaluation metrics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rime_core.annotations import Annotation
from rime_core.common.intervals import annotation_iou


@dataclass
class EvalResult:
    """Aggregate metrics comparing predicted and human annotations."""

    model_name: str
    iou: float
    f1: float
    precision: float
    recall: float
    onset_error_ms: float
    onset_error_sd_ms: float
    n_episodes_model: int
    n_episodes_human: int
    n_tp: int
    n_fp: int
    n_fn: int


def evaluate_model(
    predictions: list[Annotation],
    ground_truth: list[Annotation],
    duration_ms: float,
    tolerance_ms: float = 200.0,
) -> EvalResult:
    """Compare prediction annotations against ground-truth annotations.

    Both lists should be pre-filtered to the lane of interest by the caller.
    """
    all_annotations = predictions + ground_truth
    if all_annotations and all(annotation.event_type == "point" for annotation in all_annotations):
        return evaluate_point_events(
            predictions,
            ground_truth,
            duration_ms,
            tolerance_ms=tolerance_ms,
        )

    return _evaluate_intervals(predictions, ground_truth, duration_ms)


def _evaluate_intervals(
    predictions: list[Annotation],
    ground_truth: list[Annotation],
    duration_ms: float,
) -> EvalResult:
    """Compare interval predictions against ground-truth interval annotations."""
    tp, fp, fn = _episode_match_intervals(predictions, ground_truth)
    onset_mean, onset_sd = _onset_error_ms(predictions, ground_truth, duration_ms)
    pred_mask = _to_frame_mask(predictions, duration_ms)
    gt_mask = _to_frame_mask(ground_truth, duration_ms)

    intersection = np.logical_and(pred_mask, gt_mask).sum()
    union = np.logical_or(pred_mask, gt_mask).sum()
    pred_sum = pred_mask.sum()
    gt_sum = gt_mask.sum()

    iou = float(intersection / union) if union else 0.0
    precision = float(intersection / pred_sum) if pred_sum else 0.0
    recall = float(intersection / gt_sum) if gt_sum else 0.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return EvalResult(
        model_name=_model_name(predictions),
        iou=iou,
        f1=f1,
        precision=precision,
        recall=recall,
        onset_error_ms=onset_mean,
        onset_error_sd_ms=onset_sd,
        n_episodes_model=len(predictions),
        n_episodes_human=len(ground_truth),
        n_tp=tp,
        n_fp=fp,
        n_fn=fn,
    )


def evaluate_point_events(
    predictions: list[Annotation],
    ground_truth: list[Annotation],
    duration_ms: float,
    tolerance_ms: float = 200.0,
) -> EvalResult:
    """Compare instantaneous events using greedy tolerance-window matching."""
    pred_times = sorted(annotation.start_ms for annotation in predictions)
    gt_times = sorted(annotation.start_ms for annotation in ground_truth)
    tp, fp, fn = _tolerance_match(pred_times, gt_times, tolerance_ms)
    onset_mean, onset_sd = _onset_error_ms(predictions, ground_truth, duration_ms)

    precision = float(tp / (tp + fp)) if (tp + fp) else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) else 0.0
    f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return EvalResult(
        model_name=_model_name(predictions),
        iou=0.0,
        f1=f1,
        precision=precision,
        recall=recall,
        onset_error_ms=onset_mean,
        onset_error_sd_ms=onset_sd,
        n_episodes_model=len(predictions),
        n_episodes_human=len(ground_truth),
        n_tp=tp,
        n_fp=fp,
        n_fn=fn,
    )


def _to_frame_mask(
    annotations: list[Annotation],
    duration_ms: float,
    resolution_ms: float = 10.0,
) -> np.ndarray:
    """Convert span annotations to a frame-level binary mask."""
    if duration_ms <= 0:
        return np.zeros(0, dtype=bool)

    frame_count = int(np.ceil(duration_ms / resolution_ms))
    mask = np.zeros(frame_count, dtype=bool)
    for annotation in annotations:
        start = max(0.0, annotation.start_ms)
        end = min(duration_ms, annotation.end_ms)
        if end <= start:
            continue
        start_idx = int(np.floor(start / resolution_ms))
        end_idx = int(np.ceil(end / resolution_ms))
        mask[start_idx:end_idx] = True
    return mask


def _model_name(predictions: list[Annotation]) -> str:
    if not predictions:
        return ""
    source = predictions[0].source
    if source.startswith("model:"):
        return source.split(":", 1)[1]
    return source


def _onset_error_ms(
    predictions: list[Annotation],
    ground_truth: list[Annotation],
    duration_ms: float,
) -> tuple[float, float]:
    if not predictions or not ground_truth:
        return float("inf"), float("inf")

    pred_starts = [annotation.start_ms for annotation in sorted(predictions, key=lambda ann: ann.start_ms)]
    gt_starts = [annotation.start_ms for annotation in sorted(ground_truth, key=lambda ann: ann.start_ms)]
    unmatched_preds = set(range(len(pred_starts)))
    unmatched_gt = set(range(len(gt_starts)))
    errors: list[float] = []

    while unmatched_preds and unmatched_gt:
        best_pair: tuple[int, int] | None = None
        best_error = float("inf")
        for pred_idx in unmatched_preds:
            for gt_idx in unmatched_gt:
                error = abs(pred_starts[pred_idx] - gt_starts[gt_idx])
                if error < best_error:
                    best_error = error
                    best_pair = (pred_idx, gt_idx)
        if best_pair is None:
            break
        pred_idx, gt_idx = best_pair
        unmatched_preds.remove(pred_idx)
        unmatched_gt.remove(gt_idx)
        errors.append(min(best_error, duration_ms))

    if not errors:
        return float("inf"), float("inf")

    mean = float(np.mean(errors))
    if len(errors) < 2:
        return mean, float("inf")
    return mean, float(np.std(errors))


def _episode_match_intervals(
    predictions: list[Annotation],
    ground_truth: list[Annotation],
    iou_threshold: float = 0.1,
) -> tuple[int, int, int]:
    unmatched_pred = set(range(len(predictions)))
    unmatched_gt = set(range(len(ground_truth)))
    tp = 0

    while unmatched_pred and unmatched_gt:
        best_pair: tuple[int, int] | None = None
        best_iou = 0.0
        for pred_idx in unmatched_pred:
            for gt_idx in unmatched_gt:
                score = annotation_iou(predictions[pred_idx], ground_truth[gt_idx])
                if score > best_iou:
                    best_iou = score
                    best_pair = (pred_idx, gt_idx)
        if best_pair is None or best_iou < iou_threshold:
            break
        pred_idx, gt_idx = best_pair
        unmatched_pred.remove(pred_idx)
        unmatched_gt.remove(gt_idx)
        tp += 1

    return tp, len(unmatched_pred), len(unmatched_gt)


def _tolerance_match(
    pred_times: list[float],
    gt_times: list[float],
    tolerance_ms: float,
) -> tuple[int, int, int]:
    unmatched_pred = list(range(len(pred_times)))
    unmatched_gt = list(range(len(gt_times)))
    tp = 0

    while unmatched_pred and unmatched_gt:
        best_pred_idx: int | None = None
        best_gt_idx: int | None = None
        best_error = float("inf")
        for pred_idx in unmatched_pred:
            for gt_idx in unmatched_gt:
                error = abs(pred_times[pred_idx] - gt_times[gt_idx])
                if error < best_error:
                    best_error = error
                    best_pred_idx = pred_idx
                    best_gt_idx = gt_idx
        if best_pred_idx is None or best_gt_idx is None or best_error > tolerance_ms:
            break
        unmatched_pred.remove(best_pred_idx)
        unmatched_gt.remove(best_gt_idx)
        tp += 1

    return tp, len(unmatched_pred), len(unmatched_gt)
