"""三个稀疏 / 计数型检测器要真正进平台清单，而不只是能 import。"""

from anomaly_lab.platform.detectors import (
    DEFAULT_DETECTOR_SET,
    DETECTOR_LABELS,
    SCORE_FAMILY_PROB,
    SCORE_FAMILY_SCALE,
    detector_catalog,
    detector_score_family,
)

#: 本轮新注册的三个检测器
NEW_DETECTORS = ("event_count", "poisson_count", "zero_inflated_iqr")


def _rows() -> dict[str, dict]:
    return {row["name"]: row for row in detector_catalog()}


def test_新检测器都在平台清单里():
    rows = _rows()
    for name in NEW_DETECTORS:
        assert name in rows, name
        assert rows[name]["available"] is True, name
        assert rows[name]["reason"] is None, name


def test_新检测器只报偏高():
    """三个都没有 `bands()` —— 给不出「正常值应该在哪」，所以不能报偏低。"""
    rows = _rows()
    for name in NEW_DETECTORS:
        assert rows[name]["direction"] == "above", name


def test_新检测器的首选尺度():
    """`zero_inflated_iqr` 内部走 `robust_scale(prefer="iqr")`，必须声明首选尺度，
    否则降级到 std 时 `scale_fallback` 永远是 False，用户看不到尺度降级。
    另外两个不做尺度估计，偏好尺度是 None。"""
    rows = _rows()
    assert rows["zero_inflated_iqr"]["prefer_scale"] == "iqr"
    for name in ("event_count", "poisson_count"):
        assert rows[name]["prefer_scale"] is None, name


def test_theil_sen声明首选尺度():
    """`theil_sen` 走 `robust_scale(prefer="mad")` —— 不声明的话降级不可见。"""
    assert _rows()["theil_sen"]["prefer_scale"] == "mad"


def test_新检测器都有中文标签():
    rows = _rows()
    for name in NEW_DETECTORS:
        assert DETECTOR_LABELS[name], name
        assert rows[name]["label"] == DETECTOR_LABELS[name], name


def test_新检测器的分数量纲族():
    """⚠️ 阈值能不能跨算法沿用由它决定：

    `event_count` / `poisson_count` 是累计概率（0.99 量级）；
    `zero_inflated_iqr` 仍是 z 分数（倍数 3.0）。
    """
    assert detector_score_family("event_count") == SCORE_FAMILY_PROB
    assert detector_score_family("poisson_count") == SCORE_FAMILY_PROB
    assert detector_score_family("zero_inflated_iqr") == SCORE_FAMILY_SCALE


def test_新检测器进默认评测集合():
    """评测要遍历它们；慢的 Chronos 仍然不在集合里。"""
    for name in NEW_DETECTORS:
        assert name in DEFAULT_DETECTOR_SET, name
    assert "chronos" not in DEFAULT_DETECTOR_SET
