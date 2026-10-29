import numpy as np
import pytest

from anomaly_lab.data.synthetic import generate_series

CLASSES = ["stationary", "periodic", "trending", "step", "high_zero_ratio", "sparse_event"]


@pytest.mark.parametrize("cls", CLASSES)
def test_generated_series_shape_and_labels(cls):
    s = generate_series(cls, n=500, seed=1)
    assert s.n == 500
    assert s.label_source == "synthetic"
    assert s.labels is not None
    assert s.labels.dtype == np.int8
    assert s.meta["metric_class"] == cls
    # 真值必须非空（注入成功）
    assert s.anomaly_indices().sum() > 0


@pytest.mark.parametrize("cls", CLASSES)
def test_generation_is_reproducible(cls):
    a = generate_series(cls, n=300, seed=7)
    b = generate_series(cls, n=300, seed=7)
    c = generate_series(cls, n=300, seed=8)
    assert np.array_equal(a.values, b.values)
    assert np.array_equal(a.labels, b.labels)
    assert not np.array_equal(a.values, c.values)


def test_anomaly_intervals_match_labels():
    s = generate_series("stationary", n=500, seed=3, n_anomalies=4)
    intervals = s.meta["anomaly_types"]
    assert len(intervals) == 4
    for iv in intervals:
        assert iv["start"] >= 0 and iv["end"] < s.n
        # 标注必须与注入区间一致
        assert s.labels[iv["start"] : iv["end"] + 1].all() == 1


def test_flatline_anomaly_produces_constant_run():
    s = generate_series(
        "stationary", n=400, seed=11, n_anomalies=1, anomaly_types=["flatline"]
    )
    iv = s.meta["anomaly_types"][0]
    seg = s.values[iv["start"] : iv["end"] + 1]
    assert np.allclose(seg, seg[0])


def test_no_anomaly_leaks_into_label_free_region():
    s = generate_series("periodic", n=500, seed=5)
    idx = s.anomaly_indices()
    # 至少 85% 的点应是非异常（保证任务有意义）
    assert idx.mean() < 0.15
