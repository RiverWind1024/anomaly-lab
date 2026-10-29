import pytest

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector, MADDetector, ZScoreDetector


def _spike_series():
    return generate_series(
        "stationary", n=500, seed=31, n_anomalies=1, anomaly_types=["spike"]
    )


@pytest.mark.parametrize("det", [IQRDetector(), MADDetector(), ZScoreDetector()])
def test_detects_injected_spike(det):
    s = _spike_series()
    r = det.detect(s)
    hit = (r.is_anomaly & s.anomaly_indices().astype(bool)).sum()
    assert hit >= 1


@pytest.mark.parametrize("det", [IQRDetector(), MADDetector(), ZScoreDetector()])
def test_clean_series_false_positive_rate_low(det):
    s = generate_series("stationary", n=500, seed=33, n_anomalies=0)
    r = det.detect(s)
    assert r.is_anomaly.mean() < 0.02


def test_iqr_rolling_window_handles_trend():
    s = generate_series("trending", n=400, seed=34, n_anomalies=0)
    r = IQRDetector(k=1.5, window=100).detect(s)
    assert r.is_anomaly.mean() < 0.10


def test_statistical_metadata_and_score_semantics():
    s = _spike_series()
    r = IQRDetector().detect(s)
    assert r.detector == "iqr"
    assert r.score_type == "zscore"
    assert r.elapsed_ms >= 0
    assert r.scores.shape == s.values.shape


def _periodic_series(period: int = 48, n: int = 400):
    import numpy as np

    from anomaly_lab.contracts import SeriesBundle

    t = np.arange(n)
    rng = np.random.default_rng(5)
    values = 5 + 2 * np.sin(2 * np.pi * t / period) + rng.normal(0, 0.3, n)
    return SeriesBundle(
        series_id="p",
        values=values,
        timestamps=np.arange(n).astype("datetime64[ns]"),
        freq="5min",
    )


def test_seasonal_detector_estimates_period_from_the_series():
    """周期按序列估计，而不是写死 24——5min 粒度下 24 点只有 2 小时。"""
    from anomaly_lab.detectors.statistical import SeasonalDetector

    detector = SeasonalDetector().fit(_periodic_series(48))
    assert detector.period == 48


def test_stl_residual_detector_estimates_period_from_the_series():
    from anomaly_lab.detectors.statistical import STLResidualDetector

    detector = STLResidualDetector().fit(_periodic_series(48))
    assert detector.period == 48


def test_explicit_period_is_respected():
    from anomaly_lab.detectors.statistical import SeasonalDetector

    detector = SeasonalDetector(period=12).fit(_periodic_series(48))
    assert detector.period == 12


def test_period_falls_back_when_series_has_no_cycle():
    """没有可信周期时**不做**相位分组，退化成全局稳健统计。

    猜一个周期再去分组只会造出混相位的基线，比不做季节性更糟：
    实测非周期序列被分到 250 个相位（每相位仅 2 个点）时，
    中位数与 MAD 都不稳定，F1 从 0.305 掉到 0.192。
    """
    import numpy as np

    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import SeasonalDetector

    values = np.random.default_rng(11).normal(size=400)
    series = SeriesBundle(
        series_id="n",
        values=values,
        timestamps=np.arange(400).astype("datetime64[ns]"),
        freq="5min",
    )
    detector = SeasonalDetector().fit(series)
    assert detector.seasonal is False
    assert detector.period == 0


def test_global_fallback_mode_matches_a_robust_detector():
    """无季节性模式等价于全局中位数 + 全局 MAD。"""
    import numpy as np

    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import MADDetector, SeasonalDetector

    values = np.random.default_rng(12).normal(size=300)
    values[150] += 20.0
    series = SeriesBundle(
        series_id="n",
        values=values,
        timestamps=np.arange(300).astype("datetime64[ns]"),
        freq="5min",
    )
    seasonal = SeasonalDetector().fit(series)
    assert seasonal.seasonal is False
    mad = MADDetector().detect(series)
    assert np.allclose(seasonal.score(series), mad.scores)


def test_fallback_period_is_sampling_rate_independent():
    """同一个兜底时间长度，在不同粒度下换算成不同点数。"""
    from anomaly_lab.detectors.period import default_fallback_period

    # 一天：1min → 1440 点，5min → 288 点，1h → 24 点
    assert default_fallback_period("1min", 20000) == 1440
    assert default_fallback_period("5min", 20000) == 288
    assert default_fallback_period("1h", 20000) == 24


def test_fallback_period_respects_minimum_samples_per_phase():
    """每个相位至少要有足够样本，否则相位内的中位数/MAD 不稳定。"""
    from anomaly_lab.detectors.period import MIN_SAMPLES_PER_PHASE, default_fallback_period

    n = 400
    period = default_fallback_period("5min", n)
    assert n // period >= MIN_SAMPLES_PER_PHASE


def test_bands_are_finite_when_phase_scale_is_zero():
    """相位组内完全确定时（尺度为 0），基线与上下界不能变成 NaN。

    完全确定的周期是理想情况，不该让整条曲线的基线失效。
    """
    import numpy as np

    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import SeasonalDetector

    values = np.array([float(i % 10) for i in range(60)])
    series = SeriesBundle(
        series_id="p",
        values=values,
        timestamps=np.arange(60).astype("datetime64[ns]"),
        freq="5min",
    )
    detector = SeasonalDetector(period=10).fit(series)
    bands = detector.bands(series, 2.5)
    assert np.all(np.isfinite(bands.baseline))
    assert np.all(np.isfinite(bands.lower))
    assert np.all(np.isfinite(bands.upper))
    assert np.all(bands.lower <= bands.upper)


def test_spike_stays_visible_after_cleaning():
    """清洗只用于估计，打分必须用原始值——否则异常会被洗掉。"""
    import numpy as np

    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import SeasonalDetector

    values = np.array([float(i % 10) for i in range(60)])
    values[30] += 50.0
    series = SeriesBundle(
        series_id="p",
        values=values,
        timestamps=np.arange(60).astype("datetime64[ns]"),
        freq="5min",
    )
    detector = SeasonalDetector(period=10).fit(series)
    scores = detector.score(series)
    assert np.isfinite(scores).all()
    others = np.delete(scores, 30)
    assert scores[30] > 0.0, "尖峰必须被打分"
    assert scores[30] > others.max() * 10 + 1.0, "尖峰分数应显著高于正常点"
