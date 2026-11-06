import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.bands import Bands, compute_bands
from anomaly_lab.detectors.statistical import IQRDetector


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(len(values)).astype("datetime64[m]"),
        freq="1min",
    )


def test_bands_kind_defaults_to_alert_boundary():
    bands = compute_bands(IQRDetector(k=2.5), _series(np.arange(50.0)), threshold=2.5)
    assert bands is not None
    assert bands.kind == "alert_boundary"


def test_bands_kind_can_mark_prediction_interval():
    class Fake:
        name = "fake"
        score_type = "prob"

        def bands(self, series, threshold):
            n = len(series.values)
            return Bands(
                baseline=np.zeros(n),
                lower=np.full(n, -1.0),
                upper=np.full(n, 1.0),
                detector="fake",
                threshold=threshold,
                kind="prediction_interval",
            )

    bands = compute_bands(Fake(), _series(np.arange(10.0)), threshold=0.5)
    assert bands is not None
    assert bands.kind == "prediction_interval"


@pytest.mark.parametrize("detector_name", ["tcn"])
def test_deep_detector_provides_prediction_interval(tmp_path, detector_name):
    pytest.importorskip("torch")
    # ⚠️ deep 在模块层 import torch —— 不装 torch 时这里才会被跳过，
    #    所以 import 必须放在 importorskip **之后**（放文件头会让整份用例收集失败）。
    from anomaly_lab.data.synthetic import generate_series
    from anomaly_lab.detectors.deep import TCNDetector, train_tcn

    series = [
        generate_series("stationary", n=400, seed=200 + i, n_anomalies=0)
        for i in range(6)
    ]
    train_tcn(series, epochs=1, seed=1, out_path=tmp_path / "tcn.pt")
    detector = TCNDetector(model_path=tmp_path / "tcn.pt").fit(series[0])

    bands = compute_bands(detector, series[0], threshold=0.5)
    assert bands is not None
    assert bands.kind == "prediction_interval"
    assert bands.baseline.shape == series[0].values.shape
    assert bands.lower.shape == bands.baseline.shape
    assert bands.upper.shape == bands.baseline.shape
    # 上下界必须夹住基线
    assert np.all(bands.lower <= bands.baseline + 1e-9)
    assert np.all(bands.upper >= bands.baseline - 1e-9)


def test_deep_detector_result_carries_bands(tmp_path):
    pytest.importorskip("torch")
    # ⚠️ deep 在模块层 import torch —— 不装 torch 时这里才会被跳过，
    #    所以 import 必须放在 importorskip **之后**（放文件头会让整份用例收集失败）。
    from anomaly_lab.data.synthetic import generate_series
    from anomaly_lab.detectors.deep import TCNDetector, train_tcn

    series = [
        generate_series("stationary", n=400, seed=210 + i, n_anomalies=0)
        for i in range(6)
    ]
    train_tcn(series, epochs=1, seed=1, out_path=tmp_path / "tcn.pt")
    detector = TCNDetector(model_path=tmp_path / "tcn.pt")
    result = detector.fit(series[0]).detect(series[0])
    assert result.has_bands
    assert result.expected is not None
    assert len(result.expected) == len(series[0].values)


def test_statistical_detector_result_also_carries_bands():
    from anomaly_lab.data.synthetic import generate_series

    s = generate_series("stationary", n=300, seed=31)
    result = IQRDetector().fit(s).detect(s)
    assert result.has_bands
    assert len(result.expected) == s.n
    assert np.all(result.lower <= result.expected)
    assert np.all(result.upper >= result.expected)


def test_band_kind_travels_into_the_result():
    """带的语义必须一路传到契约里 —— 前端据此区分告警边界与预测区间。"""
    from anomaly_lab.data.synthetic import generate_series

    s = generate_series("stationary", n=300, seed=33)
    result = IQRDetector().fit(s).detect(s)
    assert result.band_kind == "alert_boundary"


def test_prediction_interval_band_kind_is_not_alert_boundary(tmp_path):
    """预测型检测器的带**不是**告警边界 —— 语义不能混。"""
    pytest.importorskip("torch")
    # ⚠️ deep 在模块层 import torch —— 不装 torch 时这里才会被跳过，
    #    所以 import 必须放在 importorskip **之后**（放文件头会让整份用例收集失败）。
    from anomaly_lab.data.synthetic import generate_series
    from anomaly_lab.detectors.deep import TCNDetector, train_tcn

    series = [
        generate_series("stationary", n=400, seed=220 + i, n_anomalies=0)
        for i in range(6)
    ]
    train_tcn(series, epochs=1, seed=1, out_path=tmp_path / "tcn.pt")
    result = TCNDetector(model_path=tmp_path / "tcn.pt").fit(series[0]).detect(series[0])
    assert result.band_kind == "prediction_interval"
    assert result.band_kind != "alert_boundary"
