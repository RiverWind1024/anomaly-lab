import pytest

from anomaly_lab.classification.classifier import classify
from anomaly_lab.data.synthetic import generate_series


@pytest.mark.parametrize(
    "cls,expected",
    [
        ("stationary", "stationary"),
        ("periodic", "periodic"),
        ("trending", "trending"),
        ("step", "step"),
        ("high_zero_ratio", "high_zero_ratio"),
        ("sparse_event", "sparse_event"),
    ],
)
def test_classifier_recovers_known_class(cls, expected):
    s = generate_series(cls, n=500, seed=17)
    r = classify(s)
    assert r.metric_class == expected


def test_classifier_gives_reasons_and_confidence():
    s = generate_series("periodic", n=500, seed=19)
    r = classify(s)
    assert r.reasons, "必须给出可解释理由"
    assert 0.0 < r.confidence <= 1.0
    assert r.recommendation.detectors


def test_classifier_overall_accuracy_is_at_least_90_percent():
    from anomaly_lab.data.synthetic import generate_series

    total = correct = 0
    for cls in ["stationary", "periodic", "trending", "step", "high_zero_ratio", "sparse_event"]:
        for seed in range(8):
            s = generate_series(cls, n=500, seed=1000 + seed)
            r = classify(s)
            total += 1
            correct += int(r.metric_class == cls)
    acc = correct / total
    assert acc >= 0.90, f"分类准确率 {acc:.2f} < 0.90"


def test_recommendation_matches_class():
    s = generate_series("periodic", n=500, seed=23)
    r = classify(s)
    assert r.recommendation.metric_class == "periodic"
    assert "seasonal" in r.recommendation.detectors


def test_strong_trend_is_not_mistaken_for_periodic():
    """强趋势序列去趋势后会留下被误认成周期的残留结构。

    实测 trending 序列的伪周期 ACF 峰 0.862，比真周期的 0.273 还高——
    只看 ACF 峰会被骗。所以 periodic 判据必须带「趋势弱」的条件。
    """
    import numpy as np

    from anomaly_lab.classification.features import extract_features

    rng = np.random.default_rng(3)
    t = np.arange(500)
    # 强趋势 + 注入的异常（制造伪周期）
    values = 0.08 * t + rng.normal(0, 1.0, 500)
    values[300:340] += 6.0
    features = extract_features(values, "5min")
    assert features.trend_strength > 0.9

    from anomaly_lab.contracts import SeriesBundle

    series = SeriesBundle(
        series_id="t",
        values=values,
        timestamps=np.arange(500).astype("datetime64[ns]"),
        freq="5min",
    )
    result = classify(series)
    assert result.metric_class != "periodic"
