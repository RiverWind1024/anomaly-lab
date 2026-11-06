"""形态 → 检测器推荐：首选算法要与形态的失效机理对应。"""

from anomaly_lab.classification.recommend import recommend_for


def test_高零值比例不推荐iqr():
    # ⚠️ MetricClass 是 Literal 类型别名，不是 Enum —— 直接用字符串
    rec = recommend_for("high_zero_ratio")
    assert rec.detectors[0] == "zero_inflated_iqr"


def test_稀疏事件推荐泊松计数():
    rec = recommend_for("sparse_event")
    assert rec.detectors[0] == "poisson_count"
