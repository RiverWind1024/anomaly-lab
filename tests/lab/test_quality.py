"""窗口体检：缺失、零值、间隔、重复时间戳、周期可识别性。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.lab.quality import period_capability, window_quality
from anomaly_lab.lab.sampling import Window


def _window(minutes: int = 100, expected: int = 20) -> Window:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return Window(
        index=0,
        start=start,
        end=start + timedelta(minutes=minutes),
        expected_points=expected,
    )


def _series(values: list[float], minutes: list[int] | None = None) -> SeriesBundle:
    n = len(values)
    offsets = minutes if minutes is not None else list(range(n))
    timestamps = np.array(
        [
            np.datetime64("2026-01-01T00:00:00", "ns")
            + np.timedelta64(offset, "m").astype("timedelta64[ns]")
            for offset in offsets
        ],
        dtype="datetime64[ns]",
    )
    return SeriesBundle(
        series_id="demo",
        values=np.asarray(values, dtype=float),
        timestamps=timestamps,
        freq="5min",
    )


def test_quality_reports_missing_and_zero():
    # 20 个期望点，实际 16 个，其中 4 个零值
    values = [0.0, 0.0, 0.0, 0.0] + [1.0] * 12
    series = _series(values, minutes=list(range(16)))
    quality = window_quality(series, _window(), freq="5min")

    assert quality.n == 16
    assert quality.expected == 20
    assert quality.n_missing == 4
    assert quality.missing_ratio == pytest.approx(0.2)
    assert quality.zero_ratio == pytest.approx(0.25)
    assert quality.sufficient is True
    assert quality.insufficient_reason is None


def test_quality_detects_duplicate_timestamps():
    series = _series([1.0, 2.0, 3.0, 4.0], minutes=[0, 5, 10, 10])
    quality = window_quality(series, _window(), freq="5min")

    assert quality.duplicate_timestamps == 1
    assert quality.on_grid_ratio == pytest.approx(2 / 3)
    assert quality.median_interval_s == pytest.approx(5 * 60)


def test_quality_insufficient_when_below_min_valid_ratio():
    # 20 个期望点，只有 12 个 → 60% < 80%
    series = _series([1.0] * 12, minutes=list(range(12)))
    quality = window_quality(series, _window(), freq="5min")

    assert quality.sufficient is False
    assert "60%" in (quality.insufficient_reason or "")


def test_quality_empty_window():
    series = _series([])
    quality = window_quality(series, _window(), freq="5min")

    assert quality.n == 0
    assert quality.missing_ratio == 1.0
    assert quality.min is None
    assert quality.max is None
    assert quality.mean is None
    assert quality.std is None
    assert quality.sufficient is False
    assert "没有数据" in (quality.insufficient_reason or "")


def test_period_capability_5min():
    # 500 点 @5min ≈ 1.7 天：日周期需要 3 × 288 = 864 点
    cap = period_capability(500, "5min")
    assert cap.daily_points == 288
    assert cap.daily_ok is False
    assert cap.weekly_ok is False
    assert cap.max_period_points == 166

    assert period_capability(900, "5min").daily_ok is True
    assert period_capability(900, "5min").weekly_ok is False
    assert period_capability(6048, "5min").weekly_ok is True


def test_period_capability_hourly():
    cap = period_capability(100, "1h")
    assert cap.daily_points == 24
    assert cap.daily_ok is True  # 100 // 24 = 4 >= 3
    assert cap.weekly_points == 168
    assert cap.weekly_ok is False
