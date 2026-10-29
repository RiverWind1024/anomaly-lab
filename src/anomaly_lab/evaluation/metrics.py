"""点级与区间级评估指标。区间统一为闭区间 (start, end)。"""

from __future__ import annotations

import numpy as np


def precision_recall_f1(
    pred: np.ndarray, truth: np.ndarray
) -> tuple[float, float, float]:
    pred = np.asarray(pred).astype(bool)
    truth = np.asarray(truth).astype(bool)
    tp = float(np.sum(pred & truth))
    fp = float(np.sum(pred & ~truth))
    fn = float(np.sum(~pred & truth))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def _segments(mask: np.ndarray) -> list[tuple[int, int]]:
    mask = np.asarray(mask).astype(bool)
    padded = np.concatenate([[False], mask, [False]])
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:]) - 1
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def point_adjusted_prf(
    pred: np.ndarray, truth: np.ndarray, delay: int = 5
) -> tuple[float, float, float]:
    """只要真值区间后 delay 点内出现过预测，就认为整个区间被检出。"""
    pred = np.asarray(pred).astype(bool).copy()
    truth = np.asarray(truth).astype(bool)
    delay = max(0, int(delay))
    for start, end in _segments(truth):
        if pred[start : end + delay + 1].any():
            pred[start : end + 1] = True
    return precision_recall_f1(pred, truth)


def _length(interval: tuple[int, int]) -> float:
    return float(max(0, interval[1] - interval[0]))


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> float:
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return float(max(0, hi - lo))


def interval_iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = _overlap(a, b)
    union = _length(a) + _length(b) - inter
    if union <= 0:
        return 1.0 if a == b else 0.0
    return inter / union


def range_based_prf(
    pred_intervals: list[tuple[int, int]],
    truth_intervals: list[tuple[int, int]],
    beta: float = 2.0,
) -> tuple[float, float, float]:
    """区间级 P/R/F：按重叠长度占各自区间长度的比例计算。"""
    pred = [(int(s), int(e)) for s, e in pred_intervals if e >= s]
    truth = [(int(s), int(e)) for s, e in truth_intervals if e >= s]
    if not pred and not truth:
        return 1.0, 1.0, 1.0

    def _coverage(targets: list[tuple[int, int]], others: list[tuple[int, int]]) -> float:
        total = sum(_length(item) for item in targets)
        if total <= 0:
            return 0.0
        covered = sum(
            max((_overlap(item, other) for other in others), default=0.0)
            for item in targets
        )
        return min(1.0, covered / total)

    precision = _coverage(pred, truth) if pred else 0.0
    recall = _coverage(truth, pred) if truth else 1.0
    if precision + recall <= 0:
        return precision, recall, 0.0
    beta2 = beta * beta
    fbeta = (1 + beta2) * precision * recall / (beta2 * precision + recall)
    return precision, recall, fbeta


def detection_delay(pred: np.ndarray, truth: np.ndarray) -> int:
    """首次预测相对首次真值的延迟；未检出返回 -1，提前检出记 0。"""
    pred = np.asarray(pred).astype(bool)
    truth = np.asarray(truth).astype(bool)
    truth_idx = np.flatnonzero(truth)
    pred_idx = np.flatnonzero(pred)
    if truth_idx.size == 0 or pred_idx.size == 0:
        return -1
    return int(max(0, pred_idx[0] - truth_idx[0]))
