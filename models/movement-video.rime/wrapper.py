"""Movement detector via OpenCV CSRT object tracker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def _load_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - runtime environment dependent
        raise RuntimeError(
            "opencv-contrib-python is required for CSRT tracking. "
            "Install with: pip install opencv-contrib-python"
        ) from exc
    return cv2


def _create_tracker(cv2: Any) -> Any:
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    raise RuntimeError("OpenCV CSRT tracker is unavailable in this build")


def _normalised_bbox_to_rect(subject_bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    bx, by, bw, bh = [float(value) for value in subject_bbox]
    x = int(round(bx * width))
    y = int(round(by * height))
    w = max(1, int(round(bw * width)))
    h = max(1, int(round(bh * height)))
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = min(w, width - x)
    h = min(h, height - y)
    return (x, y, w, h)


def _smooth_displacements(
    displacements: np.ndarray,
    smoothing_frames: int,
) -> np.ndarray:
    smoothed = np.full_like(displacements, np.nan)
    radius = smoothing_frames // 2
    for idx in range(len(displacements)):
        window = displacements[max(0, idx - radius) : idx + radius + 1]
        valid = window[np.isfinite(window)]
        if valid.size:
            smoothed[idx] = float(np.mean(valid))
    return smoothed


def _binary_to_bouts(
    times_ms: np.ndarray,
    mask: np.ndarray,
    min_bout_ms: int,
    merge_gap_ms: int,
) -> np.ndarray:
    if not np.any(mask):
        return np.zeros((0, 2), dtype=np.float64)

    bouts: list[tuple[float, float]] = []
    in_bout = False
    bout_start = 0.0
    for idx, active in enumerate(mask):
        if active and not in_bout:
            bout_start = float(times_ms[idx])
            in_bout = True
        elif not active and in_bout:
            bouts.append((bout_start, float(times_ms[idx - 1])))
            in_bout = False
    if in_bout:
        bouts.append((bout_start, float(times_ms[-1])))

    merged: list[tuple[float, float]] = []
    for start_ms, end_ms in bouts:
        if merged and start_ms - merged[-1][1] < merge_gap_ms:
            merged[-1] = (merged[-1][0], end_ms)
        else:
            merged.append((start_ms, end_ms))

    filtered = [(start_ms, end_ms) for start_ms, end_ms in merged if (end_ms - start_ms) >= min_bout_ms]
    if not filtered:
        return np.zeros((0, 2), dtype=np.float64)
    return np.asarray(filtered, dtype=np.float64)


def run_movement_detection(
    video_path: Path,
    subject_bbox: list[float],
    *,
    start_ms: float = 0.0,
    end_ms: float | None = None,
    movement_threshold: float = 0.005,
    smoothing_window_ms: int = 500,
    min_bout_ms: int = 1000,
    merge_gap_ms: int = 500,
) -> dict[str, Any]:
    cv2 = _load_cv2()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    frame_width = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0)
    local_end_ms = None if end_ms is None else max(0.0, float(end_ms) - float(start_ms))

    if start_ms:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(start_ms))

    ok, first_frame = cap.read()
    if not ok:
        cap.release()
        return {
            "times_ms": np.zeros(0, dtype=np.float64),
            "displacements": np.zeros(0, dtype=np.float64),
            "smoothed": np.zeros(0, dtype=np.float64),
            "moving_mask": np.zeros(0, dtype=bool),
            "centers_x": np.zeros(0, dtype=np.float64),
            "centers_y": np.zeros(0, dtype=np.float64),
            "init_rect": np.zeros(4, dtype=np.float64),
            "frame_width_px": 0,
            "frame_height_px": 0,
            "bouts": np.zeros((0, 2), dtype=np.float64),
        }

    frame_height, frame_width_px = first_frame.shape[:2]
    init_rect = _normalised_bbox_to_rect(subject_bbox, frame_width_px, frame_height)
    tracker = _create_tracker(cv2)
    tracker.init(first_frame, init_rect)

    cx_prev = init_rect[0] + init_rect[2] / 2.0
    cy_prev = init_rect[1] + init_rect[3] / 2.0
    frame_idx = 0
    frame_times_ms: list[float] = [0.0]
    displacements: list[float] = [0.0]
    centers_x: list[float] = [cx_prev]
    centers_y: list[float] = [cy_prev]

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_idx += 1
        time_ms = frame_idx / fps * 1000.0
        if local_end_ms is not None and time_ms > local_end_ms:
            break

        ok, rect = tracker.update(frame)
        frame_times_ms.append(time_ms)
        if not ok:
            displacements.append(float("nan"))
            centers_x.append(float("nan"))
            centers_y.append(float("nan"))
            continue

        cx = rect[0] + rect[2] / 2.0
        cy = rect[1] + rect[3] / 2.0
        disp = abs(cx - cx_prev) / frame_width
        cx_prev = cx
        cy_prev = cy
        displacements.append(float(disp))
        centers_x.append(float(cx))
        centers_y.append(float(cy))

    cap.release()

    times_ms = np.asarray(frame_times_ms, dtype=np.float64)
    displacement_array = np.asarray(displacements, dtype=np.float64)
    center_x_array = np.asarray(centers_x, dtype=np.float64)
    center_y_array = np.asarray(centers_y, dtype=np.float64)
    if times_ms.size < 3:
        return {
            "times_ms": times_ms,
            "displacements": displacement_array,
            "smoothed": displacement_array.copy(),
            "moving_mask": np.zeros(times_ms.shape, dtype=bool),
            "centers_x": center_x_array,
            "centers_y": center_y_array,
            "init_rect": np.asarray(init_rect, dtype=np.float64),
            "frame_width_px": frame_width_px,
            "frame_height_px": frame_height,
            "bouts": np.zeros((0, 2), dtype=np.float64),
        }

    smoothing_frames = max(1, int(round(fps * smoothing_window_ms / 1000.0)))
    smoothed = _smooth_displacements(displacement_array, smoothing_frames)
    moving_mask = np.isfinite(smoothed) & (smoothed >= float(movement_threshold))
    bouts = _binary_to_bouts(
        times_ms,
        moving_mask,
        int(min_bout_ms),
        int(merge_gap_ms),
    )
    return {
        "times_ms": times_ms,
        "displacements": displacement_array,
        "smoothed": smoothed,
        "moving_mask": moving_mask,
        "centers_x": center_x_array,
        "centers_y": center_y_array,
        "init_rect": np.asarray(init_rect, dtype=np.float64),
        "frame_width_px": frame_width_px,
        "frame_height_px": frame_height,
        "bouts": bouts,
    }


class CMFModel:
    def __init__(self, model_dir: str) -> None:
        with open(Path(model_dir) / "config.json", "r", encoding="utf-8") as handle:
            cfg = json.load(handle)
        self._defaults = {param["name"]: param["default"] for param in cfg.get("parameters", [])}

    def predict(
        self,
        inputs: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, np.ndarray]:
        params = params or {}
        video_input = inputs["video"]
        subject_bbox = params.get("subject_bbox", self._defaults.get("subject_bbox"))
        if subject_bbox is None:
            raise ValueError("subject_bbox is required")

        result = run_movement_detection(
            Path(video_input.path),
            list(subject_bbox),
            start_ms=float(video_input.start_ms),
            end_ms=None if video_input.end_ms is None else float(video_input.end_ms),
            movement_threshold=float(
                params.get("movement_threshold", self._defaults.get("movement_threshold", 0.005))
            ),
            smoothing_window_ms=int(
                params.get("smoothing_window_ms", self._defaults.get("smoothing_window_ms", 500))
            ),
            min_bout_ms=int(params.get("min_bout_ms", self._defaults.get("min_bout_ms", 1000))),
            merge_gap_ms=int(params.get("merge_gap_ms", self._defaults.get("merge_gap_ms", 500))),
        )
        return {"moving_bouts": result["bouts"]}
