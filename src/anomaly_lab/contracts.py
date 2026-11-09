"""贯穿全流程的唯一数据契约（L1 出，L2/L3/L4 都用它）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

LabelSource = Literal["synthetic", "public", "human", "none"]
ScoreType = Literal["zscore", "pvalue", "residual_ratio", "prob"]
MetricClass = Literal[
    "stationary", "periodic", "trending", "step", "high_zero_ratio", "sparse_event"
]

#: 基线带的语义
#:
#: - `alert_boundary`：带边界**就是告警阈值** —— 值出带 ⟺ 判为异常（统计型检测器）
#: - `prediction_interval`：带是**模型自己的预测区间**，表达「模型认为正常值在哪儿、
#:   有多不确定」。它与告警阈值不是同一个边界（预测型检测器：TCN / LSTM / Chronos）
BandKind = Literal["alert_boundary", "prediction_interval"]


@dataclass(frozen=True, eq=False)
class SeriesBundle:
    """一条时序及其标注与元信息。"""

    series_id: str
    values: np.ndarray
    timestamps: np.ndarray
    freq: str
    labels: np.ndarray | None = None
    label_source: LabelSource = "none"
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.values.ndim != 1:
            raise ValueError("values 必须是一维")
        if len(self.values) != len(self.timestamps):
            raise ValueError("values 与 timestamps 长度不一致")
        if self.labels is not None and len(self.labels) != len(self.values):
            raise ValueError("labels 与 values 长度不一致")

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def has_labels(self) -> bool:
        return self.labels is not None and self.label_source != "none"

    def anomaly_indices(self) -> np.ndarray:
        if self.labels is None:
            return np.zeros(self.n, dtype=bool)
        return self.labels.astype(bool)


@dataclass(frozen=True, eq=False)
class DetectionResult:
    """一次检测的输出。`score_type` 决定分数语义，评估层按语义分桶搜阈值。

    **可选的基线三件套**（`expected` / `lower` / `upper`）：

    分数只说"多异常"，不说"正常值应该在哪儿"。没有基线，
    「实际值 vs 预测基线」就画不出来，告警也只能给一个孤零零的分数。

    - 统计型检测器：`expected` 是中心（中位数 / 相位中位数 / 拟合值），
      `lower`/`upper` 是 `expected ± threshold × scale` 的容忍带；
    - 预测型检测器（TCN / LSTM / Chronos）：`expected` 是**重构值或预测值**，
      `lower`/`upper` 是预测区间 —— 超出区间即异常。

    三者要么全为 None（检测器不支持基线），要么长度都等于序列长度。

    `band_kind` 声明带的语义 —— 前端据此标注「告警边界」还是「预测区间」，
    避免把模型的置信区间误读成告警线。
    """

    series_id: str
    scores: np.ndarray
    score_type: ScoreType
    is_anomaly: np.ndarray
    threshold: float
    detector: str
    elapsed_ms: float
    expected: np.ndarray | None = None
    lower: np.ndarray | None = None
    upper: np.ndarray | None = None
    band_kind: BandKind | None = None
    scale_source: str | None = None
    """这一窗实际用的尺度：iqr / mad / std / poisson / none。

    ⚠️ `poisson` 是 `event_count` / `poisson_count` 的尺度来源 ——
       它们用泊松基线估期望与离散度，不走 iqr/mad/std 降级链。
    ⚠️ 降级必须**可见** —— 否则「用 std 兜底」也是一种静默。
    """

    status: Literal["ok", "undetermined"] = "ok"
    """ok / undetermined。

    ⚠️ `undetermined` = 数据里没有可用的尺度（全常数序列），
       不是「一切正常」。前端要显示成「无法判定」。
    """

    scale_fallback: bool = False
    """尺度是否**降级**过（实际来源 ≠ 检测器首选）。

    ⚠️ 为什么不能只看 `scale_source == "std"`：
       `zscore` 的首选尺度就是 std，那是它的**原生**尺度，不是降级。
       只按字符串判断会把 zscore 每次预览都标成「降级」。
    """

    def __post_init__(self) -> None:
        if len(self.scores) != len(self.is_anomaly):
            raise ValueError("scores 与 is_anomaly 长度不一致")
        bands = (self.expected, self.lower, self.upper)
        present = [b is not None for b in bands]
        if any(present) and not all(present):
            raise ValueError("expected/lower/upper 必须同时提供或同时为空")
        if all(present):
            n = len(self.scores)
            for name, arr in zip(("expected", "lower", "upper"), bands):
                assert arr is not None  # all(present) 已保证
                if len(arr) != n:
                    raise ValueError(f"{name} 长度必须等于 scores 长度")

    @property
    def has_bands(self) -> bool:
        """是否带基线（可画出「实际 vs 基线 ± 容忍带」）。"""
        return self.expected is not None
