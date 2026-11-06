"""稀疏 / 计数型数据的专用检测器。

⚠️ 两个检测器都**没有 `bands()`**：
    它们只说「这个点有多异常」，给不出「正常值应该在哪」。
    平台侧 `bands()` 返回 None，前端不画带 —— 这是预期行为。

- `poisson_count`：计数值（每分钟 error 数）vs 泊松期望；
- `zero_inflated_iqr`：大部分为 0、非零有幅度（交易额、消息大小）。
  幅度尺度也走降级链：非零 IQR → 非零 MAD → 非零 std → 不可判。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.base import TimedDetector
from anomaly_lab.detectors.scale import robust_scale


class PoissonCountDetector(TimedDetector):
    """计数值 vs 泊松期望 —— 单点 + 窗口累计，取较大者。

    ⚠️ 和 `event_count` 的区别：
       `event_count` 先二值化，只数「有几个点非零」——
       1 次和 10 次完全一样；
       这里直接用**值本身**当计数，所以强度是看得见的。

    ⚠️ 分数是 **P(X < 观测值)**（累计概率），越大越异常 ——
       与项目「分数越大越异常」的约定一致。
       ⚠️ 不要用 `poisson.sf`：它返回的是 p 值，越小越异常，
          方向正好相反，而且 value=0 时恒等于 1。
    """

    name = "poisson_count"
    score_type = "prob"
    default_threshold = 0.99

    def __init__(self, window: int = 10, threshold: float = 0.99) -> None:
        if window < 2:
            raise ValueError("window 至少为 2")
        self.window = int(window)
        self.default_threshold = float(threshold)

    def fit(self, series: SeriesBundle) -> PoissonCountDetector:
        return self

    def detect(self, series: SeriesBundle, threshold: float | None = None):
        return self._timed_detect(series, threshold)

    def score(self, series: SeriesBundle) -> np.ndarray:
        from scipy.stats import poisson

        # ⚠️ `_timed_detect` 会在调用 score() 前清空尺度来源，这里必须重写
        self._last_scale_source = "poisson"

        values = np.asarray(series.values, dtype=float)

        # ⚠️ λ 必须是因果的：只用**当前点之前**的数据。
        #    前两个点没有足够历史（min_periods=2 + shift(1)）→ 无法判断，
        #    分数给 0，绝不能用全序列均值兜底（那是未来数据）。
        history = (
            pd.Series(values).expanding(min_periods=2).mean().shift(1).to_numpy()
        )
        known = np.isfinite(history)
        # 未知位置给一个占位值（最后会被 `known` 掩成 0 分）
        rate = np.where(known, history, 1.0)
        lam = np.maximum(rate, 1e-3)   # λ=0 会让第一次出现变成「无穷倍」

        # ① 单点：这一分钟爆了
        p_point = poisson.cdf(values - 1, lam)

        # ② 窗口累计：这几分钟一直在出（λ 随有效窗口长度缩放）
        sums = pd.Series(values).rolling(self.window, min_periods=1).sum().to_numpy()
        effective = (
            pd.Series(values).rolling(self.window, min_periods=1).count().to_numpy()
        )
        p_window = poisson.cdf(sums - 1, lam * effective)

        # ⚠️ 窗口项只在「当前点本身就有事件」时采用 ——
        #    否则一次尖峰会让它后面 window-1 个 **0 值点**都报 1.0，
        #    用户会看到「0 次 / 分数 1.0」的告警。
        scores = np.where(values > 0, np.maximum(p_point, p_window), 0.0)
        return np.where(known, scores, 0.0)


MIN_NONZERO_SAMPLES = 30


class ZeroInflatedIQRDetector(TimedDetector):
    """零膨胀两段模型：零点不判，非零部分用 IQR 估幅度。

    ⚠️ 为什么不能直接用 iqr：
       零值 >75% 时 IQR = 0；零值 >50% 时 MAD = 0。
       把非零子集单独拿出来估，分母才有意义。

    ⚠️ 非零点 < 30 时**不装懂** —— 分位数估不准，标「无法判定」。
    """

    name = "zero_inflated_iqr"
    score_type = "zscore"
    prefer_scale = "iqr"
    default_threshold = 3.0

    def __init__(self, k: float = 3.0) -> None:
        self.k = float(k)
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> ZeroInflatedIQRDetector:
        return self

    def detect(self, series: SeriesBundle, threshold: float | None = None):
        return self._timed_detect(series, threshold)

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        mask = values != 0
        n_nonzero = int(mask.sum())
        scores = np.zeros_like(values)

        if n_nonzero < MIN_NONZERO_SAMPLES:
            self._last_scale_source = "none"
            self._last_status = "undetermined"
            return scores

        sub = values[mask]
        med = float(np.median(sub))
        est = robust_scale(sub, prefer="iqr")
        self._last_scale_source = est.source
        self._last_status = "ok" if est.source != "none" else "undetermined"
        if est.source == "none":
            return scores

        scores[mask] = np.abs(sub - med) / est.value
        return scores
