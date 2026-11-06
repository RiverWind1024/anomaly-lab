"""形态 → 检测器推荐：首选算法要与形态的失效机理对应。"""

from anomaly_lab.classification.recommend import recommend_for


def test_高零值比例不推荐iqr():
    # ⚠️ MetricClass 是 Literal 类型别名，不是 Enum —— 直接用字符串
    rec = recommend_for("high_zero_ratio")
    assert rec.detectors[0] == "zero_inflated_iqr"


def test_稀疏事件首选事件计数():
    # ⚠️ 合成评测集上 event_count 的点级 F1（0.215）高于 poisson_count（0.161）——
    #    零值 95%+ 时先看「有没有发生」，比直接拿值做泊松检验更稳。
    #    poisson_count 仍是次选，手动可切。
    rec = recommend_for("sparse_event")
    assert rec.detectors[0] == "event_count"
    assert "poisson_count" in rec.detectors
