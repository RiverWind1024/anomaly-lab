"""人工反馈 → 告警阈值建议：闭环里的「优化」环节。

参考 AWS 的做法：

- **CloudWatch Anomaly Detection** 的告警反馈按**时间范围**提交，类型为
  Correct / False alarm / Missed，CloudWatch 据此自动调整 band 宽度与学习率。
- **Lookout for Metrics** 同样把「用户对异常的相关性反馈」回灌模型，持续提升准确率。

我们不做在线重训模型，只做一件更可控的事：**用反馈挑告警倍数**。
平台支持的检测器分数都是稳健 z 量纲，倍数就是「偏离基线多少倍正常波动」，
调倍数等价于调 band 宽度——和 AWS 调 band 宽度是同一件事。
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
class Suggestion:
    """基于反馈给出的倍数建议。"""

    current_multiplier: float
    suggested_multiplier: float
    reason: str
    current: ThresholdEvaluation | None
    best: ThresholdEvaluation | None
    candidates: list[ThresholdEvaluation] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "current_multiplier": self.current_multiplier,
            "suggested_multiplier": self.suggested_multiplier,
            "reason": self.reason,
            "current": self.current.as_dict() if self.current else None,
            "best": self.best.as_dict() if self.best else None,
            "candidates": [item.as_dict() for item in self.candidates],
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


def suggest_multiplier(
    outcomes: list[SeriesOutcome],
    annotations: list[Annotation],
    current_multiplier: float,
) -> Suggestion:
    """根据反馈给出新的告警倍数建议。

    目标函数按可用标签自适应：有正反例时最大化 F1；只有漏报时最大化召回；
    只有误报时最小化误报点数。**没有反馈就不给建议**，绝不猜。
    """
    usable = [
        note
        for note in annotations
        if note.kind in (_POSITIVE_KIND, _NEGATIVE_KIND)
    ]
    if not usable:
        return Suggestion(
            current_multiplier=float(current_multiplier),
            suggested_multiplier=float(current_multiplier),
            reason="还没有可用于评估的反馈（漏报/误报），暂不调整倍数",
            current=None,
            best=None,
        )
    scores = np.concatenate([item.scores for item in outcomes]) if outcomes else np.zeros(0)
    positive, negative = _build_labels(outcomes, usable)
    has_positive = bool(positive.any())
    has_negative = bool(negative.any())

    candidates = [
        _score_multiplier(scores, positive, negative, multiplier)
        for multiplier in candidate_multipliers(current_multiplier)
    ]
    current = next(
        (item for item in candidates if item.multiplier == float(current_multiplier)),
        None,
    )

    def objective(item: ThresholdEvaluation) -> tuple[float, float, float]:
        # 最后一项是「离当前倍数越近越好」：同等效果下取**最小干预**，
        # 避免一步把告警推到极端（AWS 的做法也是渐进调整而非一步到位）。
        distance = -abs(item.multiplier - float(current_multiplier))
        if has_positive and has_negative:
            return (item.f1 or 0.0, item.precision or 0.0, distance)
        if has_positive:
            return (item.recall or 0.0, item.precision or 0.0, distance)
        # 只有负例：告警越少越好
        return (-float(item.fp), item.precision or 0.0, distance)

    best = max(candidates, key=objective)
    suggested = best.multiplier
    if abs(suggested - current_multiplier) < 1e-9:
        reason = "当前倍数在已有反馈上已经最优，无需调整"
    elif suggested > current_multiplier:
        reason = (
            f"反馈显示误报偏多（precision={_fmt(best.precision)}），"
            f"建议把最低档倍数从 {current_multiplier:g} 调到 {suggested:g}（更保守）"
        )
    else:
        reason = (
            f"反馈显示漏报偏多（recall={_fmt(best.recall)}），"
            f"建议把最低档倍数从 {current_multiplier:g} 调到 {suggested:g}（更灵敏）"
        )
    if len(usable) < MIN_FEEDBACK_FOR_SUGGESTION:
        reason += f"；但只有 {len(usable)} 条反馈，样本偏少，建议再积累一些再定"
    return Suggestion(
        current_multiplier=float(current_multiplier),
        suggested_multiplier=float(suggested),
        reason=reason,
        current=current,
        best=best,
        candidates=candidates,
    )
