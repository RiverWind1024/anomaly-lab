import numpy as np
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
