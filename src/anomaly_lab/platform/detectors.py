"""平台层支持的检测器注册表与「自动推荐」。

只有能给出「基线 + 双向上下界」的算法才进入平台：前端要展示基线，
没有上下界的算法（如变点检验）留在离线评测里使用。

这些检测器的分数统一是「稳健 z 分数」量纲（偏离基线多少倍尺度），
所以同一套倍数规则可以跨检测器通用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anomaly_lab.detectors.statistical import (
    DeseasonalizedIQRDetector,
    IQRDetector,
    MADDetector,
    SeasonalDetector,
    STLResidualDetector,
    ZScoreDetector,
)

DETECTOR_FACTORIES = {
    "iqr": IQRDetector,
    "mad": MADDetector,
    "zscore": ZScoreDetector,
    "seasonal": SeasonalDetector,
    "stl_residual": lambda: STLResidualDetector(period=24),
    "deseasonalized_iqr": DeseasonalizedIQRDetector,
}

#: 任务可以填 auto：运行时按序列形态自动推断检测器
AUTO_DETECTOR = "auto"

#: auto 推断不出可用候选时的兜底检测器（最通用）
DEFAULT_DETECTOR = "iqr"

#: 低于这个点数不做形态推断（特征不可靠）
MIN_AUTO_POINTS = 30


@dataclass(frozen=True)
class DetectorResolution:
    """一条序列实际用了哪个检测器，以及为什么。

    `fallback` 表示没有按推荐结果走（推断不可靠或推荐的平台不支持），
    这种情况下 `rationale` 会说明原因，不静默降级。
    """

    detector: str
    requested: str
    metric_class: str | None = None
    confidence: float | None = None
    reasons: list[str] = field(default_factory=list)
    rationale: str = ""
    fallback: bool = False

    def as_dict(self) -> dict:
        return {
            "detector": self.detector,
            "requested": self.requested,
            "metric_class": self.metric_class,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "rationale": self.rationale,
            "fallback": self.fallback,
        }


def create_detector(name: str):
    try:
        factory = DETECTOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"不支持的检测器: {name}") from exc
    return factory()


def resolve_detector(requested: str, series) -> DetectorResolution:
    """决定这条序列用哪个检测器。

    `requested` 是具体算法名时直接用它；是 `auto` 时按形态分类推荐，
    推荐里平台不支持的算法会被跳过——并如实记录，不静默换掉。
    """
    if requested != AUTO_DETECTOR:
        return DetectorResolution(detector=requested, requested=requested)
    n = len(series.values)
    if n < MIN_AUTO_POINTS:
        return DetectorResolution(
            detector=DEFAULT_DETECTOR,
            requested=requested,
            fallback=True,
            rationale=(
                f"点数 {n} 少于 {MIN_AUTO_POINTS}，形态推断不可靠，"
                f"用兜底算法 {DEFAULT_DETECTOR}"
            ),
        )
    # 延迟导入：分类器与检测器之间可能形成循环依赖
    from anomaly_lab.classification.classifier import classify

    result = classify(series)
    candidates = list(result.recommendation.detectors)
    supported = [name for name in candidates if name in DETECTOR_FACTORIES]
    unsupported = [name for name in candidates if name not in DETECTOR_FACTORIES]
    if supported:
        chosen = supported[0]
        fallback = False
    else:
        chosen = DEFAULT_DETECTOR
        fallback = True
    rationale = result.recommendation.rationale
    if unsupported:
        rationale = f"{rationale}；推荐中的 {'/'.join(unsupported)} 平台不支持"
    if fallback:
        rationale = f"{rationale}；无可用候选，回退到 {DEFAULT_DETECTOR}"
    return DetectorResolution(
        detector=chosen,
        requested=requested,
        metric_class=result.metric_class,
        confidence=result.confidence,
        reasons=list(result.reasons),
        rationale=rationale,
        fallback=fallback,
    )


def detector_catalog() -> list[dict]:
    """给前端用的检测器清单，含默认阈值。"""
    rows = [
        {
            "name": AUTO_DETECTOR,
            "default_threshold": float(
                create_detector(DEFAULT_DETECTOR).default_threshold
            ),
            "score_type": "auto",
            "label": "自动推荐（按形态推断）",
        }
    ]
    for name in DETECTOR_FACTORIES:
        detector = create_detector(name)
        rows.append(
            {
                "name": name,
                "default_threshold": float(detector.default_threshold),
                "score_type": detector.score_type,
                "label": name,
            }
        )
    return rows
