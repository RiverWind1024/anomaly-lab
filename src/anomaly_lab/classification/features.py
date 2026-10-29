"""形态特征提取：只做描述，不做异常检测。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-9


@dataclass(frozen=True, eq=False)
class FeatureVector:
    adf_pvalue: float
    dominant_period: int | None
    zero_ratio: float
    sparsity: float
    changepoint_score: float
    trend_strength: float
    noise_ratio: float
    mean: float
    std: float
    acf_peak_lag1: float
    n_samples: int
    n_nonzero: int


def adf_statistic(values: np.ndarray) -> tuple[float, float]:
    """ADF 检验统计量与 p 值；长度不足或常数序列返回 (nan, nan)。"""
    values = np.asarray(values, dtype=float)
    if len(values) < 20 or np.std(values) < _EPS:
        return float("nan"), float("nan")
    try:
        from statsmodels.tsa.stattools import adfuller

        stat, pvalue, *_ = adfuller(values, autolag="AIC", result_object=False)
        return float(stat), float(pvalue)
    except Exception:
        return float("nan"), float("nan")


def acf(values: np.ndarray, nlags: int | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 3:
        return np.array([1.0])
    if nlags is None:
        nlags = min(n // 4, 200)
    nlags = max(1, min(nlags, n - 1))
    centered = values - values.mean()
    var = np.dot(centered, centered)
    if var < _EPS:
        result = np.zeros(nlags + 1)
        result[0] = 1.0
        return result
    full = np.correlate(centered, centered, "full")[n - 1 :]
    return full[: nlags + 1] / var


def dominant_period(acf_vals: np.ndarray) -> int | None:
    """ACF 在 lag>1 的第一个显著局部峰（归一化后 > 0.2）。"""
    acf_vals = np.asarray(acf_vals, dtype=float)
    if len(acf_vals) < 4 or abs(acf_vals[0]) < _EPS:
        return None
    norm = acf_vals / acf_vals[0]
    for lag in range(2, len(norm) - 1):
        if norm[lag] > 0.2 and norm[lag] > norm[lag - 1] and norm[lag] >= norm[lag + 1]:
            return int(lag)
    return None


def zero_ratio(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return 0.0
    return float(np.mean(values == 0))


def sparsity(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return 0.0
    return float(np.mean(values != 0))


def change_point_score(values: np.ndarray, min_seg: int = 20) -> float:
    """找使组间均值差最大的切点，用 tanh 归一到 [0, 1]。"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 2 * min_seg:
        return 0.0
    std = float(np.std(values))
    if std < _EPS:
        return 0.0
    prefix = np.concatenate(([0.0], np.cumsum(values)))
    k = np.arange(min_seg, n - min_seg + 1)
    left_mean = prefix[k] / k
    right_mean = (prefix[n] - prefix[k]) / (n - k)
    max_diff = float(np.max(np.abs(left_mean - right_mean)))
    return float(np.tanh(max_diff / std))


# 兼容计划里的两种命名
changepoint_score = change_point_score


def trend_strength(values: np.ndarray) -> float:
    """线性回归斜率显著性的归一化表示：tanh(|t| / 300)。"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 3:
        return 0.0
    t = np.arange(n, dtype=float)
    t_mean = t.mean()
    x_mean = values.mean()
    sxx = float(np.sum((t - t_mean) ** 2))
    if sxx < _EPS:
        return 0.0
    slope = float(np.sum((t - t_mean) * (values - x_mean)) / sxx)
    resid = values - (x_mean + slope * (t - t_mean))
    sigma2 = float(np.sum(resid**2) / (n - 2))
    se = np.sqrt(sigma2 / sxx)
    if se < _EPS:
        return 0.0 if abs(slope) < _EPS else 1.0
    tstat = abs(slope / se)
    return float(np.tanh(tstat / 300.0))


def noise_ratio(values: np.ndarray, period: int | None = None) -> float:
    """去趋势（或去季节）后残差能量 / 总能量。"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 3:
        return 0.0
    t = np.arange(n, dtype=float)
    trend = np.polyval(np.polyfit(t, values, 1), t)
    detrended = values - trend
    total = float(np.sum(detrended**2))
    if total < _EPS:
        return 0.0
    if period and period >= 2:
        phase = np.arange(n) % period
        seasonal = np.zeros(n)
        for p in range(period):
            mask = phase == p
            if mask.any():
                seasonal[mask] = detrended[mask].mean()
        residual = detrended - seasonal
    else:
        residual = detrended
    return float(np.clip(np.sum(residual**2) / total, 0.0, 1.0))


def extract_features(values: np.ndarray, freq: str | None = None) -> FeatureVector:
    values = np.asarray(values, dtype=float)
    n = len(values)
    _, adf_p = adf_statistic(values)
    acf_vals = acf(values)
    period = dominant_period(acf_vals)
    return FeatureVector(
        adf_pvalue=adf_p,
        dominant_period=period,
        zero_ratio=zero_ratio(values),
        sparsity=sparsity(values),
        changepoint_score=change_point_score(values),
        trend_strength=trend_strength(values),
        noise_ratio=noise_ratio(values, period),
        mean=float(np.mean(values)) if n else 0.0,
        std=float(np.std(values)) if n else 0.0,
        acf_peak_lag1=float(acf_vals[1]) if len(acf_vals) > 1 else 0.0,
        n_samples=n,
        n_nonzero=int(np.sum(values != 0)),
    )
