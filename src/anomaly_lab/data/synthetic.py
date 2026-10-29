"""合成时序生成器：6 种基础形态 × 6 类异常注入，seed 完全可复现。"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from anomaly_lab.contracts import SeriesBundle

METRIC_CLASSES = [
    "stationary",
    "periodic",
    "trending",
    "step",
    "high_zero_ratio",
    "sparse_event",
]

ANOMALY_TYPES = [
    "spike",
    "contextual",
    "drift",
    "freq_shift",
    "variance_shift",
    "flatline",
]

_EPS = 1e-9


def _freq_delta(freq: str) -> np.timedelta64:
    digits = "".join(ch for ch in freq if ch.isdigit())
    unit = "".join(ch for ch in freq if ch.isalpha()).lower()
    n = int(digits) if digits else 1
    mapping = {"min": "m", "m": "m", "h": "h", "s": "s", "d": "D"}
    if unit not in mapping:
        raise ValueError(f"不支持的频率: {freq}")
    return np.timedelta64(n, mapping[unit])


def _timestamps(n: int, freq: str) -> np.ndarray:
    delta = _freq_delta(freq)
    return (np.arange(n) * delta).astype("datetime64[ns]")


def _scale(values: np.ndarray) -> float:
    """鲁棒的局部尺度，避免异常点把尺度拉高。"""
    med = np.median(values)
    mad = np.median(np.abs(values - med)) * 1.4826
    if mad > _EPS:
        return float(mad)
    std = float(np.std(values))
    return std if std > _EPS else 1.0


def _base_stationary(rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    mu = float(rng.uniform(-5, 5))
    sigma = float(rng.uniform(0.5, 2.0))
    phi = float(rng.uniform(0.0, 0.3))
    eps = rng.normal(0.0, sigma, n)
    noise = np.empty(n)
    noise[0] = eps[0]
    for i in range(1, n):
        noise[i] = phi * noise[i - 1] + eps[i]
    values = mu + noise
    return values, {"mu": mu, "sigma": sigma, "phi": phi}


def _base_periodic(rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    candidates = [p for p in (24, 48, 168) if n // p >= 3]
    period = int(rng.choice(candidates or [24]))
    amp = float(rng.uniform(1.0, 5.0))
    phase = float(rng.uniform(0.0, 2 * np.pi))
    slope = float(rng.uniform(-0.005, 0.005))
    offset = float(rng.uniform(-2.0, 2.0))
    sigma = float(rng.uniform(0.2, 0.6))
    t = np.arange(n)
    values = offset + slope * t + amp * np.sin(2 * np.pi * t / period + phase)
    values = values + rng.normal(0.0, sigma, n)
    return values, {
        "period": period,
        "amplitude": amp,
        "phase": phase,
        "slope": slope,
        "offset": offset,
        "sigma": sigma,
    }


def _base_trending(rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    slope = float(rng.uniform(0.02, 0.08))
    intercept = float(rng.uniform(-5.0, 5.0))
    sigma = float(rng.uniform(0.5, 1.5))
    t = np.arange(n)
    values = intercept + slope * t + rng.normal(0.0, sigma, n)
    return values, {"slope": slope, "intercept": intercept, "sigma": sigma}


def _base_step(rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    mu1 = float(rng.uniform(-5.0, 5.0))
    delta = float(rng.uniform(3.0, 7.0)) * float(rng.choice([-1.0, 1.0]))
    changepoint = int(rng.uniform(0.3, 0.7) * n)
    sigma = float(rng.uniform(0.5, 1.2))
    t = np.arange(n)
    values = np.where(t < changepoint, mu1, mu1 + delta)
    values = values + rng.normal(0.0, sigma, n)
    return values, {
        "mu1": mu1,
        "mu2": mu1 + delta,
        "changepoint": changepoint,
        "sigma": sigma,
    }


def _base_high_zero_ratio(rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    zero_ratio = float(rng.uniform(0.7, 0.9))
    mask = rng.random(n) < zero_ratio
    mu = float(rng.uniform(2.0, 6.0))
    sigma = float(rng.uniform(0.5, 1.5))
    nonzero = rng.normal(mu, sigma, n)
    values = np.where(mask, 0.0, nonzero)
    return values, {
        "zero_ratio": zero_ratio,
        "mu": mu,
        "sigma": sigma,
    }


def _base_sparse_event(rng: np.random.Generator, n: int) -> tuple[np.ndarray, dict]:
    values = np.zeros(n)
    n_events = max(1, min(8, round(n * 0.005)))
    margin = max(2, n // 50)
    positions: list[int] = []
    attempts = 0
    while len(positions) < n_events and attempts < 200:
        attempts += 1
        pos = int(rng.integers(margin, n - margin))
        if all(abs(pos - p) >= 3 for p in positions):
            positions.append(pos)
    mu = float(rng.uniform(3.0, 8.0))
    sigma = float(rng.uniform(0.3, 1.0))
    for pos in positions:
        values[pos] = float(rng.normal(mu, sigma))
    return values, {
        "n_events": len(positions),
        "event_positions": positions,
        "mu": mu,
        "sigma": sigma,
    }


_BASE_BUILDERS = {
    "stationary": _base_stationary,
    "periodic": _base_periodic,
    "trending": _base_trending,
    "step": _base_step,
    "high_zero_ratio": _base_high_zero_ratio,
    "sparse_event": _base_sparse_event,
}


def _inject_spike(
    values: np.ndarray, rng: np.random.Generator, start: int, end: int
) -> tuple[np.ndarray, int, int]:
    k = float(rng.uniform(4.0, 8.0)) * float(rng.choice([-1.0, 1.0]))
    values[start : end + 1] += k * _scale(values)
    return values, start, end


def _inject_contextual(
    values: np.ndarray, rng: np.random.Generator, start: int, end: int
) -> tuple[np.ndarray, int, int]:
    delta = float(rng.uniform(2.0, 4.0)) * float(rng.choice([-1.0, 1.0]))
    values[start : end + 1] += delta * _scale(values)
    return values, start, end


def _inject_drift(
    values: np.ndarray, rng: np.random.Generator, start: int, end: int
) -> tuple[np.ndarray, int, int]:
    length = end - start + 1
    magnitude = float(rng.uniform(3.0, 8.0)) * float(rng.choice([-1.0, 1.0]))
    values[start : end + 1] += np.linspace(0.0, magnitude * _scale(values), length)
    return values, start, end


def _inject_freq_shift(
    values: np.ndarray,
    rng: np.random.Generator,
    start: int,
    end: int,
    period: int | None = None,
) -> tuple[np.ndarray, int, int]:
    base_period = int(period) if period else 24
    shifted_period = max(4, base_period // 2)
    length = end - start + 1
    t = np.arange(length)
    values[start : end + 1] += 0.8 * _scale(values) * np.sin(
        2 * np.pi * t / shifted_period
    )
    return values, start, end


def _inject_variance_shift(
    values: np.ndarray, rng: np.random.Generator, start: int, end: int
) -> tuple[np.ndarray, int, int]:
    factor = float(rng.uniform(3.0, 6.0))
    seg = values[start : end + 1]
    center = float(np.median(seg))
    values[start : end + 1] = center + (seg - center) * factor
    return values, start, end


def _inject_flatline(
    values: np.ndarray, rng: np.random.Generator, start: int, end: int
) -> tuple[np.ndarray, int, int]:
    value = float(np.median(values[start : end + 1]))
    values[start : end + 1] = value
    return values, start, end


_INJECTORS = {
    "spike": _inject_spike,
    "contextual": _inject_contextual,
    "drift": _inject_drift,
    "freq_shift": _inject_freq_shift,
    "variance_shift": _inject_variance_shift,
    "flatline": _inject_flatline,
}

_LONG_ANOMALIES = {"drift", "freq_shift", "variance_shift", "flatline"}


def _anomaly_length(anomaly_type: str, rng: np.random.Generator) -> int:
    if anomaly_type in _LONG_ANOMALIES:
        return int(rng.integers(10, 21))
    if anomaly_type == "contextual":
        return int(rng.integers(2, 6))
    return int(rng.integers(1, 4))


def _choose_interval(
    anomaly_type: str,
    rng: np.random.Generator,
    n: int,
    occupied: np.ndarray,
) -> tuple[int, int]:
    length = _anomaly_length(anomaly_type, rng)
    margin = max(3, n // 50)
    for _ in range(200):
        start = int(rng.integers(margin, max(margin + 1, n - margin - length)))
        end = start + length - 1
        if end >= n:
            continue
        lo = max(0, start - 2)
        hi = min(n, end + 3)
        if not occupied[lo:hi].any():
            return start, end
    # 找不到空位时退化为最后一段
    start = max(margin, n - margin - length)
    return start, min(n - 1, start + length - 1)


def generate_series(
    metric_class: str,
    n: int = 500,
    seed: int = 42,
    freq: str = "5min",
    n_anomalies: int = 3,
    anomaly_types: Iterable[str] | None = None,
) -> SeriesBundle:
    """生成一条带真值标注的合成序列。异常区间写入 labels（1=异常）。"""
    if metric_class not in _BASE_BUILDERS:
        raise ValueError(f"未知形态: {metric_class}")
    rng = np.random.default_rng(seed)
    values, base_params = _BASE_BUILDERS[metric_class](rng, n)
    if anomaly_types is not None:
        types = [str(t) for t in anomaly_types]
        if not types:
            raise ValueError("anomaly_types 不能为空")
        chosen = [types[i % len(types)] for i in range(n_anomalies)]
    else:
        chosen = [str(t) for t in rng.choice(ANOMALY_TYPES, size=n_anomalies)]

    labels = np.zeros(n, dtype=np.int8)
    occupied = np.zeros(n, dtype=bool)
    intervals: list[dict] = []
    for anomaly_type in chosen:
        if anomaly_type not in _INJECTORS:
            raise ValueError(f"未知异常类型: {anomaly_type}")
        start, end = _choose_interval(anomaly_type, rng, n, occupied)
        injector = _INJECTORS[anomaly_type]
        if anomaly_type == "freq_shift":
            values, start, end = injector(
                values, rng, start, end, period=base_params.get("period")
            )
        else:
            values, start, end = injector(values, rng, start, end)
        labels[start : end + 1] = 1
        occupied[start : end + 1] = True
        intervals.append({"type": anomaly_type, "start": int(start), "end": int(end)})

    series_id = f"{metric_class}-{seed}-{n}"
    meta = {
        "metric_class": metric_class,
        "seed": int(seed),
        "freq": freq,
        "base_params": base_params,
        "anomaly_types": intervals,
    }
    return SeriesBundle(
        series_id=series_id,
        values=values,
        timestamps=_timestamps(n, freq),
        freq=freq,
        labels=labels,
        label_source="synthetic",
        meta=meta,
    )
