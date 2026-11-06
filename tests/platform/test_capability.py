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
