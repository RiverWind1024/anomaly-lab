import numpy as np
import pytest

from anomaly_lab.contracts import DetectionResult


def _result(**kw):
    base = {
        "series_id": "s",
        "scores": np.zeros(5),
        "score_type": "zscore",
        "is_anomaly": np.zeros(5, dtype=bool),
        "threshold": 1.0,
        "detector": "iqr",
        "elapsed_ms": 1.0,
    }
    base.update(kw)
    return DetectionResult(**base)


def test_bands_default_to_none():
    result = _result()
    assert result.expected is None
    assert result.lower is None
    assert result.upper is None
    assert not result.has_bands


def test_bands_provided_together_are_accepted():
    result = _result(
        expected=np.ones(5),
        lower=np.zeros(5),
        upper=np.full(5, 2.0),
    )
    assert result.has_bands


def test_partial_bands_are_rejected():
    with pytest.raises(ValueError, match="同时提供"):
        _result(expected=np.ones(5))


def test_bands_length_must_match_scores():
    with pytest.raises(ValueError, match="长度必须等于"):
        _result(
            expected=np.ones(3),
            lower=np.zeros(3),
            upper=np.ones(3),
        )


def test_scores_length_mismatch_still_rejected():
    with pytest.raises(ValueError, match="scores 与 is_anomaly 长度不一致"):
        _result(scores=np.zeros(4), is_anomaly=np.zeros(5, dtype=bool))
