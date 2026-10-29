"""统计基线：IQR / MAD / ZScore，分数统一为“稳健 z 分数”。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.base import TimedDetector


class _WindowedDetector(TimedDetector):
    score_type = "zscore"

    def __init__(self, k: float, window: int | None = None) -> None:
        self.k = float(k)
        self.window = window
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> _WindowedDetector:
        return self

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._center_scale(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(values - center) / scale
        scores = np.where(np.isfinite(scores), scores, 0.0)
        return scores

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


def _rolling_quantile(values: np.ndarray, window: int, q: float) -> np.ndarray:
    series = pd.Series(values)
    # shift(1) 保证当前点不参与自身基线，避免异常点抬高自身阈值
    return series.rolling(window=window, min_periods=window).quantile(q).shift(1).to_numpy()


class IQRDetector(_WindowedDetector):
    """|x - median| / IQR，阈值即经典 IQR 围栏倍数。"""

    name = "iqr"

    def __init__(self, k: float = 2.5, window: int | None = None) -> None:
        super().__init__(k=k, window=window)

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.window is None:
            center = np.full_like(values, np.median(values))
            q1, q3 = np.percentile(values, [25, 75])
            scale = np.full_like(values, q3 - q1)
        else:
            center = _rolling_quantile(values, self.window, 0.5)
            scale = _rolling_quantile(values, self.window, 0.75) - _rolling_quantile(
                values, self.window, 0.25
            )
        return center, np.where(scale > 0, scale, np.nan)


class MADDetector(_WindowedDetector):
    """|x - median| / (1.4826 * MAD)。"""

    name = "mad"

    def __init__(self, k: float = 3.5, window: int | None = None) -> None:
        super().__init__(k=k, window=window)

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.window is None:
            center = np.full_like(values, np.median(values))
            mad = np.median(np.abs(values - np.median(values))) * 1.4826
            scale = np.full_like(values, mad)
        else:
            center = _rolling_quantile(values, self.window, 0.5)
            abs_dev = np.abs(values - center)
            scale = (
                pd.Series(abs_dev)
                .rolling(window=self.window, min_periods=self.window)
                .median()
                .shift(1)
                .to_numpy()
                * 1.4826
            )
        scale = np.where(scale > 0, scale, np.nan)
        return center, scale


class ZScoreDetector(_WindowedDetector):
    """经典 z 分数：|x - mean| / std。"""

    name = "zscore"

    def __init__(self, k: float = 3.0, window: int | None = None) -> None:
        super().__init__(k=k, window=window)

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.window is None:
            center = np.full_like(values, float(np.mean(values)))
            scale = np.full_like(values, float(np.std(values)))
        else:
            rolling = pd.Series(values).rolling(
                window=self.window, min_periods=self.window
            )
            center = rolling.mean().shift(1).to_numpy()
            scale = rolling.std(ddof=0).shift(1).to_numpy()
        return center, np.where(scale > 0, scale, np.nan)
