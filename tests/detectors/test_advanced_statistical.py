from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import (
    ChangePointDetector,
    DeseasonalizedIQRDetector,
    EventCountDetector,
    IQRDetector,
    SeasonalDetector,
    STLResidualDetector,
)


def test_seasonal_detector_finds_phase_anomaly():
    s = generate_series(
        "periodic", n=1000, seed=41, n_anomalies=1, anomaly_types=["contextual"]
    )
    res = SeasonalDetector(period=50).fit(s).detect(s)
    assert res.is_anomaly.sum() > 0
    assert (res.is_anomaly & s.anomaly_indices()).sum() >= 1


def test_stl_residual_detector_works_on_trend():
    s = generate_series("trending", n=600, seed=43, n_anomalies=1, anomaly_types=["spike"])
    res = STLResidualDetector(period=24).fit(s).detect(s)
    assert res.score_type == "residual_ratio"
    assert (res.is_anomaly & s.anomaly_indices()).sum() >= 1


def test_deseasonalized_iqr_reduces_false_positive_on_trend():
    s = generate_series("trending", n=600, seed=45, n_anomalies=0)
    plain = IQRDetector().fit(s).detect(s).is_anomaly.mean()
    deseason = DeseasonalizedIQRDetector().fit(s).detect(s).is_anomaly.mean()
    assert deseason <= plain


def test_changepoint_detector_detects_step():
    s = generate_series("step", n=500, seed=47, n_anomalies=0)
    res = ChangePointDetector(min_seg=20).fit(s).detect(s)
    assert res.score_type == "prob"
    assert res.is_anomaly.sum() > 0


def test_event_count_detector_on_sparse_series():
    s = generate_series(
        "sparse_event", n=500, seed=49, n_anomalies=1, anomaly_types=["spike"]
    )
    res = EventCountDetector(window=50).fit(s).detect(s)
    assert (res.is_anomaly & s.anomaly_indices()).sum() >= 1
