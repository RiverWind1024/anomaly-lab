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
