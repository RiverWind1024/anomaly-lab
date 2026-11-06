"""自动推荐算法：按序列形态推断检测器。"""

import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DEFAULT_DETECTOR,
    MIN_AUTO_POINTS,
    resolve_detector,
)


def _bundle(values: np.ndarray, freq: str = "5min") -> SeriesBundle:
    n = len(values)
    return SeriesBundle(
        series_id="s",
        values=np.asarray(values, dtype=float),
        timestamps=np.arange(n).astype("datetime64[ns]"),
        freq=freq,
    )


def _periodic(n: int = 240) -> np.ndarray:
    t = np.arange(n)
    return np.sin(2 * np.pi * t / 24) + 0.01 * np.random.default_rng(0).normal(size=n)


def _stationary(n: int = 240) -> np.ndarray:
    return np.random.default_rng(1).normal(size=n)


def test_auto_picks_seasonal_for_periodic_series():
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(_periodic()))
    assert resolution.detector == "seasonal"
    assert resolution.metric_class == "periodic"
    assert resolution.fallback is False
    assert resolution.rationale


def test_auto_picks_a_global_detector_for_stationary_series():
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(_stationary()))
    assert resolution.metric_class == "stationary"
    assert resolution.detector in {"iqr", "mad", "zscore"}
    assert resolution.fallback is False


def test_auto_falls_back_when_series_is_too_short():
    """点数太少时形态特征不可靠，如实回退而不是硬猜。"""
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(np.arange(5.0)))
    assert resolution.detector == DEFAULT_DETECTOR
    assert resolution.fallback is True
    assert resolution.metric_class is None
    assert str(MIN_AUTO_POINTS) in resolution.rationale


def test_explicit_detector_is_used_as_is():
    resolution = resolve_detector("iqr", _bundle(_periodic()))
    assert resolution.detector == "iqr"
    assert resolution.requested == "iqr"
    assert resolution.metric_class is None
    assert resolution.fallback is False


def test_auto_picks_the_recommended_detector_when_supported():
    """首选算法现在平台支持了 —— 不该再回退到 iqr。"""
    from anomaly_lab.classification.classifier import classify

    sparse = np.zeros(240)
    sparse[::60] = 5.0  # 稀疏事件 → 首选 event_count
    assert classify(_bundle(sparse)).recommendation.detectors == [
        "event_count",
        "poisson_count",
        "zero_inflated_iqr",
    ]
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(sparse))
    assert resolution.detector == "event_count"
    assert resolution.fallback is False


def test_resolution_serializes_for_the_api():
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(_periodic()))
    data = resolution.as_dict()
    assert data["detector"] == "seasonal"
    assert data["requested"] == "auto"
    assert data["metric_class"] == "periodic"
    assert isinstance(data["confidence"], float)
    assert data["fallback"] is False


@pytest.mark.parametrize("name", ["iqr", "mad", "zscore", "seasonal", "deseasonalized_iqr"])
def test_all_supported_detectors_share_the_same_score_scale(name):
    """平台支持的检测器分数都是稳健 z 量纲，倍数规则才能跨检测器通用。"""
    from anomaly_lab.platform.detectors import create_detector

    detector = create_detector(name).fit(_bundle(_periodic()))
    scores = detector.score(_bundle(_periodic()))
    assert scores.ndim == 1
    assert np.all(scores >= 0)
