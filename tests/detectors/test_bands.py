import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.bands import compute_bands
from anomaly_lab.detectors.statistical import (
    ChangePointDetector,
    DeseasonalizedIQRDetector,
    IQRDetector,
    SeasonalDetector,
    STLResidualDetector,
)


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(len(values)).astype("datetime64[m]"),
        freq="1min",
    )


def test_iqr_bands_are_baseline_plus_minus_k_iqr():
    values = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    bands = compute_bands(IQRDetector(k=2.5), _series(values), threshold=2.5)
    assert bands is not None
    assert bands.baseline.shape == values.shape
    assert np.allclose(bands.baseline, np.median(values))
    assert np.all(bands.upper > bands.baseline)
    assert np.all(bands.lower < bands.baseline)


def test_seasonal_bands_are_symmetric_around_phase_center():
    t = np.arange(48 * 5)
    values = 10 + np.sin(2 * np.pi * t / 48) + 0.05 * np.cos(t * 1.7)
    bands = compute_bands(SeasonalDetector(period=48), _series(values), threshold=2.0)
    assert bands is not None
    assert bands.baseline.shape == values.shape
    assert np.all(np.isfinite(bands.baseline))
    assert np.allclose(bands.upper + bands.lower, 2 * bands.baseline)


def test_stl_bands_bracket_the_fitted_curve():
    t = np.arange(200)
    values = 5 + 3 * np.sin(2 * np.pi * t / 24) + 0.01 * t
    bands = compute_bands(STLResidualDetector(period=24), _series(values), threshold=3.5)
    assert bands is not None
    assert bands.baseline.shape == values.shape
    assert np.all(bands.upper >= bands.lower)
    assert np.all(np.isfinite(bands.baseline))


def test_deseasonalized_bands_are_symmetric():
    t = np.arange(120)
    values = 0.05 * t + np.sin(t / 3.0)
    bands = compute_bands(DeseasonalizedIQRDetector(), _series(values), threshold=2.5)
    assert bands is not None
    assert np.allclose(bands.upper + bands.lower, 2 * bands.baseline)


def test_detector_without_bands_returns_none():
    values = np.arange(100, dtype=float)
    assert compute_bands(ChangePointDetector(), _series(values), threshold=0.99) is None
