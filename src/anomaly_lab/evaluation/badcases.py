"""Bad Case 归因：误报/漏报按位置、形态、分数分布、连续性给出可读原因。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.contracts import DetectionResult, SeriesBundle


@dataclass(frozen=True, eq=False)
class BadCase:
    series_id: str
    kind: str
    group: str
    reason: str
    indices: list[int]


def _segments(mask: np.ndarray) -> list[tuple[int, int]]:
    mask = np.asarray(mask).astype(bool)
    padded = np.concatenate([[False], mask, [False]])
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:]) - 1
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def _position(start: int, n: int) -> str:
    ratio = start / max(1, n - 1)
    if ratio <= 0.1:
        return "前10%"
    if ratio >= 0.9:
        return "后10%"
    return "中段"


def attribute_badcases(
    series: SeriesBundle, result: DetectionResult
) -> list[BadCase]:
    labels = np.asarray(series.labels).astype(bool)
    pred = np.asarray(result.is_anomaly).astype(bool)
    scores = np.asarray(result.scores, dtype=float)
    n = len(pred)
    metric_class = str(series.meta.get("metric_class", "unknown"))
    cases: list[BadCase] = []

    def _make(kind: str, start: int, end: int) -> BadCase:
        indices = list(range(start, end + 1))
        position = _position(start, n)
        continuity = "连续段" if end > start else "孤立点"
        point_score = float(scores[start])
        percentile = float((scores <= point_score).mean() * 100)
        if kind == "false_positive":
            reason = (
                f"误报：形态={metric_class}，位置={position}，{continuity}，"
                f"分数 {point_score:.2f} 处于该序列 {percentile:.0f}% 分位"
            )
        else:
            reason = (
                f"漏报：形态={metric_class}，位置={position}，{continuity}，"
                f"真值点分数仅 {point_score:.2f}（{percentile:.0f}% 分位），分数不够高"
            )
        group = f"{metric_class}/{position}/{continuity}"
        return BadCase(series.series_id, kind, group, reason, indices)

    for start, end in _segments(pred & ~labels):
        cases.append(_make("false_positive", start, end))
    for start, end in _segments(~pred & labels):
        cases.append(_make("false_negative", start, end))
    return cases
