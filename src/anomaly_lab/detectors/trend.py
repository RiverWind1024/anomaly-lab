"""趋势型检测器：把趋势拆掉，再对残差做阈值判定。

⚠️ **为什么趋势型不能直接跑 IQR**：
    IQR 用的是**全局**分位数。序列在涨时，整体分布被拉宽 →
    四分位距变大 → 围栏跟着变宽 → 真正的突变点淹没在里面。
    实测（合成集 `trending-*`，真异常 28 点）：

    | 检测器 | 报出 | 命中真异常 |
    |---|---|---|
    | `iqr` | 2 | 2（漏掉 26 个） |
    | `trend_residual_iqr` | 16 | 16（全部命中） |

    所以趋势型序列必须**先去趋势，再判残差**。

⚠️ **趋势线怎么估，决定了能不能检出尖峰**：
    最小二乘（`polyfit`）会被离群点拉偏 —— 一次大幅尖峰就能把趋势线拽歪，
    剩下的点全变成「残差」。Theil-Sen 取的是**所有点对斜率的中位数**，
    少数点对的影响被中位数吃掉，尖峰拉不动它。

    这是 `stl_residual` 踩过的坑（它用 STL 的最小二乘拟合，
    在趋势序列上会报出上百个误报），这里不重复。

⚠️ **趋势用清洗值估，残差用原始值**：
    估趋势时把离群点裁掉（`winsorize`）→ 趋势线更稳；
    但**打分必须用原始值** —— 异常点必须留在残差里，
    否则检测器就看不见它了（见 `TimedDetector.estimate_values` 的约定）。
"""

from __future__ import annotations

import numpy as np

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.bands import Bands
from anomaly_lab.detectors.base import TimedDetector
from anomaly_lab.detectors.robust import winsorize

#: 估趋势线用的最大点数。
#:
#: ⚠️ Theil-Sen 是 O(n²) 的点对斜率 —— n=500 要算 12.5 万个斜率（几十毫秒），
#:    n=5000 就是 1250 万个（几秒 + 100 MB 内存）。
#:    超了就**等间隔抽样**估趋势线（斜率中位数在子样本上已经足够稳），
#:    残差仍然对**全部点**算 —— 抽样只影响「趋势线怎么估」，不影响「谁异常」。
MAX_TREND_POINTS = 1200


def theil_sen_trend(values: np.ndarray) -> np.ndarray:
    """Theil-Sen 稳健趋势线：逐点的中位数斜率 + 中位数截距。

    ⚠️ **斜率用点对斜率的中位数**（不是最小二乘）——
       少数离群点对只影响中位数，不影响整体斜率。
    ⚠️ **截距也用中位数** —— 与斜率配套，两者都是稳健统计量。
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n == 0:
        return values.copy()
    if n == 1:
        return values.copy()

    t = np.arange(n, dtype=float)
    if n > MAX_TREND_POINTS:
        # ⚠️ 抽样只用于**估斜率**；斜率估出来后，截距与残差都用全部点
        idx = np.linspace(0, n - 1, MAX_TREND_POINTS)
        t_fit = t[idx]
        y_fit = values[idx]
    else:
        t_fit = t
        y_fit = values

    # 点对斜率：上三角（i < j）
    i, j = np.triu_indices(len(t_fit), k=1)
    dx = t_fit[j] - t_fit[i]
    # ⚠️ dx 恒为正（j > i 且 t 单调），不会除零
    slopes = (y_fit[j] - y_fit[i]) / dx
    slope = float(np.median(slopes))
    intercept = float(np.median(y_fit - slope * t_fit))
    return slope * t + intercept


class TheilSenTrendDetector(TimedDetector):
    """Theil-Sen 趋势线 + 残差 MAD。

    分数 = `|残差| / 稳健尺度`（尺度单位），
    所以跟统计族共用同一套倍数阈值（2.5 / 3.75）。
    """

    name = "theil_sen"
    score_type = "zscore"
    #: 残差尺度首选 MAD（稳健）；退化时走 `scale.py` 的降级链
    prefer_scale = "mad"
    #: 默认阈值 **3.5**（不是统计族常看的 2.5）。
    #:
    #: ⚠️ 这是**实测出来的**，不是拍的 ——
    #:    合成集 20 条 trending 序列（真异常 609 点）扫阈值：
    #:
    #:    | k | 点级 F1 | 调整 F1 | 召回 | 精确率 |
    #:    |---|---|---|---|---|
    #:    | 2.5 | 0.609 | 0.710 | 55.5% | 73.3% |
    #:    | 3.0 | 0.649 | 0.765 | 54.2% | 91.1% |
    #:    | **3.5** | **0.650** | 0.752 | 52.9% | **98.3%** |
    #:
    #:    k=2.5 精确率只有 73%（每 4 个报出有 1 个是误报），
    #:    k=3.5 精确率 98.3% 而召回只掉 2.6 个百分点 —— 明显更划算。
    default_threshold = 3.5

    def __init__(self, k: float = 3.5) -> None:
        self.k = float(k)
        self.default_threshold = float(k)
        self._cache: tuple | None = None

    def fit(self, series: SeriesBundle) -> TheilSenTrendDetector:
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, residual, scale = self._parts(values)
        if scale <= 0:
            # 尺度不可判 —— 返回 0 分，由 `_last_status` 标出来
            self._last_status = "undetermined"
            return np.zeros_like(values)
        self._last_status = "ok"
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(residual) / scale
        return np.where(np.isfinite(scores), scores, 0.0)

    def _parts(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        """返回 (趋势线, 残差, 残差尺度)。结果缓存，score 与 bands 共用。"""
        cached = self._cache
        if cached is not None and np.array_equal(cached[0], values):
            # ⚠️ 缓存命中也要恢复尺度来源 —— `_timed_detect` 每次开始前都会清空它，
            #    否则同一个检测器重复检测同一条序列时 `scale_source` 会变成 None。
            self._last_scale_source = cached[4]
            return cached[1], cached[2], cached[3]

        from anomaly_lab.detectors.scale import numeric_floor, robust_scale

        # ⚠️ **趋势用清洗值估，残差用原始值** —— 异常点必须留在残差里
        trend = theil_sen_trend(winsorize(values))
        residual = values - trend

        # ⚠️ 输入本身没有可分辨的波动（死传感器 / 常数）：
        #    残差全是浮点噪声，不能当尺度 —— 否则会报一堆假告警。
        if np.ptp(values) <= numeric_floor(values):
            self._last_scale_source = "none"
            self._cache = (values.copy(), trend, residual, 0.0, "none")
            return trend, residual, 0.0

        est = robust_scale(residual, prefer="mad")
        self._last_scale_source = est.source
        scale = est.value if est.source != "none" else 0.0

        self._cache = (values.copy(), trend, residual, scale, est.source)
        return trend, residual, scale

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        trend, _, scale = self._parts(values)
        if not np.isfinite(scale):
            scale = 0.0
        return Bands(
            baseline=trend,
            lower=trend - float(threshold) * scale,
            upper=trend + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)
