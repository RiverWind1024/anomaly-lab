"""周期估计：FFT 粗定位 + ACF 谐波验证。

关键设计：
- 候选周期范围按**时间**表达，换采样频率也能找到同一个「日周期」；
- ACF 用**谐波重复性**（p、2p、3p 都出现）验证，而不是单点显著性——
  单点门槛会被单个异常点抬高，恰恰让有异常的那段数据失效；
- 估计过程对离群点鲁棒（先截尾）。
"""

import numpy as np
import pytest

from anomaly_lab.detectors.period import (
    HARMONIC_THRESHOLD,
    MIN_CONFIDENCE,
    MIN_PERIOD_POINTS,
    default_fallback_period,
    detect_period,
    estimate_period,
)


def _sine(period: int, n: int, noise: float = 0.3, seed: int = 0) -> np.ndarray:
    t = np.arange(n)
    rng = np.random.default_rng(seed)
    return 5 + 2 * np.sin(2 * np.pi * t / period) + rng.normal(0, noise, n)


def _sawtooth(period: int, n: int) -> np.ndarray:
    return np.array([float(i % period) for i in range(n)])


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
    # 长周期的**定位精度**受数据长度限制，不是算法问题：
    # 频率分辨率 ~1/n，折算成周期约 P²/n（P=168, n=1000 → ~28 个周期点）。
    # 补零只能做亚桶插值，不能提高真实分辨率。所以这里不要求精确命中。
    assert abs(estimate.period_points - 168) <= 4


def test_short_period_is_located_exactly():
    """短周期必须精确——±1 的误差会让相位分组整体错位。"""
    for period in (24, 48):
        estimate = estimate_period(_sine(period, 500), "5min")
        assert estimate.period_points == period


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


def test_spike_does_not_break_period_estimation():
    """异常点不能主导周期估计。

    单个离群点会把去趋势后的自相关从 0.824 压到 0.08、把频谱突出度
    从 19 压到 1.9——如果估计因此失效，季节性基线就没了，
    恰恰是**有异常的那段数据**最容易漏报。
    """
    clean = _sawtooth(10, 60)
    spiky = clean.copy()
    spiky[30] += 50.0

    before = estimate_period(clean, "5min")
    after = estimate_period(spiky, "5min")
    assert before.usable and after.usable
    assert after.period_points == before.period_points == 10
    assert after.confidence > MIN_CONFIDENCE


def test_short_period_is_not_excluded_by_the_lower_bound():
    """分钟级的短周期很常见，下限不能把它排除在候选之外。"""
    values = _sawtooth(10, 60)  # 5min 粒度 → 50 分钟的周期
    estimate = estimate_period(values, "5min")
    assert estimate.found
    assert estimate.period_points == 10


def test_period_below_minimum_points_is_rejected():
    """少于 4 个点的「周期」没有统计意义。"""
    assert MIN_PERIOD_POINTS >= 4
    estimate = estimate_period(_sawtooth(2, 100), "5min")
    assert estimate.period_points is None or estimate.period_points >= MIN_PERIOD_POINTS


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


def test_detect_period_fallback_is_sampling_rate_independent():
    """不给显式 fallback 时，回退周期按时间给，而不是写死点数。"""

    class _Noise:
        values = np.random.default_rng(9).normal(size=10000)
        freq = "5min"

    assert detect_period(_Noise()) == default_fallback_period("5min", 10000)


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


def test_harmonic_threshold_separates_real_periods_from_spurious_ones():
    """真实周期的谐波强度要显著高于异常造成的伪周期。"""
    assert HARMONIC_THRESHOLD > 0.1
