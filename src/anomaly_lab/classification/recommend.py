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
        # ⚠️ **不再推荐 `stl_residual`** ——
        #    它在无周期的趋势序列上会**爆掉**：STL 需要一个真实存在的周期，
        #    而 `detect_period` 对趋势序列会估出伪周期（实测 500 点序列估成 166，
        #    即「只有 3 个周期」），拿它去分解就得到一堆乱残差
        #    → 合成集 trending 上报出 2032 个点、精确率只有 11.3%。
        #
        #    它**不是废品** —— 在真周期序列上是最好的那个（F1 0.491）。
        #    只是不能用在「没有周期」的序列上。
        ["theil_sen", "trend_residual_iqr"],
        {"theil_sen": {"k": [2.5, 3.5]}, "trend_residual_iqr": {"k": [1.5, 3.0]}},
        (
            "趋势会抬高全局方差，先去趋势再做残差阈值；"
            "趋势线用 Theil-Sen 稳健估计（最小二乘会被尖峰拉偏）"
        ),
    ),
    "step": (
        ["changepoint", "trend_residual_iqr"],
        {
            "changepoint": {"min_seg": [10, 30]},
            "trend_residual_iqr": {"k": [1.5, 3.0]},
        },
        (
            "阶梯型的关键是变点位置，均值突变检测比点级阈值更合适"
            "（平台不支持变点检测，退而用去趋势后检测残差）"
        ),
    ),
    "high_zero_ratio": (
        ["zero_inflated_iqr", "event_count", "iqr"],
        {
            "zero_inflated_iqr": {"k": [2.0, 4.0]},
            "event_count": {"window": [20, 100]},
            "iqr": {"k": [2.0, 4.0]},
        },
        "零值会破坏 IQR/MAD 的分母；先看非零部分的幅度，或看事件频率",
    ),
    "sparse_event": (
        ["event_count", "poisson_count", "zero_inflated_iqr"],
        {
            "event_count": {"window": [20, 100]},
            "poisson_count": {"window": [10, 100]},
            "zero_inflated_iqr": {"k": [2.0, 4.0]},
        },
        (
            "零值 95%+ 的稀疏事件，先看「有没有发生」——"
            "二值化计数的信噪比高于直接拿值做泊松检验"
            "（合成评测集上点级 F1 明显更高）；"
            "幅度只有在非零点足够多时才估得准"
        ),
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
