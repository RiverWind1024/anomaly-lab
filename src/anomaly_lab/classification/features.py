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
    n_nonzero_runs: int


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
    running_min = float(norm[1])
    for lag in range(2, len(norm) - 1):
        is_peak = (
            norm[lag] > 0.2
            and norm[lag] > norm[lag - 1]
            and norm[lag] >= norm[lag + 1]
        )
        # 真周期在峰前应有明显低谷；单调衰减的 ACF（趋势/阶梯）不算周期
        if is_peak and norm[lag] - running_min > 0.15:
            # 真周期应在 2 倍周期处仍保留相关性；无法验证第二个峰的孤立峰不算
            if 2 * lag >= len(norm) or norm[2 * lag] <= 0.2:
                running_min = min(running_min, float(norm[lag]))
                continue
            return int(lag)
        running_min = min(running_min, float(norm[lag]))
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
    """单变点强度：变点两侧大窗口中位数的差异 / 全局稳健尺度。

    用相邻大窗口（而非全体两段）避免短时异常段（drift/flatline）被误判为阶梯；
    短异常段在 20% 长度的窗口中会被稀释。
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 4 * min_seg:
        return 0.0
    med = float(np.median(values))
    scale = float(np.median(np.abs(values - med))) * 1.4826
    if scale < _EPS:
        scale = float(np.std(values))
    if scale < _EPS:
        return 0.0
    window = max(min_seg, min(n // 5, 100))
    best = 0.0
    for k in range(window, n - window + 1):
        left = float(np.median(values[k - window : k]))
        right = float(np.median(values[k : k + window]))
        best = max(best, abs(left - right))
    return float(np.tanh(best / scale))


# 兼容计划里的两种命名
changepoint_score = change_point_score


def trend_strength(values: np.ndarray) -> float:
    """趋势强度：|Spearman 秩相关|，对异常段/离群点比 OLS 斜率更稳健。"""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 3 or np.std(values) < _EPS:
        return 0.0
    try:
        from scipy.stats import spearmanr

        rho = float(spearmanr(np.arange(n), values).statistic)
        return abs(rho) if np.isfinite(rho) else 0.0
    except Exception:
        return 0.0


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
    if n >= 2:
        t = np.arange(n, dtype=float)
        detrended = values - np.polyval(np.polyfit(t, values, 1), t)
    else:
        detrended = values
    acf_vals = acf(detrended)
    period = dominant_period(acf_vals)
    nonzero_mask = values != 0
    n_nonzero_runs = (
        int(nonzero_mask[0]) + int(np.sum(nonzero_mask[1:] & ~nonzero_mask[:-1])) if n else 0
    )
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
        n_nonzero=int(np.sum(nonzero_mask)),
        n_nonzero_runs=n_nonzero_runs,
    )
