"""多算法对比：同一条序列用不同算法各跑一遍，看各自的基线与告警点。

用途是**选算法**时给用户对照：auto 推荐的算法到底比别的强在哪，
换掉它会多报还是少报。这只是探索，不产生告警、不落盘。

注意：各检测器的分数都是「偏离基线多少个尺度单位」，量纲一致，可以横向比较；
但**尺度本身的估计方式不同**（STL 残差的 MAD 通常远小于全局 MAD），
所以同一份数据在不同算法下分数量级可能差很多。对比表里的
`default_threshold` 就是解读这个差异的参照——它给出该算法「惯用」的倍数。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.detectors.bands import compute_bands
from anomaly_lab.platform.alerts import AlertRule, severity_from_conditions
from anomaly_lab.platform.detectors import create_detector


@dataclass(frozen=True)
class DetectorOutcome:
    """一个算法在这条序列上的结果。"""

    name: str
    score_type: str
    default_threshold: float
    baseline: np.ndarray | None
    lower: np.ndarray | None
    upper: np.ndarray | None
    scores: np.ndarray
    severity: np.ndarray
    n_alerts: int
    n_top: int

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score_type": self.score_type,
            "default_threshold": self.default_threshold,
            "baseline": self.baseline,
            "lower": self.lower,
            "upper": self.upper,
            "scores": self.scores,
            "severity": self.severity,
            "n_alerts": self.n_alerts,
            "n_top": self.n_top,
        }


def compare_series(
    series,
    detector_names: list[str],
    rules: list[AlertRule],
    band_width: float,
) -> list[DetectorOutcome]:
    """对一条序列依次跑各检测器，用同一套规则判定等级。"""
    outcomes: list[DetectorOutcome] = []
    top_level = len(rules)
    for name in detector_names:
        detector = create_detector(name).fit(series)
        result = detector.detect(series, threshold=band_width)
        bands = compute_bands(detector, series, band_width)
        severity = severity_from_conditions(result.scores, series.values, rules)
        outcomes.append(
            DetectorOutcome(
                name=name,
                score_type=result.score_type,
                default_threshold=float(detector.default_threshold),
                baseline=np.asarray(bands.baseline, dtype=float) if bands else None,
                lower=np.asarray(bands.lower, dtype=float) if bands else None,
                upper=np.asarray(bands.upper, dtype=float) if bands else None,
                scores=np.asarray(result.scores, dtype=float),
                severity=severity,
                n_alerts=int((severity > 0).sum()),
                n_top=int((severity == top_level).sum()),
            )
        )
    return outcomes
