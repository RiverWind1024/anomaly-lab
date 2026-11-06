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


def test_第一个点不报():
    # 没有历史，无法判断 —— 不能拿全序列均值兜底
    values = np.zeros(50)
    values[0] = 100.0
    result = EventCountDetector(window=10).detect(_series(values))
    assert result.scores[0] == 0.0


def test_截断不变性_后面加数据不影响前面的分数():
    """⚠️ 因果性最强的证据：把后半段换掉，前半段分数必须逐位不变。"""
    rng = np.random.default_rng(11)
    values = (rng.uniform(size=250) < 0.3).astype(float)
    values[80:90] = 1.0

    base = EventCountDetector(window=10).detect(_series(values)).scores

    changed = values.copy()
    changed[150:] = 999.0
    after = EventCountDetector(window=10).detect(_series(changed)).scores

    np.testing.assert_allclose(after[:150], base[:150])


def test_事件结束后的零值点不再被报():
    """⚠️ 窗口的尾巴不是异常点 —— 告警必须落在真正发生事件的位置。

    否则一次 5 连事件会让后面 5 个 0 值点都报满分，
    用户看到「0 次 / 分数 1.0」，无法理解。
    """
    values = np.zeros(100)
    values[50:55] = 1.0
    result = EventCountDetector(window=10).detect(_series(values))

    assert result.is_anomaly[50:55].any()
    assert not result.is_anomaly[55:].any()
    assert (result.scores[55:] == 0).all()
