"""人工反馈 → 算法与阈值建议：闭环里的「优化」环节。

参考 AWS 的做法：

- **CloudWatch Anomaly Detection** 的告警反馈按**时间范围**提交，类型为
  Correct / False alarm / Missed，CloudWatch 据此自动调整 band 宽度与学习率。
- **Lookout for Metrics** 同样把「用户对异常的相关性反馈」回灌模型，持续提升准确率。

我们不做在线重训模型，只做一件更可控的事：**用反馈挑「用哪个算法 + 用哪个倍数」**。
平台支持的检测器分数都是稳健 z 量纲，倍数就是「偏离基线多少倍正常波动」，
调倍数等价于调 band 宽度——和 AWS 调 band 宽度是同一件事；而当误报来自
「这条序列本来就不适合这个算法」时，换算法比调倍数更对症。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: 反馈类型：`missed` = 该报没报；`false_alarm` = 不该报却报了；其余不参与调参
FEEDBACK_KINDS = {"correct", "false_alarm", "missed", "other"}

#: 参与评估的区间类型：正例（该报）与负例（不该报）
_POSITIVE_KIND = "missed"
_NEGATIVE_KIND = "false_alarm"

#: 倍数的合理范围：低于 0.1 几乎任何偏离都告警，高于 20 基本不告警
MIN_MULTIPLIER = 0.1
MAX_MULTIPLIER = 20.0

#: 绝对候选网格：保证当前倍数很大/很小时仍能覆盖到有意义的取值
_ABSOLUTE_GRID = (
    0.1,
    0.2,
    0.3,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    3.0,
    5.0,
    7.5,
    10.0,
    15.0,
    20.0,
)

#: 相对候选网格：以当前倍数为中心上下浮动
_RELATIVE_FACTORS = (
    0.05,
    0.1,
    0.2,
    0.3,
    0.4,
    0.55,
    0.7,
    0.85,
    1.0,
    1.2,
    1.5,
    2.0,
    3.0,
)


#: 反馈少于这个数量时，建议仅供参考（样本太少容易过拟合到个别区间）
MIN_FEEDBACK_FOR_SUGGESTION = 3


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


@dataclass(frozen=True)
class Annotation:
    """一条反馈（时间范围级）。"""

    series_id: str
    start_ts: str
    end_ts: str
    kind: str


@dataclass(frozen=True)
class SeriesOutcome:
    """一条序列的检测输出摘要；评估只需要时间与分数。"""

    series_id: str
    timestamps: np.ndarray
    scores: np.ndarray


@dataclass(frozen=True)
class ThresholdEvaluation:
    """某个告警倍数下的表现。

    `precision` 需要负例（不该报却报了）才能评估，`recall` 需要正例（该报没报）
    才能评估——缺一侧时是 `None` 而不是 1.0，否则「没有正例」会被误读成「完美」。
    """

    multiplier: float
    precision: float | None
    recall: float | None
    f1: float | None
    tp: int
    fp: int
    tn: int
    fn: int

    def as_dict(self) -> dict:
        return {
            "multiplier": self.multiplier,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
        }


@dataclass(frozen=True)
class SettingSuggestion:
    """基于反馈给出的「算法 + 倍数」建议。

    反馈既能说明**阈值**不合适（误报多就调保守），也能说明**算法**不合适
    （这条序列用 seasonal 一直吵，换个算法就安静了）——所以建议里两者都管。
    """

    current_detector: str
    suggested_detector: str
    current_multiplier: float
    suggested_multiplier: float
    reason: str
    current: ThresholdEvaluation | None
    best: ThresholdEvaluation | None
    candidates: list[dict] = field(default_factory=list)

    @property
    def detector_changed(self) -> bool:
        return self.suggested_detector != self.current_detector

    def as_dict(self) -> dict:
        return {
            "current_detector": self.current_detector,
            "suggested_detector": self.suggested_detector,
            "detector_changed": self.detector_changed,
            "current_multiplier": self.current_multiplier,
            "suggested_multiplier": self.suggested_multiplier,
            "reason": self.reason,
            "current": self.current.as_dict() if self.current else None,
            "best": self.best.as_dict() if self.best else None,
            "candidates": self.candidates,
        }


def to_naive_ns(value: str) -> np.datetime64:
    """把 ISO 时间转成 naive UTC 的纳秒时间戳，便于和检测结果对齐。"""
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp.to_datetime64()


def normalize_ts(value: str) -> str:
    """规范化成统一格式的 naive UTC ISO 字符串。

    反馈要按时间范围存和比较，字符串比较只有在格式一致时才等价于时间比较，
    所以入库前统一规范化。
    """
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp.isoformat()


def candidate_multipliers(current: float) -> list[float]:
    """候选倍数网格 = 绝对网格 ∪ 围绕当前倍数的相对网格。

    两套都要：相对网格保证「小幅调整」总是可达，绝对网格保证当前倍数
    偏大或偏小时仍能覆盖到有意义的取值。
    """
    values = set(_ABSOLUTE_GRID)
    for factor in _RELATIVE_FACTORS:
        scaled = float(current) * factor
        values.add(round(min(max(scaled, MIN_MULTIPLIER), MAX_MULTIPLIER), 4))
    return sorted(values)


def _range_mask(
    timestamps: np.ndarray, start: np.datetime64, end: np.datetime64
) -> np.ndarray:
    return (timestamps >= start) & (timestamps <= end)


def _build_labels(
    outcomes: list[SeriesOutcome], annotations: list[Annotation]
) -> tuple[np.ndarray, np.ndarray]:
    """按反馈区间给每个点打「该报 / 不该报」的标签。"""
    total = sum(len(item.scores) for item in outcomes)
    positive = np.zeros(total, dtype=bool)
    negative = np.zeros(total, dtype=bool)
    offset = 0
    for outcome in outcomes:
        length = len(outcome.scores)
        for note in annotations:
            if note.series_id != outcome.series_id:
                continue
            mask = _range_mask(
                outcome.timestamps,
                to_naive_ns(note.start_ts),
                to_naive_ns(note.end_ts),
            )
            if note.kind == _POSITIVE_KIND:
                positive[offset : offset + length] |= mask
            elif note.kind == _NEGATIVE_KIND:
                negative[offset : offset + length] |= mask
        offset += length
    return positive, negative


def _score_multiplier(
    scores: np.ndarray, positive: np.ndarray, negative: np.ndarray, multiplier: float
) -> ThresholdEvaluation:
    alert = scores >= multiplier
    tp = int(np.count_nonzero(alert & positive))
    fn = int(np.count_nonzero(~alert & positive))
    fp = int(np.count_nonzero(alert & negative))
    tn = int(np.count_nonzero(~alert & negative))
    # 缺正例就没有 recall 可谈，缺负例就没有 precision 可谈——如实留空
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return ThresholdEvaluation(
        multiplier=float(multiplier),
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
    )


def suggest_setting(
    outcomes_by_detector: dict[str, list[SeriesOutcome]],
    annotations: list[Annotation],
    current_detector: str,
    current_multiplier: float,
) -> SettingSuggestion:
    """根据反馈给出「用哪个算法 + 用哪个倍数」的建议。

    对每个候选算法 × 候选倍数算一遍表现，再在全部组合里挑最优：

    - 目标函数按可用标签自适应：有正反例时最大化 F1；只有漏报时最大化召回；
      只有误报时最小化误报点数；
    - 同等效果时**优先不改算法**，其次**最小干预**（倍数离当前最近）——
      避免一步把配置推到极端（AWS 的做法也是渐进调整而非一步到位）。

    **没有反馈就不给建议**，绝不猜。
    """
    usable = [
        note
        for note in annotations
        if note.kind in (_POSITIVE_KIND, _NEGATIVE_KIND)
    ]
    if not usable:
        return SettingSuggestion(
            current_detector=current_detector,
            suggested_detector=current_detector,
            current_multiplier=float(current_multiplier),
            suggested_multiplier=float(current_multiplier),
            reason="还没有可用于评估的反馈（漏报/误报），暂不调整",
            current=None,
            best=None,
        )

    multipliers = candidate_multipliers(current_multiplier)
    candidates: list[dict] = []
    has_positive = False
    has_negative = False
    for detector, outcomes in outcomes_by_detector.items():
        if not outcomes:
            continue
        scores = np.concatenate([item.scores for item in outcomes])
        positive, negative = _build_labels(outcomes, usable)
        has_positive = has_positive or bool(positive.any())
        has_negative = has_negative or bool(negative.any())
        for multiplier in multipliers:
            evaluation = _score_multiplier(scores, positive, negative, multiplier)
            candidates.append({"detector": detector, **evaluation.as_dict()})

    if not candidates:
        return SettingSuggestion(
            current_detector=current_detector,
            suggested_detector=current_detector,
            current_multiplier=float(current_multiplier),
            suggested_multiplier=float(current_multiplier),
            reason="没有可用于评估的检测结果",
            current=None,
            best=None,
        )

    def objective(item: dict) -> tuple[float, float, float, float]:
        distance = -abs(item["multiplier"] - float(current_multiplier))
        same_detector = 1.0 if item["detector"] == current_detector else 0.0
        if has_positive and has_negative:
            return (item["f1"] or 0.0, item["precision"] or 0.0, same_detector, distance)
        if has_positive:
            return (item["recall"] or 0.0, item["precision"] or 0.0, same_detector, distance)
        # 只有负例：告警越少越好
        return (-float(item["fp"]), item["precision"] or 0.0, same_detector, distance)

    best_row = max(candidates, key=objective)
    suggested_detector = str(best_row["detector"])
    suggested_multiplier = float(best_row["multiplier"])
    current_row = next(
        (
            item
            for item in candidates
            if item["detector"] == current_detector
            and abs(item["multiplier"] - float(current_multiplier)) < 1e-9
        ),
        None,
    )
    best = ThresholdEvaluation(
        multiplier=suggested_multiplier,
        precision=best_row["precision"],
        recall=best_row["recall"],
        f1=best_row["f1"],
        tp=best_row["tp"],
        fp=best_row["fp"],
        tn=best_row["tn"],
        fn=best_row["fn"],
    )

    reason = _explain(
        current_detector=current_detector,
        suggested_detector=suggested_detector,
        current_multiplier=float(current_multiplier),
        suggested_multiplier=suggested_multiplier,
        best=best,
        current_row=current_row,
        detector_changed=suggested_detector != current_detector,
        n_feedback=len(usable),
    )
    return SettingSuggestion(
        current_detector=current_detector,
        suggested_detector=suggested_detector,
        current_multiplier=float(current_multiplier),
        suggested_multiplier=suggested_multiplier,
        reason=reason,
        current=(
            ThresholdEvaluation(
                multiplier=float(current_row["multiplier"]),
                precision=current_row["precision"],
                recall=current_row["recall"],
                f1=current_row["f1"],
                tp=current_row["tp"],
                fp=current_row["fp"],
                tn=current_row["tn"],
                fn=current_row["fn"],
            )
            if current_row
            else None
        ),
        best=best,
        candidates=candidates,
    )


def _explain(
    *,
    current_detector: str,
    suggested_detector: str,
    current_multiplier: float,
    suggested_multiplier: float,
    best: ThresholdEvaluation,
    current_row: dict | None,
    detector_changed: bool,
    n_feedback: int,
) -> str:
    """把建议写成一句人话，说明**为什么**。"""
    parts: list[str] = []
    if detector_changed:
        before = (
            f"F1 {current_row['f1']:.2f}"
            if current_row and current_row.get("f1") is not None
            else f"误报 {current_row['fp']} 个"
            if current_row
            else "当前表现不佳"
        )
        after = (
            f"F1 {best.f1:.2f}"
            if best.f1 is not None
            else f"误报 {best.fp} 个"
        )
        if current_detector == "auto":
            # auto 是「逐序列各选一个」的混合表现，不是单个算法
            parts.append(
                f"反馈显示自动选择（每条序列各挑一个算法）在这段区间上不合适"
                f"（{before}），建议把任务固定为 {suggested_detector}（{after}）"
            )
        else:
            parts.append(
                f"反馈显示这条序列更适合用 {suggested_detector} 而不是 {current_detector}"
                f"（{before} → {after}）"
            )
    elif abs(suggested_multiplier - current_multiplier) < 1e-9:
        parts.append("当前算法与倍数在已有反馈上已经最优，无需调整")
    elif suggested_multiplier > current_multiplier:
        parts.append(
            f"反馈显示误报偏多（precision={_fmt(best.precision)}），"
            f"建议把最低档倍数从 {current_multiplier:g} 调到 {suggested_multiplier:g}（更保守）"
        )
    else:
        parts.append(
            f"反馈显示漏报偏多（recall={_fmt(best.recall)}），"
            f"建议把最低档倍数从 {current_multiplier:g} 调到 {suggested_multiplier:g}（更灵敏）"
        )
    if n_feedback < MIN_FEEDBACK_FOR_SUGGESTION:
        parts.append(f"但只有 {n_feedback} 条反馈，样本偏少，建议再积累一些再定")
    return "；".join(parts)
