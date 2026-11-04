"""趋势型检测器：Theil-Sen 稳健趋势线 + 残差 MAD。

⚠️ 这个文件守的是一件**静默失效**的事：
   趋势型序列直接跑 IQR 会**大幅漏报** ——
   IQR 用全局分位数，趋势把整体分布拉宽，围栏跟着变宽，
   真正的突变点淹没在里面。界面显示「一切正常」，实际是「漏了」。

   实测（合成集 20 条 trending 序列，真异常 609 点）：
   `iqr` 召回只有 20.2%，去趋势类算法能到 52% 以上。
"""

from __future__ import annotations

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.statistical import IQRDetector, TrendResidualIQRDetector
from anomaly_lab.detectors.trend import TheilSenTrendDetector, theil_sen_trend


def _series(values, freq="5min"):
    values = np.asarray(values, dtype=float)
    return SeriesBundle(
        series_id="s",
        values=values,
        timestamps=list(range(len(values))),
        freq=freq,
    )


def _trending_with_spike(n=500, slope=0.077, sigma=0.74, spike_at=250, spike=3.0):
    """带线性趋势 + 一个尖峰的序列。

    ⚠️ 参数取自合成集 `trending-*` 的真实取值（n=500 / slope 0.077 / sigma 0.74）。
    """
    rng = np.random.default_rng(3)
    values = slope * np.arange(n, dtype=float) + rng.normal(0, sigma, n)
    values[spike_at] += spike
    return values


# ---------- 趋势线本身 ----------


def test_trend_line_follows_a_linear_trend():
    values = np.arange(100, dtype=float) * 3.0 + 5.0
    trend = theil_sen_trend(values)
    # ⚠️ 完全线性的序列，拟合误差应该极小
    assert np.max(np.abs(trend - values)) < 1e-6


def test_trend_line_is_not_pulled_by_an_outlier():
    """⚠️ **核心性质**：尖峰不能把趋势线拽歪。

    最小二乘会被单个离群点拉偏 —— 一次大幅尖峰就能让整条趋势线歪掉，
    剩下的点全变成「残差」（误报满天飞）。
    """
    values = _trending_with_spike()
    trend = theil_sen_trend(values)
    # 趋势线在尖峰**之前**应该贴着原始趋势（不被拉高）
    # ⚠️ 容差 1.0 —— 序列本身有 sigma=0.74 的噪声，斜率估计不可能完全准
    expected = 0.077 * np.arange(250, dtype=float)
    assert np.max(np.abs(trend[:250] - expected)) < 1.0


def test_trend_line_handles_short_series():
    assert len(theil_sen_trend(np.array([1.0]))) == 1
    assert len(theil_sen_trend(np.array([1.0, 2.0]))) == 2
    assert len(theil_sen_trend(np.array([]))) == 0


# ---------- 检测器行为 ----------


def test_detects_a_spike_on_a_trending_series():
    """⚠️ **这是本检测器存在的理由**：趋势型上的尖峰要能报出来。"""
    values = _trending_with_spike()
    result = TheilSenTrendDetector().fit(_series(values)).detect(
        _series(values), threshold=3.5
    )
    flagged = np.where(np.asarray(result.is_anomaly))[0]
    assert 250 in flagged, f"尖峰点没被报出来，报出的是 {flagged}"


def test_iqr_misses_the_same_spike():
    """⚠️ **对照**：同样的数据，IQR 报不出来。

    这条测试是整个改动的「为什么」——
    没有它，将来有人把去趋势逻辑删掉也不会有测试变红。
    """
    values = _trending_with_spike()
    result = IQRDetector(k=2.5).fit(_series(values)).detect(_series(values), threshold=2.5)
    flagged = np.where(np.asarray(result.is_anomaly))[0]
    assert 250 not in flagged, "IQR 居然报出来了 —— 那这条测试的前提就不成立"


def test_almost_no_false_alarm_on_a_clean_trend():
    """干净的趋势基本不该有告警。

    ⚠️ 断言是「很少」不是「一个都没有」——
       3.5 倍稳健尺度对正态噪声本来就有约 0.1% 的尾部概率，
       500 个点里出现 1~2 个是**统计正常**，不是缺陷。
       断言成 0 会让这条测试在换随机种子时随机变红。
    """
    rng = np.random.default_rng(7)
    values = 0.077 * np.arange(500, dtype=float) + rng.normal(0, 0.74, 500)
    result = TheilSenTrendDetector().fit(_series(values)).detect(
        _series(values), threshold=3.5
    )
    assert int(np.asarray(result.is_anomaly).sum()) <= 3


def test_score_is_in_scale_units():
    """分数是「几个尺度单位」—— 与统计族共用一套倍数阈值。"""
    detector = TheilSenTrendDetector()
    assert detector.score_type == "zscore"
    assert detector.default_threshold == 3.5


def test_bands_baseline_is_the_trend_line():
    """⚠️ 上下界带的基线应该是**趋势线**，不是水平线。

    平台要画「正常值应该在哪儿」——
    趋势型序列的正常值就在一条斜线上，画成水平线是错的。
    """
    values = _trending_with_spike()
    series = _series(values)
    result = TheilSenTrendDetector().fit(series).detect(series, threshold=3.5)
    assert result.expected is not None
    expected = np.asarray(result.expected)
    # 基线在上升
    assert expected[-1] > expected[0]
    # 且贴着原始趋势（尖峰处除外）
    assert abs(expected[50] - 0.077 * 50) < 1.0


def test_outlier_stays_in_the_residual():
    """⚠️ **打分必须用原始值** —— 异常点必须留在残差里。

    估趋势时清洗离群点是对的（趋势线更稳），
    但如果打分也用清洗值，检测器就**看不见**那个异常点了。
    """
    values = _trending_with_spike()
    detector = TheilSenTrendDetector().fit(_series(values))
    scores = detector.score(_series(values))
    assert scores[250] > 3.5


def test_degenerate_scale_does_not_silently_become_zero():
    """⚠️ **尺度退化为 0 时不能假装「一切正常」**。

    残差全是同一个值 → 尺度是 0 → 分数算不出来。
    把它变成 0 会让界面显示「正常」，那是**假的**。
    （`iqr` 那边有同样的缺陷，见 ROADMAP 的静默失效待办。）
    """
    values = np.full(100, 5.0)
    scores = TheilSenTrendDetector().fit(_series(values)).score(_series(values))
    assert not np.any(np.isfinite(scores)), "尺度退化时分数应该是 NaN（无法判定），不是 0"


# ---------- 与改名后的旧算法对比 ----------


def test_both_trend_algorithms_find_the_spike():
    """两个去趋势算法都应该能报出尖峰。"""
    values = _trending_with_spike()
    series = _series(values)
    for detector in (TheilSenTrendDetector(), TrendResidualIQRDetector()):
        result = detector.fit(series).detect(series, threshold=detector.default_threshold)
        assert 250 in np.where(np.asarray(result.is_anomaly))[0], detector.name
