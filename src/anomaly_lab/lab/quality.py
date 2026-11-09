"""窗口体检：数据质量与「这个窗口能识别什么周期」。

⚠️ 体检只**报告**，不修复。缺失值怎么处理由指标的 `missing_policy` 决定，
   这里不做二次清洗 —— 否则「体检看到的」与「检测实际拿到的」会不一致。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.lab.sampling import Window, window_slice
from anomaly_lab.platform.sources.base import MIN_VALID_POINTS
from anomaly_lab.platform.timeutil import freq_delta


@dataclass(frozen=True)
class WindowQuality:
    """一个窗口的数据质量。"""

    index: int
    start: datetime
    end: datetime
    n: int
    expected: int
    n_missing: int
    missing_ratio: float
    zero_ratio: float
    duplicate_timestamps: int
    on_grid_ratio: float
    median_interval_s: float | None
    min: float | None
    max: float | None
    mean: float | None
    std: float | None
    sufficient: bool
    insufficient_reason: str | None


@dataclass(frozen=True)
class PeriodCapability:
    """当前窗口长度能识别到的最长周期。

    约定与 `detect_period` 一致：至少要有 3 个完整周期。
    """

    daily_points: int
    daily_ok: bool
    weekly_points: int
    weekly_ok: bool
    max_period_points: int


def window_quality(
    series: SeriesBundle,
    window: Window,
    *,
    freq: str,
    min_valid_ratio: float = 0.8,
) -> WindowQuality:
    """计算窗口质量。

    `n_missing` 是「按期望点数算出来的缺口」，不是源库的 NULL 数
    （NULL 在 `series_from_frame` 里已经按 `missing_policy` 处理过）。
    """
    values, timestamps = window_slice(series, window)
    n = len(values)
    expected = int(window.expected_points)
    n_missing = max(0, expected - n)
    missing_ratio = n_missing / expected if expected else 0.0

    vmin: float | None
    vmax: float | None
    mean: float | None
    std: float | None
    if n:
        zero_ratio = float(np.mean(values == 0.0))
        vmin = float(np.min(values))
        vmax = float(np.max(values))
        mean = float(np.mean(values))
        std = float(np.std(values))
    else:
        zero_ratio = 0.0
        vmin = vmax = mean = std = None

    diffs = np.diff(timestamps.astype("datetime64[s]").astype(np.int64))
    duplicate_timestamps = int((diffs == 0).sum())
    expected_seconds = float(freq_delta(freq).total_seconds())
    on_grid_ratio = float(np.mean(diffs == expected_seconds)) if len(diffs) else 0.0
    median_interval_s = float(np.median(diffs)) if len(diffs) else None

    reason: str | None = None
    if n == 0:
        reason = "窗口内没有数据"
    elif n < MIN_VALID_POINTS:
        reason = f"有效点仅 {n} 个，少于 {MIN_VALID_POINTS}"
    elif expected and n / expected < min_valid_ratio:
        reason = f"有效点占比 {n / expected:.0%}，低于 {min_valid_ratio:.0%}"

    return WindowQuality(
        index=window.index,
        start=window.start,
        end=window.end,
        n=n,
        expected=expected,
        n_missing=n_missing,
        missing_ratio=missing_ratio,
        zero_ratio=zero_ratio,
        duplicate_timestamps=duplicate_timestamps,
        on_grid_ratio=on_grid_ratio,
        median_interval_s=median_interval_s,
        min=vmin,
        max=vmax,
        mean=mean,
        std=std,
        sufficient=reason is None,
        insufficient_reason=reason,
    )


def period_capability(window_points: int, freq: str) -> PeriodCapability:
    """当前窗口能识别日周期 / 周周期吗？

    真实指标的周期是**时间**概念：5min 粒度的日周期是 288 点、周周期是 2016 点。
    500 点的窗口在 5min 粒度下只有 1.7 天，根本看不到日周期 ——
    这个检查就是为了避免算法给出一个「猜出来的周期」。
    """
    seconds = float(freq_delta(freq).total_seconds())
    daily = max(1, math.ceil(86400 / seconds))
    weekly = daily * 7
    return PeriodCapability(
        daily_points=daily,
        daily_ok=window_points // daily >= 3,
        weekly_points=weekly,
        weekly_ok=window_points // weekly >= 3,
        max_period_points=max(1, window_points // 3),
    )
