"""按分数语义分桶的阈值搜索。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.detectors.base import VALID_SCORE_TYPES

_UNIT_INTERVAL = {"pvalue", "prob"}


@dataclass(frozen=True, eq=False)
class ThresholdResult:
    threshold: float
    precision: float
    recall: float
    f1: float
    n_flagged: int


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def search_threshold(
    scores: np.ndarray,
    score_type: str,
    truth: np.ndarray | None,
    candidates: int = 200,
) -> ThresholdResult:
    """在候选阈值上搜索 F1 最优；并列时取召回更高者。"""
    if score_type not in VALID_SCORE_TYPES:
        raise ValueError(f"未知 score_type: {score_type!r}")
    if truth is None:
        raise ValueError("阈值搜索必须有真值")
    truth = np.asarray(truth)
    if truth.dtype == object and all(item is None for item in truth.ravel()):
        raise ValueError("阈值搜索必须有真值")
    truth = truth.astype(bool)

    scores = np.asarray(scores, dtype=float)
    if scores.shape != truth.shape:
        raise ValueError("scores 与 truth 形状不一致")
    if candidates < 2:
        raise ValueError("candidates 至少为 2")

    if score_type in _UNIT_INTERVAL:
        hi = 1.0
    else:
        hi = float(np.nanmax(scores)) if scores.size else 0.0
    if not np.isfinite(hi) or hi <= 0:
        hi = 1.0
    grid = np.linspace(0.0, hi, candidates)

    best: ThresholdResult | None = None
    for threshold in grid:
        pred = scores > threshold
        tp = int(np.sum(pred & truth))
        fp = int(np.sum(pred & ~truth))
        fn = int(np.sum(~pred & truth))
        precision, recall, f1 = _prf(tp, fp, fn)
        candidate = ThresholdResult(
            threshold=float(threshold),
            precision=precision,
            recall=recall,
            f1=f1,
            n_flagged=int(pred.sum()),
        )
        if best is None or (candidate.f1, candidate.recall) > (best.f1, best.recall):
            best = candidate
    assert best is not None
    return best
