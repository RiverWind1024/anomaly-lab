"""统计基线：IQR / MAD / ZScore，分数统一为“稳健 z 分数”。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.bands import Bands
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

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._center_scale(values)
        return Bands(
            baseline=center,
            lower=center - float(threshold) * scale,
            upper=center + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )


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


class SeasonalDetector(TimedDetector):
    """按周期相位分组，用该相位的中位数/MAD 做稳健标准化。"""

    name = "seasonal"
    score_type = "zscore"
    default_threshold = 2.5

    def __init__(self, period: int | None = None, k: float = 2.5) -> None:
        if period is not None and period <= 1:
            raise ValueError("period 必须大于 1")
        self.period = int(period) if period is not None else 24
        self._auto = period is None
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> SeasonalDetector:
        if self._auto:
            from anomaly_lab.classification.features import extract_features

            detected = extract_features(series.values).dominant_period
            self.period = int(detected) if detected else 24
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._phase_center_scale(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(values - center) / scale
        return np.where(np.isfinite(scores), scores, 0.0)

    def _phase_center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """按相位分组求中位数与 MAD；样本不足或尺度为 0 的相位留空。"""
        n = len(values)
        center = np.full(n, np.nan)
        scale = np.full(n, np.nan)
        phases = np.arange(n) % self.period
        for phase in range(self.period):
            mask = phases == phase
            if mask.sum() < 2:
                continue
            group = values[mask]
            med = float(np.median(group))
            mad = float(np.median(np.abs(group - med))) * 1.4826
            if mad <= 0:
                mad = float(np.std(group))
            if mad <= 0:
                continue
            center[mask] = med
            scale[mask] = mad
        return center, scale

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._phase_center_scale(values)
        return Bands(
            baseline=center,
            lower=center - float(threshold) * scale,
            upper=center + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


class STLResidualDetector(TimedDetector):
    """STL 分解后的残差绝对值 / 残差 MAD。"""

    name = "stl_residual"
    score_type = "residual_ratio"
    default_threshold = 3.5

    def __init__(self, period: int, k: float = 3.5) -> None:
        if period <= 1:
            raise ValueError("period 必须大于 1")
        self.period = int(period)
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> STLResidualDetector:
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, abs_resid, mad = self._residual_parts(values)
        if mad <= 0:
            return np.zeros_like(values)
        return abs_resid / mad

    def _residual_parts(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        """返回 (拟合曲线, 残差绝对值, 残差尺度)。"""
        from statsmodels.tsa.seasonal import STL

        fit = STL(values, period=self.period, robust=True).fit()
        fitted = np.asarray(fit.trend + fit.seasonal, dtype=float)
        abs_resid = np.abs(values - fitted)
        mad = float(np.median(np.abs(abs_resid - np.median(abs_resid)))) * 1.4826
        if mad <= 0:
            mad = float(np.std(abs_resid))
        return fitted, abs_resid, mad

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        fitted, _, mad = self._residual_parts(values)
        scale = np.full_like(values, mad)
        return Bands(
            baseline=fitted,
            lower=fitted - float(threshold) * scale,
            upper=fitted + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


class DeseasonalizedIQRDetector(TimedDetector):
    """先去线性趋势，再对残差跑 IQR。"""

    name = "deseasonalized_iqr"
    score_type = "zscore"
    default_threshold = 2.5

    def __init__(self, k: float = 2.5) -> None:
        self.k = float(k)
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> DeseasonalizedIQRDetector:
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, residuals = self._trend_and_residual(values)
        return IQRDetector(k=self.k).score(
            SeriesBundle(
                series_id=series.series_id,
                values=residuals,
                timestamps=series.timestamps,
                freq=series.freq,
            )
        )

    def _trend_and_residual(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        t = np.arange(len(values), dtype=float)
        slope, intercept = np.polyfit(t, values, 1)
        trend = slope * t + intercept
        return trend, values - trend

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        trend, residuals = self._trend_and_residual(values)
        center, scale = IQRDetector(k=self.k)._center_scale(residuals)
        baseline = trend + center
        return Bands(
            baseline=baseline,
            lower=baseline - float(threshold) * scale,
            upper=baseline + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


class ChangePointDetector(TimedDetector):
    """滑窗双样本 t 检验，score = 1 - p 值。"""

    name = "changepoint"
    score_type = "prob"
    default_threshold = 0.99

    def __init__(self, min_seg: int = 20, threshold: float = 0.99) -> None:
        if min_seg < 3:
            raise ValueError("min_seg 至少为 3")
        self.min_seg = int(min_seg)
        self.default_threshold = float(threshold)

    def fit(self, series: SeriesBundle) -> ChangePointDetector:
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        from scipy.stats import ttest_ind

        values = np.asarray(series.values, dtype=float)
        n = len(values)
        scores = np.zeros(n)
        w = self.min_seg
        for cut in range(w, n - w + 1):
            left = values[cut - w : cut]
            right = values[cut : cut + w]
            result = ttest_ind(left, right, equal_var=False)
            pvalue = float(result.pvalue)
            scores[cut] = 0.0 if not np.isfinite(pvalue) else 1.0 - pvalue
        return scores

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


class EventCountDetector(TimedDetector):
    """滑动窗口非零事件数 vs 泊松基线，score = P(基线事件数 < 实际计数)。"""

    name = "event_count"
    score_type = "prob"
    default_threshold = 0.99

    def __init__(self, window: int = 50, threshold: float = 0.99) -> None:
        if window < 2:
            raise ValueError("window 至少为 2")
        self.window = int(window)
        self.default_threshold = float(threshold)

    def fit(self, series: SeriesBundle) -> EventCountDetector:
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        from scipy.stats import poisson

        values = np.asarray(series.values, dtype=float)
        nonzero = (values != 0).astype(float)
        counts = (
            pd.Series(nonzero)
            .rolling(window=self.window, center=True, min_periods=1)
            .sum()
            .to_numpy()
        )
        lam = max(1e-6, float(nonzero.mean()) * self.window)
        return poisson.cdf(counts - 1, lam)

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)
