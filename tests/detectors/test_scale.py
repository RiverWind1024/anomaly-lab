"""尺度降级链：IQR → MAD → std → 不可判。"""

import numpy as np
import pytest

from anomaly_lab.detectors.scale import majority_source, pick_scale, robust_scale


def test_正常数据用首选尺度():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    est = robust_scale(values, prefer="iqr")
    assert est.source == "iqr"
    assert est.value == np.percentile(values, 75) - np.percentile(values, 25)


def test_iqr和mad都为零时退回std():
    # ⚠️ 80% 零：q75=0 → IQR=0；MAD 也=0（>50% 零）→ 必须继续降级到 std
    #    （60% 零时 IQR 还有 1.75，测不到降级 —— 这是实际算过的）
    values = np.array([0.0] * 8 + [1.0, 2.0])
    est = robust_scale(values, prefer="iqr")
    assert est.source == "std"
    assert est.value == np.std(values)


def test_全常数序列不可判():
    est = robust_scale(np.ones(50), prefer="iqr")
    assert est.source == "none"
    assert est.value == 0.0


def test_pick_scale逐点挑第一个正值():
    scale, source = pick_scale(
        prefer="iqr",
        candidates={
            "iqr": np.array([0.0, 2.0, 0.0, 0.0]),
            "mad": np.array([0.0, 0.0, 1.5, 0.0]),
            "std": np.array([0.0, 0.0, 0.0, 3.0]),
        },
    )
    assert list(scale) == [0.0, 2.0, 1.5, 3.0]
    assert list(source) == ["none", "iqr", "mad", "std"]


def test_pick_scale优先级是首选在前():
    # ⚠️ 三个候选同时为正时，必须选首选的那个。
    #    写成 reversed() 会让 std 永远赢 —— 正常数据的分数会全变。
    scale, source = pick_scale(
        prefer="iqr",
        candidates={
            "iqr": np.array([2.0]),
            "mad": np.array([1.0]),
            "std": np.array([3.0]),
        },
    )
    assert list(scale) == [2.0]
    assert list(source) == ["iqr"]


def test_数值噪声不算尺度():
    # ⚠️ 常数序列经过 polyfit/STL 后残差是 1e-16 量级，不是精确 0
    est = robust_scale(np.full(100, 5.0) + 1e-16 * np.arange(100))
    assert est.source == "none"


def test_pick_scale容忍缺失候选():
    # ⚠️ ZScore 只提供 std —— 不能因为它没给 iqr 就 KeyError
    scale, source = pick_scale(prefer="std", candidates={"std": np.array([0.0, 2.0])})
    assert list(scale) == [0.0, 2.0]
    assert list(source) == ["none", "std"]


def test_majority_source忽略none():
    source = np.array(["none", "iqr", "iqr", "std"], dtype=object)
    assert majority_source(source) == "iqr"
    assert majority_source(np.array(["none", "none"], dtype=object)) == "none"


def test_robust_scale不返回inf():
    # ⚠️ 超大值会让 std 溢出成 inf；inf > floor 成立，
    #    旧实现会返回 value=inf，于是 score = 偏差 / inf = 0 ——
    #    又变回「算不出来当成正常」。必须跳过 inf 继续降级。
    values = np.array([0.0, 1e308, -1e308, 1.0])
    with np.errstate(over="ignore"):
        est = robust_scale(values, prefer="std")
    assert est.source == "iqr"
    assert np.isfinite(est.value)


def test_mad来源时带1_4826系数():
    values = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 100.0])
    est = robust_scale(values, prefer="mad")
    assert est.source == "mad"
    assert est.value == pytest.approx(
        np.median(np.abs(values - np.median(values))) * 1.4826
    )


def test_pick_scale忽略非有限候选():
    scale, source = pick_scale(
        prefer="iqr",
        candidates={
            "iqr": np.array([np.nan, np.inf, 2.0]),
            "std": np.array([1.0, 1.0, 1.0]),
        },
    )
    assert list(scale) == [1.0, 1.0, 2.0]
    assert list(source) == ["std", "std", "iqr"]


def test_pick_scale的floor压掉数值噪声():
    _scale, source = pick_scale(
        prefer="iqr", candidates={"iqr": np.array([1e-13, 1.0])}, floor=1e-12
    )
    assert list(source) == ["none", "iqr"]


def test_majority_source可判点不足一半时返回none():
    source = np.array(["none"] * 9 + ["std"], dtype=object)
    assert majority_source(source) == "none"


def test_iqr在零膨胀数据上不再恒为0分():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    values = np.zeros(200)
    values[50] = 25.0
    values[150] = 25.0
    series = SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(200).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector(k=2.5).detect(series)
    assert result.scale_source == "std"
    assert result.scores[50] > 2.5          # 必须能报出来
    assert result.scores[0] == 0.0


def test_全常数序列标记为无法判定():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    series = SeriesBundle(
        series_id="s",
        values=np.full(100, 7.0),
        timestamps=np.arange(100).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector().detect(series)
    assert result.status == "undetermined"
    assert not result.is_anomaly.any()


def test_高量级数据的真实波动不算噪声():
    # ⚠️ 1e9 量级、1e-4 波动 —— 远高于浮点分辨率（约 7e-6），不是噪声
    rng = np.random.default_rng(0)
    values = 1e9 + rng.normal(0, 1e-4, 400)
    est = robust_scale(values, prefer="iqr")
    assert est.source == "iqr"
    assert est.value > 1e-5


def test_高量级数据不会被判成无法判定():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    rng = np.random.default_rng(0)
    values = 1e9 + rng.normal(0, 1e-4, 400)
    series = SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(400).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector().detect(series)
    assert result.scale_source == "iqr"
    assert result.status == "ok"
    # ⚠️ 断言用 2.5（默认阈值）而不是 3.0：400 点 N(0,1) 的最大偏差约 3.74σ，
    #    除以 IQR(≈1.349σ) 只有约 2.77 —— 3.0 在高斯噪声下数学上达不到。
    assert result.scores.max() > 2.5
    assert result.is_anomaly.any()


def test_MAD滚动窗口在暖机段降级到iqr():
    # ⚠️ 滚动 MAD 需要 2×window 才有效（两次 rolling 各 shift 一次），
    #    暖机段必须降级到 iqr —— 不能静默返回 0 分。
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector, MADDetector

    rng = np.random.default_rng(7)
    values = rng.normal(0, 1, 400)
    series = SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(400).astype("datetime64[m]"),
        freq="1min",
    )
    mad_scores = MADDetector(window=50).score(series)
    iqr_scores = IQRDetector(window=50).score(series)
    # 暖机段（50..99）两者一致；稳定段（100 之后）应该不同
    assert np.allclose(mad_scores[50:100], iqr_scores[50:100])
    assert not np.allclose(mad_scores[100:], iqr_scores[100:])


def test_滚动窗口下零膨胀仍能报出来():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    rng = np.random.default_rng(3)
    values = np.zeros(400)
    values[::40] = rng.normal(10, 2, 10)   # 每 40 点一次事件，有幅度
    series = SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(400).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector(k=2.5, window=50).detect(series)
    assert result.scores.max() > 2.5


def test_窗口比序列还长时标记无法判定():
    # ⚠️ window > n/2 时可用点不足一半 —— 这是有意的保守行为，用测试固定住
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    rng = np.random.default_rng(5)
    values = rng.normal(0, 1, 60)
    series = SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(60).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector(window=50).detect(series)
    assert result.status == "undetermined"
