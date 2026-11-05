"""跨时间窗采样：把一段较长的数据切成多个「与生产同构」的窗口。

⚠️ 窗口大小、频率、缺失策略必须与未来检测任务一致，
   否则预检结论不可迁移。本模块只负责**切窗**，不负责取数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.timeutil import freq_delta

#: 支持的计划模式。`stratified` 需要数据，由 `stratify_windows` 单独处理。
PLAN_MODES = ("recent", "even")


@dataclass(frozen=True)
class Window:
    """一个采样窗口。

    `index` 是它在整段范围里的原始序号（不是筛选后的序号）——
    前端要靠它把窗口放回时间轴。
    """

    index: int
    start: datetime
    end: datetime
    expected_points: int


def _evenly_spaced(items: list[Window], count: int) -> list[Window]:
    """从有序窗口里均匀挑 `count` 个（含首尾）。"""
    if count >= len(items):
        return list(items)
    picks = np.linspace(0, len(items) - 1, count)
    chosen: list[Window] = []
    seen: set[int] = set()
    for raw in picks:
        idx = round(float(raw))
        if idx not in seen:
            seen.add(idx)
            chosen.append(items[idx])
    # round 撞车时从尾部补齐，保证数量够
    for item in reversed(items):
        if len(chosen) >= count:
            break
        if item.index not in seen:
            seen.add(item.index)
            chosen.append(item)
    return sorted(chosen, key=lambda w: w.index)


def plan_windows(
    start: datetime,
    end: datetime,
    freq: str,
    *,
    window_points: int = 500,
    stride_points: int | None = None,
    max_points: int = 10_000,
    max_windows: int = 100,
    mode: str = "even",
) -> list[Window]:
    """规划采样窗口。

    - `recent`：取最近的 N 个窗口
    - `even`：在范围内均匀取 N 个窗口

    窗口数受三个上限约束：`max_points / window_points`、`max_windows`、范围内可用窗口数。
    """
    if window_points <= 0:
        raise ValueError("window_points 必须为正整数")
    if max_points <= 0:
        raise ValueError("max_points 必须为正整数")
    if max_windows <= 0:
        raise ValueError("max_windows 必须为正整数")
    if mode not in PLAN_MODES:
        raise ValueError(f"不支持的采样模式: {mode!r}（可选：{PLAN_MODES}）")

    stride = window_points if stride_points is None else stride_points
    if stride <= 0:
        raise ValueError("stride_points 必须为正整数")

    delta = freq_delta(freq)
    window_span = delta * window_points
    stride_span = delta * stride
    total = end - start
    if total < window_span:
        return []

    available = int((total - window_span) / stride_span) + 1
    budget_windows = max_points // window_points
    limit = min(max_windows, budget_windows, available)
    if limit <= 0:
        return []

    if mode == "recent":
        indices = list(range(available - limit, available))
        chosen = [
            Window(
                index=i,
                start=start + stride_span * i,
                end=start + stride_span * i + window_span,
                expected_points=window_points,
            )
            for i in indices
        ]
        return chosen

    all_windows = [
        Window(
            index=i,
            start=start + stride_span * i,
            end=start + stride_span * i + window_span,
            expected_points=window_points,
        )
        for i in range(available)
    ]
    return _evenly_spaced(all_windows, limit)


def _window_bounds(series: SeriesBundle, window: Window) -> tuple[int, int]:
    """窗口在序列里的下标区间（左闭右开）。"""
    stamps = series.timestamps.astype("datetime64[ns]").astype(np.int64)
    start = np.datetime64(window.start.replace(tzinfo=None), "ns").astype(np.int64)
    end = np.datetime64(window.end.replace(tzinfo=None), "ns").astype(np.int64)
    lo = int(np.searchsorted(stamps, start, side="left"))
    hi = int(np.searchsorted(stamps, end, side="left"))
    return lo, hi


def window_slice(series: SeriesBundle, window: Window) -> tuple[np.ndarray, np.ndarray]:
    """取窗口内的值和时间戳（左闭右开）。"""
    lo, hi = _window_bounds(series, window)
    return series.values[lo:hi], series.timestamps[lo:hi]


def window_labels(series: SeriesBundle, window: Window) -> np.ndarray:
    """窗口内的点级真值（左闭右开）。

    ⚠️ **无真值时返回全 0** —— 而不是 None。
       评估层要拼真值数组，长度必须与值一致；「没有真值」这件事
       由 `SeriesBundle.has_labels` 表达，不靠返回值区分。
    """
    lo, hi = _window_bounds(series, window)
    if series.labels is None:
        return np.zeros(hi - lo, dtype=np.int8)
    return np.asarray(series.labels[lo:hi], dtype=np.int8)


def window_values(series: SeriesBundle, window: Window) -> np.ndarray:
    """取窗口内的值（左闭右开）。"""
    return window_slice(series, window)[0]


def _suspicion(values: np.ndarray, expected_points: int) -> float:
    """窗口的「可疑度」：稳健 z 的峰值 + 缺口惩罚。

    只用廉价统计 —— 分层采样时会对所有候选窗口调用，不能跑完整检测。
    """
    if len(values) == 0:
        return 0.0
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med))) * 1.4826
    if mad <= 1e-9:
        mad = float(np.std(values))
    if mad <= 1e-9:
        mad = 1.0
    peak = float(np.max(np.abs(values - med)) / mad)
    gap = max(0.0, 1.0 - len(values) / expected_points)
    return peak + 2.0 * gap


def stratify_windows(
    series: SeriesBundle,
    candidates: list[Window],
    *,
    max_windows: int = 100,
) -> list[Window]:
    """分层选择：一半取最可疑的窗口，一半在剩余里均匀铺开。

    目的：既覆盖「正常但典型」的窗口，也不漏掉「看起来有问题」的窗口。
    """
    if max_windows <= 0:
        raise ValueError("max_windows 必须为正整数")
    if len(candidates) <= max_windows:
        return list(candidates)

    scored = [
        (_suspicion(window_values(series, w), w.expected_points), w) for w in candidates
    ]
    top_n = max(1, max_windows // 2)
    top = [
        w
        for _, w in sorted(scored, key=lambda item: (-item[0], item[1].index))[:top_n]
    ]
    seen = {w.index for w in top}
    rest = [w for w in candidates if w.index not in seen]

    fill = _evenly_spaced(rest, max_windows - len(top))
    chosen = sorted([*top, *fill], key=lambda w: w.index)
    return chosen
