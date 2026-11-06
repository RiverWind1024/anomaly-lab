"""耗时直方图的桶与分位计算。

⚠️ 桶必须显式指定 —— OTel SDK 的默认桶（0/5/10/25/…）对「0.2ms 的 IQR」
   和「30 秒的任务」都不合适。同一套桶要同时装下这两个量级。
"""

from __future__ import annotations

from collections.abc import Sequence

#: 耗时桶上界（毫秒）。
DURATION_BUCKETS_MS: tuple[float, ...] = (
    1.0,
    2.0,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,
    300_000.0,
)


def percentile(
    bucket_counts: Sequence[int], count: int, quantile: float
) -> float | None:
    """直方图近似分位：在命中的桶里做线性插值。

    ⚠️ 只取桶上界会让「平均 11ms」显示成 P95=25ms，看着像两个数量级。
       桶内均匀分布的假设不精确，但比直接取上界贴近真实值。
       精确分位要存每个样本，内存随请求量线性涨，不值得。
    """
    if count <= 0:
        return None
    target = quantile * count
    cumulative = 0
    lower = 0.0
    for upper, bucket in zip(DURATION_BUCKETS_MS, bucket_counts):
        if bucket and cumulative + bucket >= target:
            position = (target - cumulative) / bucket
            return lower + (upper - lower) * min(1.0, max(0.0, position))
        cumulative += bucket
        lower = upper
    return float(DURATION_BUCKETS_MS[-1])
