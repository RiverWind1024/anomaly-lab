"""可解释的 6 类形态判别规则。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.classification.features import FeatureVector, acf, extract_features
from anomaly_lab.classification.recommend import Recommendation, recommend_for
from anomaly_lab.contracts import MetricClass, SeriesBundle

# 经验阈值：sparse_event 的零值占比远高于 high_zero_ratio（后者上限约 0.9）
_HIGH_ZERO_RATIO = 0.6
_CHANGEPOINT_THRESHOLD = 0.7
_TREND_THRESHOLD = 0.3
_ADF_ALPHA = 0.05
#: 趋势强度高到不可能是周期型的门槛（step / stationary 判据也用它）
_STRONG_TREND = 0.9


@dataclass(frozen=True, eq=False)
class ClassificationResult:
    series_id: str
    metric_class: MetricClass
    confidence: float
    reasons: list[str]
    features: FeatureVector
    recommendation: Recommendation


def _acf_peak(values: np.ndarray, period: int | None) -> float:
    if not period:
        return 0.0
    if len(values) >= 2:
        t = np.arange(len(values), dtype=float)
        values = values - np.polyval(np.polyfit(t, values, 1), t)
    acf_vals = acf(values)
    if len(acf_vals) <= period or abs(acf_vals[0]) < 1e-9:
        return 0.0
    return float(acf_vals[period] / acf_vals[0])


def _classify_features(values: np.ndarray, f: FeatureVector) -> tuple[MetricClass, float, list[str]]:
    n_nonzero = f.n_nonzero
    run_limit = max(5, int(0.02 * f.n_samples))
    if f.zero_ratio >= _HIGH_ZERO_RATIO and f.n_nonzero_runs <= run_limit:
        confidence = 0.6 + 0.39 * min(1.0, (run_limit - f.n_nonzero_runs) / run_limit)
        return (
            "sparse_event",
            confidence,
            [
                (
                    f"零值占比 {f.zero_ratio:.1%}（非零点 {n_nonzero} 个，"
                    f"连续段 {f.n_nonzero_runs} 个）→ 稀疏事件型"
                )
            ],
        )

    if f.zero_ratio >= _HIGH_ZERO_RATIO:
        margin = (f.zero_ratio - _HIGH_ZERO_RATIO) / (1 - _HIGH_ZERO_RATIO)
        confidence = 0.6 + 0.39 * min(1.0, margin)
        return (
            "high_zero_ratio",
            confidence,
            [f"零值占比 {f.zero_ratio:.1%} → 高零值比例型"],
        )

    if f.dominant_period is not None and f.trend_strength < _STRONG_TREND:
        # 「趋势弱」是必要条件：强趋势序列去趋势后会留下被误认成周期的
        # 残留结构（实测 trending 序列的伪周期 ACF 峰 0.862，比真周期的
        # 0.273 还高——只看 ACF 峰会被骗）。真周期序列的趋势强度都在 0.43 以下。
        peak = _acf_peak(values, f.dominant_period)
        confidence = 0.6 + 0.39 * min(1.0, max(0.0, (peak - 0.2) / 0.8))
        return (
            "periodic",
            confidence,
            [
                f"主周期 lag={f.dominant_period}（ACF r={peak:.2f}）→ 周期型",
                f"趋势强度 {f.trend_strength:.2f} < {_STRONG_TREND} → 排除趋势残留",
            ],
        )

    if f.changepoint_score >= _CHANGEPOINT_THRESHOLD and f.trend_strength < 0.9:
        confidence = 0.6 + 0.39 * min(
            1.0, (f.changepoint_score - _CHANGEPOINT_THRESHOLD) / (1 - _CHANGEPOINT_THRESHOLD)
        )
        return (
            "step",
            confidence,
            [
                f"变点强度 {f.changepoint_score:.2f} ≥ {_CHANGEPOINT_THRESHOLD}",
                f"线性趋势弱（{f.trend_strength:.2f}）→ 阶梯型",
            ],
        )

    adf_ok = np.isfinite(f.adf_pvalue) and f.adf_pvalue < _ADF_ALPHA
    if adf_ok and f.trend_strength < _TREND_THRESHOLD:
        confidence = 0.6 + 0.39 * min(1.0, (1 - f.adf_pvalue / _ADF_ALPHA))
        return (
            "stationary",
            confidence,
            [f"ADF p={f.adf_pvalue:.3f} < {_ADF_ALPHA}", f"趋势弱（{f.trend_strength:.2f}）→ 平稳型"],
        )

    confidence = 0.6 + 0.39 * min(1.0, f.trend_strength)
    return (
        "trending",
        confidence,
        [f"趋势强度 {f.trend_strength:.2f} → 趋势型"],
    )


def classify(series: SeriesBundle) -> ClassificationResult:
    features = extract_features(series.values, series.freq)
    metric_class, confidence, reasons = _classify_features(series.values, features)
    recommendation = recommend_for(metric_class, features)
    return ClassificationResult(
        series_id=series.series_id,
        metric_class=metric_class,
        confidence=float(confidence),
        reasons=reasons,
        features=features,
        recommendation=recommendation,
    )
