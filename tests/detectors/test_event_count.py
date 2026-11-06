import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.statistical import EventCountDetector


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle("s", values, np.arange(len(values)).astype("datetime64[m]"), "1min")


def test_不使用未来数据():
    values = np.zeros(200)
    values[190:200] = 1.0
    result = EventCountDetector(window=20).detect(_series(values))

    assert result.scores[185] == 0.0      # ⚠️ 居中窗口会把 190–195 算进来
    assert result.scores[195] > 0.0       # 因果窗口能看到刚发生的爆发


def test_有效窗口长度参与期望():
    values = np.ones(50)
    result = EventCountDetector(window=20).detect(_series(values))
    assert not result.is_anomaly.any()


def test_尺度来源标为_poisson():
    values = np.zeros(50)
    values[10:20] = 1.0
    result = EventCountDetector(window=20).detect(_series(values))
    assert result.scale_source == "poisson"
