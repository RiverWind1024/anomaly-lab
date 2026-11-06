"""数据能力探测：这个指标会让哪些算法失效。"""

import numpy as np

from anomaly_lab.platform.capability import probe


def test_零膨胀判iqr不适用():
    values = np.zeros(200)
    values[[10, 60, 110, 160]] = [1.0, 2.0, 1.0, 3.0]   # 98% 零
    cap = probe(values)
    assert cap.zero_ratio == 0.98
    assert cap.n_nonzero == 4
    assert cap.verdict == "unsuitable"
    names = {w.detector for w in cap.warnings}
    assert "iqr" in names and "mad" in names


def test_计数型能识别():
    values = np.array([0, 0, 1, 0, 2, 0, 0, 1, 0, 10], dtype=float)
    cap = probe(values)
    assert cap.looks_like_counts is True


def test_连续值不判失效():
    cap = probe(np.random.default_rng(0).normal(10, 2, 500))
    assert cap.verdict == "ok"
    assert cap.warnings == []


def test_全常数序列不可判():
    cap = probe(np.full(100, 3.0))
    assert cap.verdict == "undetermined"


def test_计数型且零值很多时给出泊松建议():
    """稀疏计数是 poisson_count 的目标场景 —— 不能只警告 zscore。"""
    values = np.array([0, 0, 0, 1, 0, 0, 2, 0, 0, 0] * 20, dtype=float)
    cap = probe(values)
    assert cap.looks_like_counts is True
    assert cap.verdict == "unsuitable"


def test_非零点太少时提示零膨胀IQR也估不准():
    values = np.zeros(200)
    values[[10, 60, 110]] = [5.0, 6.0, 7.0]      # 只有 3 个非零点
    cap = probe(values)
    names = {w.detector for w in cap.warnings}
    assert "zero_inflated_iqr" in names


def test_恰好75百分比零不误报iqr():
    """⚠️ 75% 零时 q75 落在非零区，IQR > 0 —— 百分比阈值会误报。"""
    rng = np.random.default_rng(0)
    values = np.zeros(200)
    values[50:] = rng.uniform(1, 2, 150)   # 75% 零，非零值是连续正值
    cap = probe(values)
    names = {w.detector for w in cap.warnings}
    assert "iqr" not in names


def test_恰好50百分比零不误报mad():
    rng = np.random.default_rng(0)
    values = np.concatenate([np.zeros(100), rng.uniform(1, 2, 100)])  # 50% 零
    cap = probe(values)
    names = {w.detector for w in cap.warnings}
    assert "mad" not in names


def test_76百分比零才报iqr失效():
    rng = np.random.default_rng(0)
    values = np.zeros(200)
    values[152:] = rng.uniform(1, 2, 48)   # 76% 零
    cap = probe(values)
    names = {w.detector for w in cap.warnings}
    assert "iqr" in names


def test_catalog_每个检测器都带首选尺度():
    from anomaly_lab.platform.detectors import detector_catalog

    rows = {row["name"]: row for row in detector_catalog()}
    assert rows["iqr"]["prefer_scale"] == "iqr"
    assert rows["mad"]["prefer_scale"] == "mad"
    assert rows["zscore"]["prefer_scale"] == "std"
    for row in rows.values():
        assert "prefer_scale" in row

