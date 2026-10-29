"""验证「自动推荐算法」在真实数据上的实际表现。

要回答的问题：**把 auto 设成默认，代价有多大？**

对每条带真值标签的序列：

- 用各检测器在**各自固定的默认阈值**下算点级 F1 与 point-adjusted F1
  ——这是平台实际用法（不是逐序列搜阈值的诊断上限，那种数字在真实部署里拿不到）；
- 记录 auto 选中的算法、它的 F1 排名（1 = 最好）与是否回退。

汇总成：各算法的平均 F1、auto 的平均排名与夺冠率、auto 相对「最好的固定算法」
和相对「固定用某个常见算法」的差距。

**为什么排名用 point-adjusted F1**：像 NAB 这类公开集的异常标注极其稀疏
（有的序列 4032 个点只标了 1 个异常），此时点级 F1 几乎只反映误报量，
无法区分「有没有抓到那个点」。point-adjusted 口径（窗口内命中一次即算检出）
才对应真实告警体验。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.evaluation.metrics import point_adjusted_prf, precision_recall_f1
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DETECTOR_FACTORIES,
    create_detector,
    resolve_detector,
)


@dataclass(frozen=True)
class SeriesResult:
    """一条序列上的各算法表现。"""

    series_id: str
    metric_class: str
    confidence: float
    auto_detector: str
    fallback: bool
    f1: dict[str, float] = field(default_factory=dict)
    adjusted_f1: dict[str, float] = field(default_factory=dict)
    ranks: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    """整体结论。

    `detector_mean_f1` 是**点级** F1；`detector_mean_adjusted_f1` 是
    **point-adjusted** F1（真值窗口内只要有一次命中就算整个窗口检出）——
    NAB 这类稀疏点级标注的公开集适用后者：4032 个点里只标 1 个异常时，
    点级 F1 几乎只反映误报量。
    """

    rows: list[SeriesResult]
    detector_mean_f1: dict[str, float]
    detector_mean_adjusted_f1: dict[str, float]
    auto_mean_f1: float
    auto_mean_adjusted_f1: float
    auto_mean_rank: float
    auto_top1_rate: float
    best_fixed_detector: str
    best_fixed_mean_f1: float
    baseline_detector: str
    baseline_mean_f1: float
    fallback_rate: float

    def as_dict(self) -> dict:
        return {
            "n_series": len(self.rows),
            "detector_mean_f1": self.detector_mean_f1,
            "detector_mean_adjusted_f1": self.detector_mean_adjusted_f1,
            "auto_mean_f1": self.auto_mean_f1,
            "auto_mean_adjusted_f1": self.auto_mean_adjusted_f1,
            "auto_mean_rank": self.auto_mean_rank,
            "auto_top1_rate": self.auto_top1_rate,
            "best_fixed_detector": self.best_fixed_detector,
            "best_fixed_mean_f1": self.best_fixed_mean_f1,
            "baseline_detector": self.baseline_detector,
            "baseline_mean_f1": self.baseline_mean_f1,
            "fallback_rate": self.fallback_rate,
        }


def _ranks(scores: dict[str, float]) -> dict[str, int]:
    """按 F1 降序排名，并列取相同名次（1 = 最好）。"""
    order = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ranks: dict[str, int] = {}
    previous_score: float | None = None
    previous_rank = 0
    for position, (name, score) in enumerate(order, start=1):
        if previous_score is not None and abs(score - previous_score) < 1e-12:
            ranks[name] = previous_rank
        else:
            ranks[name] = position
            previous_rank = position
        previous_score = score
    return ranks


def validate_auto(
    series_list: list[SeriesBundle],
    detectors: list[str] | None = None,
    baseline_detector: str = "iqr",
) -> ValidationReport:
    """在带真值的序列上验证 auto 推荐的质量。"""
    names = [
        name
        for name in (detectors or list(DETECTOR_FACTORIES))
        if name in DETECTOR_FACTORIES
    ]
    rows: list[SeriesResult] = []
    for series in series_list:
        if series.labels is None:
            continue
        truth = np.asarray(series.labels).astype(bool)
        if truth.sum() == 0:
            continue
        resolution = resolve_detector(AUTO_DETECTOR, series)
        f1: dict[str, float] = {}
        adjusted: dict[str, float] = {}
        for name in names:
            detector = create_detector(name).fit(series)
            result = detector.detect(series, threshold=detector.default_threshold)
            pred = np.asarray(result.is_anomaly).astype(bool)
            _, _, score = precision_recall_f1(pred, truth)
            _, _, adj = point_adjusted_prf(pred, truth)
            f1[name] = float(score)
            adjusted[name] = float(adj)
        rows.append(
            SeriesResult(
                series_id=series.series_id,
                metric_class=resolution.metric_class or "unknown",
                confidence=float(resolution.confidence or 0.0),
                auto_detector=resolution.detector,
                fallback=resolution.fallback,
                f1=f1,
                adjusted_f1=adjusted,
                # 排名按 point-adjusted F1：稀疏点级标注下点级 F1 几乎只反映误报量
                ranks=_ranks(adjusted),
            )
        )

    if not rows:
        raise ValueError("没有可用于验证的序列（需要带异常标签）")

    detector_mean_f1 = {
        name: float(np.mean([row.f1[name] for row in rows])) for name in names
    }
    detector_mean_adjusted = {
        name: float(np.mean([row.adjusted_f1[name] for row in rows])) for name in names
    }
    best_fixed = max(detector_mean_f1, key=lambda name: detector_mean_f1[name])
    auto_scores = [row.f1[row.auto_detector] for row in rows]
    auto_adjusted = [row.adjusted_f1[row.auto_detector] for row in rows]
    auto_ranks = [float(row.ranks[row.auto_detector]) for row in rows]
    baseline_scores = [row.f1.get(baseline_detector, 0.0) for row in rows]
    fallback_rate = float(np.mean([1.0 if row.fallback else 0.0 for row in rows]))
    return ValidationReport(
        rows=rows,
        detector_mean_f1=detector_mean_f1,
        detector_mean_adjusted_f1=detector_mean_adjusted,
        auto_mean_f1=float(np.mean(auto_scores)),
        auto_mean_adjusted_f1=float(np.mean(auto_adjusted)),
        auto_mean_rank=float(np.mean(auto_ranks)),
        auto_top1_rate=float(np.mean([1.0 if rank == 1.0 else 0.0 for rank in auto_ranks])),
        best_fixed_detector=best_fixed,
        best_fixed_mean_f1=detector_mean_f1[best_fixed],
        baseline_detector=baseline_detector,
        baseline_mean_f1=float(np.mean(baseline_scores)),
        fallback_rate=fallback_rate,
    )
