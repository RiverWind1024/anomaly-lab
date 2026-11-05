"""跨时间窗采样：窗口规划与分层选择。"""

from __future__ import annotations

import itertools
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.lab.sampling import Window, plan_windows, stratify_windows


def _range(days: int = 30) -> tuple[datetime, datetime]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return start, start + timedelta(days=days)


def _series(values: np.ndarray, freq: str = "5min") -> SeriesBundle:
    n = len(values)
    timestamps = np.datetime64("2026-01-01T00:00:00", "ns") + np.arange(n) * np.timedelta64(
        5, "m"
    ).astype("timedelta64[ns]")
    return SeriesBundle(
        series_id="demo",
        values=np.asarray(values, dtype=float),
        timestamps=timestamps,
        freq=freq,
    )


def test_even_windows_tile_the_range_without_overlap():
    start, end = _range(30)
    windows = plan_windows(start, end, "5min", window_points=500, stride_points=500)

    # 30 天 / (500 × 5min ≈ 41.7h) ≈ 17 个不重叠窗口
    assert len(windows) == 17
    assert windows[0].start == start
    assert windows[0].end == start + timedelta(minutes=2500)
    assert windows[-1].end <= end
    for left, right in itertools.pairwise(windows):
        assert left.end == right.start
    assert [w.index for w in windows] == list(range(17))


def test_recent_mode_takes_the_tail():
    start, end = _range(30)
    windows = plan_windows(
        start, end, "5min", window_points=500, stride_points=500, max_windows=5, mode="recent"
    )

    assert len(windows) == 5
    # 最近 5 个窗口 = 原始索引 12..16
    assert [w.index for w in windows] == [12, 13, 14, 15, 16]
    assert windows[-1].end <= end


def test_even_mode_spreads_selected_windows_across_the_range():
    start, end = _range(30)
    windows = plan_windows(
        start, end, "5min", window_points=500, stride_points=500, max_windows=5, mode="even"
    )

    assert [w.index for w in windows] == [0, 4, 8, 12, 16]


def test_max_points_caps_window_count():
    start, end = _range(30)
    windows = plan_windows(
        start, end, "5min", window_points=500, stride_points=500, max_points=1000
    )

    # 预算 1000 点 / 每窗 500 点 = 最多 2 窗
    assert len(windows) == 2
    assert [w.index for w in windows] == [0, 16]


def test_overlapping_stride_increases_window_count():
    # 2 天 = 2880min；窗口 100 点 @5min = 500min
    # 不重叠步长 500min → 5 窗；50% 重叠步长 250min → 10 窗
    start, end = _range(2)
    non_overlap = plan_windows(
        start, end, "5min", window_points=100, stride_points=100, max_points=10_000
    )
    overlap = plan_windows(
        start, end, "5min", window_points=100, stride_points=50, max_points=10_000
    )

    assert len(non_overlap) == 5
    assert len(overlap) == 10
    assert overlap[1].start - overlap[0].start == timedelta(minutes=250)


def test_range_shorter_than_one_window_returns_empty():
    start, end = _range(1)
    windows = plan_windows(start, end, "5min", window_points=500)
    assert windows == []


def test_rejects_non_positive_window_points():
    start, end = _range(30)
    with pytest.raises(ValueError, match="window_points"):
        plan_windows(start, end, "5min", window_points=0)


def test_stratified_selection_includes_suspicious_window():
    # 10 个窗口，第 5 个窗口里有一个明显尖峰
    values = np.zeros(10 * 50)
    values[5 * 50 + 25] = 100.0
    series = _series(values)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candidates = plan_windows(
        start, start + timedelta(minutes=5 * 500), "5min", window_points=50, stride_points=50
    )

    selected = stratify_windows(series, candidates, max_windows=4)

    assert len(selected) == 4
    assert 5 in [w.index for w in selected]
    # 结果按时间顺序排列
    assert [w.index for w in selected] == sorted(w.index for w in selected)


def test_stratified_returns_all_when_fewer_than_budget():
    series = _series(np.zeros(200))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candidates = plan_windows(
        start, start + timedelta(minutes=5 * 200), "5min", window_points=50, stride_points=50
    )
    assert len(stratify_windows(series, candidates, max_windows=10)) == 4


def test_window_is_immutable():
    window = Window(index=0, start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 2, tzinfo=UTC), expected_points=10)
    with pytest.raises(FrozenInstanceError):
        window.index = 1  # type: ignore[misc]
