"""Detector 协议：分数越大越异常，score_type 显式声明语义。"""

from __future__ import annotations

import time
from typing import Protocol

import numpy as np

from anomaly_lab.contracts import DetectionResult, ScoreType, SeriesBundle

VALID_SCORE_TYPES: frozenset[str] = frozenset(
    {"zscore", "pvalue", "residual_ratio", "prob"}
)


class Detector(Protocol):
    name: str
    score_type: ScoreType

    def fit(self, series: SeriesBundle) -> Detector: ...

    def score(self, series: SeriesBundle) -> np.ndarray: ...

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult: ...


def validate_detector(detector: object) -> None:
    score_type = getattr(detector, "score_type", None)
    if score_type not in VALID_SCORE_TYPES:
        raise ValueError(
            f"非法 score_type={score_type!r}，必须是 {sorted(VALID_SCORE_TYPES)} 之一"
        )
    name = getattr(detector, "name", None)
    if not isinstance(name, str) or not name:
        raise TypeError("detector.name 必须是非空字符串")
    for method in ("fit", "score", "detect"):
        if not callable(getattr(detector, method, None)):
            raise TypeError(f"detector 缺少方法: {method}")


def make_result(
    series: SeriesBundle,
    scores: np.ndarray,
    score_type: str,
    threshold: float,
    detector: str,
    elapsed_ms: float,
) -> DetectionResult:
    scores = np.asarray(scores, dtype=float)
    return DetectionResult(
        series_id=series.series_id,
        scores=scores,
        score_type=score_type,  # type: ignore[arg-type]
        is_anomaly=scores > threshold,
        threshold=float(threshold),
        detector=detector,
        elapsed_ms=float(elapsed_ms),
    )


class TimedDetector:
    """给具体检测器复用：计时 + 统一构造 DetectionResult。"""

    name: str = ""
    score_type: str = ""
    default_threshold: float = 0.0

    def _timed_detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        started = time.perf_counter()
        scores = self.score(series)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        chosen = self.default_threshold if threshold is None else float(threshold)
        return make_result(
            series, scores, self.score_type, chosen, self.name, elapsed_ms
        )
