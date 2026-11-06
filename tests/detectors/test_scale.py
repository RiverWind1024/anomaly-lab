"""尺度降级链：IQR → MAD → std → 不可判。"""

import numpy as np

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
