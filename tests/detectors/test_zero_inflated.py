import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.zero_inflated import (
    PoissonCountDetector,
    ZeroInflatedIQRDetector,
)


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(len(values)).astype("datetime64[m]"),
        freq="1min",
    )


def test_一次是正常抖动十次才算异常():
    # 每 30 分钟出现一次 1（正常抖动），第 200 点出现 10 次
    values = np.zeros(300)
    values[::30] = 1.0
    values[200] = 10.0

    result = PoissonCountDetector(window=30).detect(_series(values))

    assert not result.is_anomaly[90]       # 单次事件不报（90 是事件点）
    assert not result.is_anomaly[100]      # 零值点更不报
    assert result.is_anomaly[200]          # 10 次必报


def test_连续小突发靠窗口累计():
    # 常态：每 3 分钟 3 次；突发：连续 5 分钟各 3 次（频率 ×3，单点幅度不变）
    # ⚠️ 单点项和 2 点窗口都不够（< 0.99），必须靠 10 点窗口累计才报得出来。
    values = np.zeros(300)
    values[::3] = 3.0
    values[100:105] = 3.0

    assert not PoissonCountDetector(window=2).detect(_series(values)).is_anomaly.any()
    result = PoissonCountDetector(window=10).detect(_series(values))
    assert result.is_anomaly[100:105].any()


def test_零值不会被误报():
    values = np.zeros(100)
    result = PoissonCountDetector(window=10).detect(_series(values))
    assert not result.is_anomaly.any()


def test_第一个点不报():
    # 没有历史，无法判断 —— 不能拿全序列均值兜底
    values = np.zeros(50)
    values[0] = 100.0
    result = PoissonCountDetector(window=10).detect(_series(values))
    assert result.scores[0] == 0.0


def test_截断不变性_后面加数据不影响前面的分数():
    """⚠️ 因果性最强的证据：把后半段换掉，前半段分数必须逐位不变。"""
    rng = np.random.default_rng(7)
    values = rng.poisson(0.4, 250).astype(float)
    values[80:90] = 5.0

    base = PoissonCountDetector(window=10).detect(_series(values)).scores

    changed = values.copy()
    changed[150:] = 999.0
    after = PoissonCountDetector(window=10).detect(_series(changed)).scores

    np.testing.assert_allclose(after[:150], base[:150])


def test_poisson_count的尺度来源是poisson():
    values = np.zeros(100)
    values[::20] = 2.0
    result = PoissonCountDetector(window=10).detect(_series(values))
    assert result.scale_source == "poisson"
    assert result.status == "ok"


def test_非零幅度异常能报出来():
    # ⚠️ 非零点必须 ≥ 30（实现的门槛），且幅度要有变化（否则 IQR=0）
    values = np.zeros(300)
    idx = np.arange(0, 300, 4)[:60]              # 60 个非零点
    values[idx] = 4 + (np.arange(60) % 4)        # 4/5/6/7 循环 → IQR > 0
    values[idx[30]] = 50.0                       # 一个幅度异常

    result = ZeroInflatedIQRDetector(k=3.0).detect(_series(values))
    assert result.is_anomaly[idx[30]]
    assert not result.is_anomaly[idx[10]]


def test_非零点太少时标记无法判定():
    values = np.zeros(300)
    values[10] = values[20] = 5.0               # 只有 2 个非零点
    result = ZeroInflatedIQRDetector().detect(_series(values))
    assert result.status == "undetermined"


def test_zero_inflated_iqr的尺度来源是非零IQR():
    values = np.zeros(300)
    idx = np.arange(0, 300, 4)[:60]
    values[idx] = 4 + (np.arange(60) % 4)
    result = ZeroInflatedIQRDetector().detect(_series(values))
    assert result.scale_source == "iqr"
    assert result.status == "ok"


def test_zero_inflated_iqr降级到std时标记降级():
    # 非零点全是 7，只有一个 50 —— IQR=0、MAD=0，退到 std
    values = np.zeros(200)
    idx = np.arange(0, 200, 3)[:60]
    values[idx] = 7.0
    values[idx[30]] = 50.0
    result = ZeroInflatedIQRDetector().detect(_series(values))
    assert result.scale_source == "std"
    assert result.scale_fallback is True
