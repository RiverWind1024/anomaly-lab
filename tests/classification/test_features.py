import numpy as np
import pytest

from anomaly_lab.classification.features import (
    adf_statistic,
    change_point_score,
    dominant_period,
    extract_features,
    zero_ratio,
)


def test_adf_on_stationary_is_significant():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 400)
    _, p = adf_statistic(x)
    assert p < 0.05


def test_adf_on_trend_is_not_significant():
    t = np.arange(400)
    x = 0.05 * t + np.random.default_rng(1).normal(0, 1, 400)
    _, p = adf_statistic(x)
    assert p > 0.05


def test_dominant_period_detects_sine():
    t = np.arange(1000)
    x = np.sin(2 * np.pi * t / 50)
    assert dominant_period(np.correlate(x - x.mean(), x - x.mean(), "full")[999:]) == 50


def test_zero_ratio():
    x = np.array([0.0, 0.0, 1.0, 0.0, 2.0])
    assert zero_ratio(x) == pytest.approx(0.6)


def test_changepoint_score_high_for_step():
    x = np.concatenate([np.zeros(200), np.ones(200) * 10])
    assert change_point_score(x) > 0.5


def test_extract_features_returns_finite_values():
    rng = np.random.default_rng(2)
    f = extract_features(rng.normal(0, 1, 300))
    for v in (f.adf_pvalue, f.zero_ratio, f.sparsity, f.noise_ratio, f.std):
        assert np.isfinite(v)


def test_extract_features_handles_constant_series():
    f = extract_features(np.ones(100))
    assert f.std == pytest.approx(0.0)
