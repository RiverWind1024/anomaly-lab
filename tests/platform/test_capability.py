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


def test_count_ready_在稀疏计数上与looks_like_counts一致():
    counts = probe(np.array([0, 0, 1, 0, 2, 0, 0, 1, 0, 10], dtype=float))
    assert counts.looks_like_counts is True
    assert counts.count_ready is True

    continuous = probe(np.random.default_rng(0).normal(10, 2, 500))
    assert continuous.looks_like_counts is False
    assert continuous.count_ready is False


def test_全为正整数的序列也算计数型():
    values = np.array([1, 3, 2, 5, 4, 2, 6, 1, 3, 2] * 10, dtype=float)
    cap = probe(values)
    assert cap.count_ready is True
    # 但它不属于「稀疏计数」（没有零），zscore 的泊松警告不该出现
    assert cap.looks_like_counts is False


def test_catalog_每个检测器都带首选尺度():
    from anomaly_lab.platform.detectors import detector_catalog

    rows = {row["name"]: row for row in detector_catalog()}
    assert rows["iqr"]["prefer_scale"] == "iqr"
    assert rows["mad"]["prefer_scale"] == "mad"
    assert rows["zscore"]["prefer_scale"] == "std"
    for row in rows.values():
        assert "prefer_scale" in row



def test_无周期数据提示季节性算法会退化():
    """没有可信周期时，seasonal / stl_residual 的前提不成立。"""
    values = np.random.default_rng(0).normal(10, 2, 500)
    cap = probe(values)
    assert cap.has_period is False
    names = {w.detector for w in cap.shape_warnings}
    assert "seasonal" in names and "stl_residual" in names
    # ⚠️ 形态不适配**不参与** verdict —— 数据本身没问题，只是这两个算法不适用。
    #    否则几乎所有非周期序列都会被判成 unsuitable，这个字段就没意义了。
    assert cap.verdict == "ok"
    assert cap.warnings == []


def test_周期数据不提示缺少周期():
    rng = np.random.default_rng(1)
    t = np.arange(500)
    values = 10 + 3 * np.sin(2 * np.pi * t / 24) + rng.normal(0, 0.3, 500)
    cap = probe(values)
    assert cap.has_period is True
    names = {w.detector for w in cap.shape_warnings}
    assert "seasonal" not in names and "stl_residual" not in names


def test_周期数据提示趋势算法拟合不完整():
    """线性趋势线解释不了周期波动 —— 残差里仍是一个完整的正弦。"""
    rng = np.random.default_rng(1)
    t = np.arange(500)
    values = 10 + 3 * np.sin(2 * np.pi * t / 24) + rng.normal(0, 0.3, 500)
    cap = probe(values)
    assert cap.detrended_structure >= 0.3
    names = {w.detector for w in cap.shape_warnings}
    assert "theil_sen" in names and "trend_residual_iqr" in names


def test_纯线性趋势不提示非线性():
    """⚠️ 反例守卫：线性趋势 + 噪声必须被判成近似线性，不能一有趋势就报警。"""
    rng = np.random.default_rng(2)
    values = np.linspace(0, 100, 500) + rng.normal(0, 1, 500)
    cap = probe(values)
    assert cap.detrended_structure < 0.3
    names = {w.detector for w in cap.shape_warnings}
    assert "theil_sen" not in names and "trend_residual_iqr" not in names


def test_阶梯数据提示趋势算法():
    rng = np.random.default_rng(3)
    values = np.concatenate([np.zeros(250), np.full(250, 10.0)]) + rng.normal(0, 1, 500)
    cap = probe(values)
    assert cap.detrended_structure >= 0.3
    names = {w.detector for w in cap.shape_warnings}
    assert "theil_sen" in names
