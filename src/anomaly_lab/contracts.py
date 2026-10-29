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
    """一次检测的输出。`score_type` 决定分数语义，评估层按语义分桶搜阈值。"""

    series_id: str
    scores: np.ndarray
    score_type: ScoreType
    is_anomaly: np.ndarray
    threshold: float
    detector: str
    elapsed_ms: float

    def __post_init__(self) -> None:
        if len(self.scores) != len(self.is_anomaly):
            raise ValueError("scores 与 is_anomaly 长度不一致")
