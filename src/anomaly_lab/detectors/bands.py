"""检测器的可解释输出：中心基线 + 双向上下界。

平台层用它把「异常分数」翻译成「实际值偏离基线多远」，避免前端各自实现公式。

⚠️ **两种语义必须分清**（`kind` 字段）：

- `alert_boundary`（统计型检测器）：带的边界**就是告警阈值** ——
  值落在带外 ⟺ 分数超过阈值。前端画出来就能直接对照告警点。
- `prediction_interval`（预测型检测器：TCN / LSTM / Chronos）：
  带是**模型自己的预测区间**（重构值 ± 残差尺度 / 预测分位数），
  表达「模型认为正常值在哪儿、有多不确定」。它与告警阈值**不是同一个边界** ——
  预测型检测器的分数是序列内 min-max 归一的相对量，阈值语义与之不同。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.contracts import BandKind, SeriesBundle


@dataclass(frozen=True, eq=False)
class Bands:
    """基线与双向上下界；长度与被检测序列一致。"""

    baseline: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    detector: str
    threshold: float
    kind: BandKind = "alert_boundary"

    def __post_init__(self) -> None:
        n = len(self.baseline)
        if len(self.lower) != n or len(self.upper) != n:
            raise ValueError("baseline/lower/upper 长度必须一致")


def compute_bands(
    detector: object, series: SeriesBundle, threshold: float
) -> Bands | None:
    """检测器可选实现 `bands(series, threshold)`；没有则返回 None。"""
    method = getattr(detector, "bands", None)
    if not callable(method):
        return None
    result = method(series, float(threshold))
    if result is None:
        return None
    if not isinstance(result, Bands):
        raise TypeError("detector.bands 必须返回 Bands 或 None")
    return result
