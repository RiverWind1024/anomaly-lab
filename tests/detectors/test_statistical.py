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
    """没有周期的序列用兜底周期，不能硬猜一个。"""
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
    assert detector.period == 24
