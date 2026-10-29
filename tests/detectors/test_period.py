"""周期估计：FFT 粗定位 + ACF 验证。"""

import numpy as np
import pytest

from anomaly_lab.detectors.period import (
    MIN_CONFIDENCE,
    detect_period,
    estimate_period,
)


def _sine(period: int, n: int, noise: float = 0.3, seed: int = 0) -> np.ndarray:
    t = np.arange(n)
    rng = np.random.default_rng(seed)
    return 5 + 2 * np.sin(2 * np.pi * t / period) + rng.normal(0, noise, n)


def test_exact_period_is_recovered():
    estimate = estimate_period(_sine(48, 300), "5min")
    assert estimate.found
    assert estimate.period_points == 48
    assert estimate.confidence > 0.3


def test_period_is_not_off_by_one():
    """相位分组时 ±1 的误差会让基线整体错位，所以必须精确。"""
    for period in (24, 48, 72):
        estimate = estimate_period(_sine(period, 400), "5min")
        assert estimate.period_points == period, f"周期 {period} 估成了 {estimate.period_points}"


def test_long_period_beyond_old_acf_limit_is_found():
    """旧的 ACF 实现 lag 上限写死 200，168 点的周周期根本看不到。"""
    estimate = estimate_period(_sine(168, 1000), "5min")
    assert estimate.found
    assert abs(estimate.period_points - 168) <= 1


def test_same_time_period_found_across_sampling_rates():
    """同一个「一天」，在 5min / 15min / 1h 粒度下都要认出来。"""
    for freq, points_per_day in (("5min", 288), ("15min", 96), ("1h", 24)):
        values = _sine(points_per_day, points_per_day * 3)
        estimate = estimate_period(values, freq)
        assert estimate.found, f"{freq} 粒度没检出"
        assert abs(estimate.period_seconds - 86400) < 3600, (
            f"{freq} 粒度估成 {estimate.period_seconds} 秒，应接近 86400"
        )


def test_pure_noise_is_not_reported_as_usable():
    """纯噪声里也能挑出一个「像周期」的峰，但置信度必须低到不能被采用。"""
    for seed in (1, 2, 3):
        estimate = estimate_period(np.random.default_rng(seed).normal(size=300), "5min")
        assert not estimate.usable, (
            f"seed={seed} 误判为可用周期 {estimate.period_points}（置信度 {estimate.confidence:.2f}）"
        )


def test_trend_is_not_reported_as_usable():
    t = np.arange(300)
    values = 0.05 * t + np.random.default_rng(7).normal(0, 1, 300)
    estimate = estimate_period(values, "5min")
    assert not estimate.usable


def test_single_cycle_gets_low_confidence():
    """只够一个周期时不该给出可信的结论。"""
    values = _sine(288, 288)
    estimate = estimate_period(values, "5min")
    assert estimate.confidence < MIN_CONFIDENCE


def test_detect_period_falls_back_when_unreliable():
    """拿不准或装不下两个周期时回退到默认值。"""

    class _Fake:
        values = np.random.default_rng(9).normal(size=300)
        freq = "5min"

    assert detect_period(_Fake(), fallback=24) == 24

    # 周期比序列一半还长 → 相位分组会退化成每相位 1 个点 → 回退
    class _LongPeriod:
        values = _sine(200, 300)
        freq = "5min"

    assert detect_period(_LongPeriod(), fallback=24) == 24


def test_detect_period_uses_estimate_when_confident():
    class _Periodic:
        values = _sine(48, 400)
        freq = "5min"

    assert detect_period(_Periodic(), fallback=24) == 48


def test_confidence_is_between_zero_and_one():
    estimate = estimate_period(_sine(48, 400), "5min")
    assert 0.0 <= estimate.confidence <= 1.0


def test_autocorrelate_matches_direct_correlation():
    from anomaly_lab.detectors.period import autocorrelate

    values = _sine(24, 200)
    fast = autocorrelate(values - values.mean(), 50)
    centered = values - values.mean()
    slow = np.correlate(centered, centered, "full")[len(values) - 1 :][: 51] / np.dot(
        centered, centered
    )
    assert np.allclose(fast, slow, atol=1e-8)


@pytest.mark.parametrize("freq", ["5min", "1h", "1d"])
def test_invalid_frequency_does_not_crash(freq):
    estimate = estimate_period(_sine(24, 200), freq)
    assert estimate.period_points is None or estimate.period_points >= 2
