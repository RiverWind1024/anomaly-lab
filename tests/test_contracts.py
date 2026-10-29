import numpy as np
import pytest

from anomaly_lab.contracts import DetectionResult, SeriesBundle


def _bundle(**kw):
    base = dict(
        series_id="s1",
        values=np.arange(10.0),
        timestamps=np.arange(10).astype("datetime64[ns]"),
        freq="1min",
    )
    base.update(kw)
    return SeriesBundle(**base)


def test_series_bundle_roundtrip():
    b = _bundle()
    assert b.n == 10
    assert not b.has_labels
    assert b.anomaly_indices().sum() == 0


def test_series_bundle_rejects_length_mismatch():
    with pytest.raises(ValueError, match="长度不一致"):
        _bundle(labels=np.zeros(3, dtype=np.int8))


def test_series_bundle_rejects_2d_values():
    with pytest.raises(ValueError, match="一维"):
        _bundle(values=np.zeros((3, 3)))


def test_detection_result_rejects_length_mismatch():
    with pytest.raises(ValueError, match="长度不一致"):
        DetectionResult(
            series_id="s1",
            scores=np.zeros(5),
            score_type="zscore",
            is_anomaly=np.zeros(4, dtype=bool),
            threshold=1.0,
            detector="iqr",
            elapsed_ms=1.0,
        )
