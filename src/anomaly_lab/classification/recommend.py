"""形态 → 检测器候选与参数域。"""

from __future__ import annotations

from dataclasses import dataclass

from anomaly_lab.contracts import MetricClass


@dataclass(frozen=True, eq=False)
class Recommendation:
    metric_class: MetricClass
    detectors: list[str]
    params: dict[str, dict]
    rationale: str


_RULES: dict[str, tuple[list[str], dict[str, dict], str]] = {
    "stationary": (
        ["iqr", "mad", "zscore"],
        {
            "iqr": {"k": [1.5, 3.0]},
            "mad": {"k": [3.0, 5.0]},
            "zscore": {"k": [2.0, 4.0]},
        },
        "平稳序列没有趋势/周期，用抗离群的全局阈值类方法即可",
    ),
    "periodic": (
        ["seasonal", "stl_residual", "iqr"],
        {"seasonal": {"k": [2.0, 4.0]}, "stl_residual": {}, "iqr": {"k": [1.5, 3.0]}},
        "周期型需要按相位分组或先做 STL 分解，否则季节性会被误判为异常",
    ),
    "trending": (
        ["deseasonalized_iqr", "stl_residual"],
        {"deseasonalized_iqr": {"k": [1.5, 3.0]}, "stl_residual": {}},
        "趋势会抬高全局方差，先去趋势再做残差阈值",
    ),
    "step": (
        ["changepoint"],
        {"changepoint": {"min_seg": [10, 30]}},
        "阶梯型的关键是变点位置，均值突变检测比点级阈值更合适",
    ),
    "high_zero_ratio": (
        ["iqr"],
        {"iqr": {"k": [2.0, 4.0]}},
        "大量零值会破坏均值/标准差，用分位数法更稳；零值专门建模留待 v2",
    ),
    "sparse_event": (
        ["event_count"],
        {"event_count": {"window": [20, 100]}},
        "稀疏事件应看窗口内事件计数相对泊松期望的偏离，而不是单点幅度",
    ),
}


def recommend_for(metric_class: MetricClass, features=None) -> Recommendation:
    detectors, params, rationale = _RULES[metric_class]
    if metric_class == "periodic" and features is not None:
        period = getattr(features, "dominant_period", None)
        if period:
            params = {**params, "seasonal": {**params["seasonal"], "period": period}}
            rationale = f"{rationale}（分类器给出周期长度 {period}）"
    return Recommendation(
        metric_class=metric_class,
        detectors=list(detectors),
        params={k: dict(v) for k, v in params.items()},
        rationale=rationale,
    )
