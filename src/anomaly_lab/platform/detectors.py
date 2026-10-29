"""平台层支持的检测器注册表。

只有能给出「基线 + 双向上下界」的算法才进入平台：前端要展示基线，
没有上下界的算法（如变点检验）留在离线评测里使用。
"""

from __future__ import annotations

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


def create_detector(name: str):
    try:
        factory = DETECTOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"不支持的检测器: {name}") from exc
    return factory()


def detector_catalog() -> list[dict]:
    """给前端用的检测器清单，含默认阈值。"""
    rows = []
    for name in DETECTOR_FACTORIES:
        detector = create_detector(name)
        rows.append(
            {
                "name": name,
                "default_threshold": float(detector.default_threshold),
                "score_type": detector.score_type,
            }
        )
    return rows
