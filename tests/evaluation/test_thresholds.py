import numpy as np
import pytest

from anomaly_lab.evaluation.thresholds import ThresholdResult, search_threshold


def test_search_finds_good_threshold():
    scores = np.array([0.0, 0.1, 5.0, 0.2, 6.0, 0.3])
    truth = np.array([0, 0, 1, 0, 1, 0], dtype=np.int8)
    r = search_threshold(scores, "zscore", truth)
    assert isinstance(r, ThresholdResult)
    assert r.recall == pytest.approx(1.0)
    assert r.f1 > 0.9


def test_threshold_search_requires_truth():
    with pytest.raises(ValueError):
        search_threshold(np.zeros(5), "zscore", None)


def test_zero_division_precision_is_zero():
    scores = np.array([1.0, 1.0])
    truth = np.array([0, 0], dtype=np.int8)
    r = search_threshold(scores, "zscore", truth)
    assert r.precision == 0.0


def test_prob_semantics_uses_unit_range():
    scores = np.linspace(0, 1, 50)
    truth = (scores > 0.8).astype(np.int8)
    r = search_threshold(scores, "prob", truth)
    assert 0.0 <= r.threshold <= 1.0
