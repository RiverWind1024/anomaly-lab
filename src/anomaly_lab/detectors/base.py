"""Detector 协议：分数越大越异常，score_type 显式声明语义。"""

from __future__ import annotations

import time
from typing import Protocol

import numpy as np

from anomaly_lab.contracts import DetectionResult, ScoreType, SeriesBundle
from anomaly_lab.detectors.bands import Bands

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
    bands: Bands | None = None,
    scale_source: str | None = None,
    status: str = "ok",
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
        expected=None if bands is None else np.asarray(bands.baseline, dtype=float),
        lower=None if bands is None else np.asarray(bands.lower, dtype=float),
        upper=None if bands is None else np.asarray(bands.upper, dtype=float),
        band_kind=None if bands is None else bands.kind,
        scale_source=scale_source,
        status=status,
    )


class TimedDetector:
    """给具体检测器复用：计时 + 统一构造 DetectionResult。"""

    name: str = ""
    score_type: str = ""
    default_threshold: float = 0.0

    def estimate_values(self, values: np.ndarray) -> np.ndarray:
        """**估计**用的值：周期、基线、分解都基于它。

        默认返回原始值。子类可以返回**清洗后**的值，让最小二乘 / 频域
        这类不稳健的估计量不被离群点带偏。

        注意这条约定是单向的：**打分必须用原始值**（见 `score`）。
        把异常点从打分输入里洗掉，检测器就看不见它了。
        """
        return np.asarray(values, dtype=float)

    def bands(self, series: SeriesBundle, threshold: float) -> Bands | None:
        """基线 + 双向上下界；默认不支持基线（返回 None）。

        支持基线的检测器覆盖这个方法。`expected` 是"正常值应该在哪儿"，
        `lower`/`upper` 是容忍带 —— 超出即异常。
        """
        return None

    def _timed_detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        started = time.perf_counter()
        scores = self.score(series)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        chosen = self.default_threshold if threshold is None else float(threshold)
        # 基线是**可选输出**：检测器没实现就返回 None，不影响主流程
        bands = self.bands(series, chosen)

        # 尺度来源由检测器在 `_center_scale` 里写进实例属性 ——
        # 这样 `make_result` 不必改签名，也能把「降级」暴露到结果里。
        source = getattr(self, "_last_scale_source", None)
        status = getattr(self, "_last_status", None) or (
            "undetermined" if source == "none" else "ok"
        )
        return make_result(
            series,
            scores,
            self.score_type,
            chosen,
            self.name,
            elapsed_ms,
            bands=bands,
            scale_source=source,
            status=status,
        )
