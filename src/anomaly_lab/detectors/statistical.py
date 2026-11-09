"""统计基线：IQR / MAD / ZScore，分数统一为“稳健 z 分数”。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.bands import Bands
from anomaly_lab.detectors.base import TimedDetector
from anomaly_lab.detectors.period import detect_period, usable_period
from anomaly_lab.detectors.robust import winsorize
from anomaly_lab.detectors.scale import majority_source, numeric_floor, pick_scale

#: 周期拿不准时的兜底值（点数）
DEFAULT_PERIOD = 24

#: 尺度来源的「降级程度」：数值越大越差。季节性的最终来源取最差的一档。
_SOURCE_RANK = {"mad": 0, "std": 1, "none": 2}


def _worse(a: str, b: str) -> str:
    """两档来源里更差的那个（mad < std < none）。"""
    return a if _SOURCE_RANK[a] >= _SOURCE_RANK[b] else b


class _WindowedDetector(TimedDetector):
    """|x - center| / scale 型检测器的公共骨架（IQR / MAD / ZScore）。"""

    score_type = "zscore"
    #: 降级链的起点（iqr / mad / std）
    prefer_scale = "iqr"

    def __init__(self, k: float, window: int | None = None, floor: float | None = None) -> None:
        self.k = float(k)
        self.window = window
        #: 数值噪声下限；None = 按输入值量级自动计算（见 `numeric_floor`）
        self.floor = floor
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> _WindowedDetector:
        return self

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """返回 `(center, scale)`；**同时**把尺度来源写进 `_last_scale_source`。

        ⚠️ IQR 与 MAD 只差 `prefer_scale`，所以实现在基类 ——
           两份拷贝将来改候选（比如加一档）必然漂移。
        """
        if self.window is None:
            med = float(np.median(values))
            center = np.full_like(values, med)
            cand = {
                "iqr": np.full_like(
                    values,
                    float(np.percentile(values, 75))
                    - float(np.percentile(values, 25)),
                ),
                "mad": np.full_like(values, float(np.median(np.abs(values - med))) * 1.4826),
                "std": np.full_like(values, float(np.std(values))),
            }
        else:
            center = _rolling_quantile(values, self.window, 0.5)
            cand = {
                "iqr": _rolling_quantile(values, self.window, 0.75)
                - _rolling_quantile(values, self.window, 0.25),
                "mad": _rolling_mad(values, self.window),
                "std": _rolling_std(values, self.window),
            }
        scale, source = pick_scale(
            prefer=self.prefer_scale,
            candidates=cand,
            floor=numeric_floor(values) if self.floor is None else self.floor,
        )
        self._last_scale_source = majority_source(source)
        return center, scale

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._center_scale(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(values - center) / scale
        # NaN 仍然写 0（保持既有分数语义），但 `status` 由 `_last_scale_source` 决定，
        # 所以「算不出来」不会被当成「一切正常」。
        return np.where(np.isfinite(scores), scores, 0.0)

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


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    # ⚠️ ddof=0 必须与整段的 `np.std` 一致，否则正常数据的分数会变
    return (
        pd.Series(values).rolling(window, min_periods=window)
        .std(ddof=0).shift(1).to_numpy()
    )


def _rolling_mad(values: np.ndarray, window: int) -> np.ndarray:
    med = _rolling_quantile(values, window, 0.5)
    abs_dev = np.abs(values - med)
    return (
        pd.Series(abs_dev).rolling(window, min_periods=window)
        .median().shift(1).to_numpy() * 1.4826
    )


class IQRDetector(_WindowedDetector):
    """|x - median| / IQR，阈值即经典 IQR 围栏倍数。"""

    name = "iqr"
    prefer_scale = "iqr"

    def __init__(self, k: float = 2.5, window: int | None = None, floor: float | None = None) -> None:
        super().__init__(k=k, window=window, floor=floor)


class MADDetector(_WindowedDetector):
    """|x - median| / (1.4826 * MAD)。"""

    name = "mad"
    prefer_scale = "mad"

    def __init__(self, k: float = 3.5, window: int | None = None) -> None:
        super().__init__(k=k, window=window)


class ZScoreDetector(_WindowedDetector):
    """经典 z 分数：|x - mean| / std。"""

    name = "zscore"
    prefer_scale = "std"

    def __init__(self, k: float = 3.0, window: int | None = None) -> None:
        super().__init__(k=k, window=window)

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.window is None:
            center = np.full_like(values, float(np.mean(values)))
            std_values = np.full_like(values, float(np.std(values)))
        else:
            rolling = pd.Series(values).rolling(
                window=self.window, min_periods=self.window
            )
            center = rolling.mean().shift(1).to_numpy()
            std_values = rolling.std(ddof=0).shift(1).to_numpy()
        # ZScore 只提供 std —— 不能因为链里有 iqr 就 KeyError
        scale, source = pick_scale(
            prefer=self.prefer_scale,
            candidates={"std": std_values},
            floor=numeric_floor(values),
        )
        self._last_scale_source = majority_source(source)
        return center, scale


class SeasonalDetector(TimedDetector):
    """按周期相位分组，用该相位的中位数/MAD 做稳健标准化。"""

    name = "seasonal"
    score_type = "zscore"
    default_threshold = 2.5
    #: 相位组内首选 MAD；退化到全局 std 时 `scale_fallback` 才能看出来
    prefer_scale = "mad"

    def __init__(self, period: int | None = None, k: float = 2.5) -> None:
        if period is not None and period <= 1:
            raise ValueError("period 必须大于 1")
        self.period = int(period) if period is not None else DEFAULT_PERIOD
        self._auto = period is None
        #: 是否真的做相位分组。周期不可信时为 False，退化成全局稳健统计。
        self.seasonal = True
        self.default_threshold = float(k)
        self._phase_cache: tuple | None = None

    def fit(self, series: SeriesBundle) -> SeasonalDetector:
        if self._auto:
            period = usable_period(series)
            if period is None:
                # 没有可信周期 → **不做**相位分组，退化成全局稳健统计。
                #
                # 猜一个周期再去分组只会造出混相位的基线，比不做季节性更糟：
                # 实测非周期序列被分到 250 个相位（每相位仅 2 个点）时，
                # 中位数与 MAD 都不稳定，F1 从 0.305 掉到 0.192。
                self.seasonal = False
                self.period = 0
            else:
                self.period = period
                self.seasonal = True
        return self

    def estimate_values(self, values: np.ndarray) -> np.ndarray:
        """相位中位数/MAD 本身就稳健，但小组时清洗更稳。

        注意：只有**估计**用清洗值，`score` 仍用原始值打分。
        """
        return winsorize(values)

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._phase_center_scale(values, self.estimate_values(values))
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(values - center) / scale
        return np.where(np.isfinite(scores), scores, 0.0)

    def _phase_center_scale(
        self, values: np.ndarray, estimate: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """按相位分组求中位数与 MAD。

        `estimate` 是清洗后的值，用来做**估计**（中位数与尺度）；
        打分仍用原始 `values`，异常点不会被洗掉。

        组内尺度为 0（该相位的值完全相同）时，退到**全局尺度**兜底，
        而不是留空——留空会让基线与上下界变成 NaN。完全确定的周期
        是理想情况，不该让整条曲线的基线失效。
        """
        if estimate is None:
            estimate = values
        n = len(values)
        if not self.seasonal:
            # 无季节性模式：全局中位数 + 全局 MAD（等价于一个稳健检测器）
            median = float(np.median(estimate))
            single_scale, source = self._global_scale(estimate)
            center = np.full(n, median)
            scale_arr = np.full(n, single_scale) if single_scale > 0 else np.zeros(n)
            self._last_scale_source = source
            self._phase_cache = (values.copy(), center, scale_arr, source)
            return center, scale_arr
        cached = self._phase_cache
        if cached is not None and np.array_equal(cached[0], values):
            # ⚠️ 缓存命中时也必须恢复来源 —— `_timed_detect` 每次都会先清空
            self._last_scale_source = cached[3]
            return cached[1], cached[2]
        center = np.full(n, np.nan)
        scale = np.full(n, np.nan)
        phases = np.arange(n) % self.period
        floor = numeric_floor(values)
        global_scale, global_source = self._global_scale(estimate)
        worst = "mad"                       # 相位组正常时用的是组内 MAD
        filled = False                      # 是否至少填过一组
        for phase in range(self.period):
            mask = phases == phase
            if mask.sum() < 2:
                continue
            group = estimate[mask]
            med = float(np.median(group))
            mad = float(np.median(np.abs(group - med))) * 1.4826
            if mad <= floor:
                # ⚠️ 组内值完全相同时 `np.std` 会因求和舍入返回**正的噪声**，
                #    不能只看 `<= 0`，否则会把浮点噪声当真实尺度。
                std = float(np.std(group))
                if std > floor:
                    mad = std
                    worst = _worse(worst, "std")
                else:
                    mad = 0.0
            if mad <= 0:
                # 组内完全确定：用一个正的尺度兜底，避免除零与 NaN
                mad = global_scale
                worst = _worse(worst, global_source)
            if mad <= 0:
                continue
            center[mask] = med
            scale[mask] = mad
            filled = True
        source = worst if filled else "none"
        self._last_scale_source = source
        self._phase_cache = (values.copy(), center, scale, source)
        return center, scale

    def _global_scale(self, values: np.ndarray) -> tuple[float, str]:
        """全局稳健尺度，作为相位组内尺度退化时的兜底。"""
        if len(values) == 0:
            return 0.0, "none"
        floor = numeric_floor(values)
        mad = float(np.median(np.abs(values - np.median(values)))) * 1.4826
        if mad > floor:
            return mad, "mad"
        std = float(np.std(values))
        if std > floor:
            return std, "std"
        return 0.0, "none"

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
    #: 残差首选 MAD；退化到 std 时 `scale_fallback` 才能看出来
    prefer_scale = "mad"

    def __init__(self, period: int | None = None, k: float = 3.5) -> None:
        if period is not None and period <= 1:
            raise ValueError("period 必须大于 1")
        self.period = int(period) if period is not None else DEFAULT_PERIOD
        self._auto = period is None
        self.default_threshold = float(k)
        self._residual_cache: tuple | None = None

    def fit(self, series: SeriesBundle) -> STLResidualDetector:
        if self._auto:
            # fallback 传 None = 按时间回退（见 period.default_fallback_period）
            self.period = detect_period(series)
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, abs_resid, mad = self._residual_parts(values, self.estimate_values(values))
        if mad <= 0:
            # 常数序列的残差只有浮点噪声 —— 不能当成「一切正常」
            self._last_status = "undetermined"
            return np.zeros_like(values)
        self._last_status = "ok"
        return abs_resid / mad

    def estimate_values(self, values: np.ndarray) -> np.ndarray:
        """STL 分解是最小二乘拟合——尖峰会把拟合曲线拉偏。

        所以**分解用清洗值**，而**残差仍用原始值**：
        异常点必须留在残差里，否则检测器就看不见它了。
        """
        return winsorize(values)

    def _residual_parts(
        self, values: np.ndarray, estimate: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray, float]:
        """返回 (拟合曲线, 残差绝对值, 残差尺度)。结果会缓存，score 与 bands 共用。"""
        # ⚠️ 输入本身没有可分辨的波动（传感器卡死、指标恒为常数）时，
        #    STL 的残差全是浮点噪声 —— 长序列上这些噪声会超过 numeric_floor，
        #    被当成真实尺度，报出一堆假告警。
        #    这里直接判「没有结构」，而不是把 floor 调大（调大 fence 会误伤真实小波动）。
        if np.ptp(values) <= numeric_floor(values):
            self._last_scale_source = "none"
            self._last_status = "undetermined"
            zeros = np.zeros_like(values)
            return zeros, zeros, 0.0
        cached = self._residual_cache
        if cached is not None and np.array_equal(cached[0], values):
            # ⚠️ 缓存命中时也必须恢复来源（`_timed_detect` 每次都会先清空）
            self._last_scale_source = cached[4]
            return cached[1], cached[2], cached[3]
        from statsmodels.tsa.seasonal import STL

        if estimate is None:
            estimate = values
        fit = STL(estimate, period=self.period, robust=True).fit()
        fitted = np.asarray(fit.trend + fit.seasonal, dtype=float)
        # 残差用原始值算：异常点必须体现在残差里
        abs_resid = np.abs(values - fitted)
        # ⚠️ 数值噪声下限要按**原始值**的量级算：常数序列的残差是 1e-16，
        #    按残差自身量级算下限会把它当成真实尺度。
        floor = numeric_floor(values)
        mad = float(np.median(np.abs(abs_resid - np.median(abs_resid)))) * 1.4826
        if mad > floor:
            source = "mad"
        else:
            mad = float(np.std(abs_resid))
            if mad > floor:
                source = "std"
            else:
                # ⚠️ 1e-16 的尺度会把数值噪声放大成假告警
                mad = 0.0
                source = "none"
        self._last_scale_source = source
        self._residual_cache = (values.copy(), fitted, abs_resid, mad, source)
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


class TrendResidualIQRDetector(TimedDetector):
    """先去线性趋势，再对残差跑 IQR。

    ⚠️ **旧名 `deseasonalized_iqr` 已改名** —— 那个名字说的是「去季节化」，
       做的却是「去**趋势**」。名不副实会让人以为它在处理季节性，
       于是想找「趋势」时 grep 不到它。
       旧名仍可用（见 `platform/detectors.py` 的 `DETECTOR_ALIASES`），
       历史评测产物里的记录也照常显示。

    ⚠️ **趋势线用清洗值估** —— 最小二乘会被尖峰拉偏
       （一次大幅尖峰就能把整条趋势线拽歪，剩下的点全变成「残差」）。
       估趋势时先 `winsorize`，但**打分仍用原始值** ——
       异常点必须留在残差里，否则检测器就看不见它了。
    """

    name = "trend_residual_iqr"
    score_type = "zscore"
    default_threshold = 2.5
    #: 残差交给内部 IQRDetector，首选尺度自然是 iqr
    prefer_scale = "iqr"

    def __init__(self, k: float = 2.5) -> None:
        self.k = float(k)
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> TrendResidualIQRDetector:
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, residuals = self._trend_and_residual(values)
        # ⚠️ 留着引用才能拿到内层实例记录的尺度来源
        # ⚠️ 数值噪声下限按**原始值**量级算：常数序列去趋势后残差是 1e-16，
        #    按残差自身量级算下限会把它当成真实尺度。
        inner = IQRDetector(k=self.k, floor=numeric_floor(values))
        scores = inner.score(
            SeriesBundle(
                series_id=series.series_id,
                values=residuals,
                timestamps=series.timestamps,
                freq=series.freq,
            )
        )
        self._last_scale_source = inner._last_scale_source
        return scores

    def _trend_and_residual(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        t = np.arange(len(values), dtype=float)
        # ⚠️ 趋势用**清洗值**估，残差用**原始值**
        slope, intercept = np.polyfit(t, winsorize(values), 1)
        trend = slope * t + intercept
        return trend, values - trend

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        trend, residuals = self._trend_and_residual(values)
        center, scale = IQRDetector(k=self.k, floor=numeric_floor(values))._center_scale(
            residuals
        )
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


#: 旧类名 → 新类名。
#:
#: ⚠️ 保留它是为了**不打断已有导入**（`from ... import DeseasonalizedIQRDetector`）。
#:    新代码请用 `TrendResidualIQRDetector`。
DeseasonalizedIQRDetector = TrendResidualIQRDetector


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

        # ⚠️ `_timed_detect` 会在调用 score() 前清空尺度来源，这里必须重写
        self._last_scale_source = "poisson"

        values = np.asarray(series.values, dtype=float)
        nonzero = (values != 0).astype(float)
        # ⚠️ 窗口必须是**因果**的：t 点只看 t-w+1…t。
        #    用 `center=True` 会把 t+1…t+w/2 算进来 —— 离线评估虚高，
        #    上线后最后 w/2 点行为不一致。
        counts = (
            pd.Series(nonzero)
            .rolling(window=self.window, min_periods=1)
            .sum()
            .to_numpy()
        )
        effective = (
            pd.Series(nonzero)
            .rolling(window=self.window, min_periods=1)
            .count()
            .to_numpy()
        )
        # ⚠️ λ 必须是因果的：只用**当前点之前**的数据。
        #    前两个点没有足够历史（min_periods=2 + shift(1)）→ 无法判断，
        #    分数给 0，绝不能用全序列均值兜底（那是未来数据）。
        history = (
            pd.Series(nonzero).expanding(min_periods=2).mean().shift(1).to_numpy()
        )
        known = np.isfinite(history)
        rate = np.where(known, history, 1.0)
        scores = poisson.cdf(counts - 1, np.maximum(rate * effective, 1e-6))
        # ⚠️ 只在**当前点本身就是事件**时才报。
        #    否则一次 5 连事件会让它后面 5 个 0 值点都报满分，
        #    用户看到的是「0 次 / 分数 1.0」的告警 —— 那是窗口的尾巴，不是异常点。
        scores = np.where(nonzero > 0, scores, 0.0)
        return np.where(known, scores, 0.0)

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)
