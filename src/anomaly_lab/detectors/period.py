"""周期估计：FFT 粗定位 + ACF 精定位。

相对原来「只用 ACF、lag 上限硬编码 200」的做法，这里解决了三个问题：

1. **看得见长周期**：ACF 只能看到 `max_lag` 个滞后，原来上限写死 200——
   而 5min 粒度的日周期是 288 点、周周期 2016 点，ACF 根本看不到。
   FFT 没有这个限制。
2. **周期不再有 ±1 误差**：原来 ACF 峰的位置直接当周期，真实周期 48 会被
   估成 47 或 49。相位分组时 ±1 的误差会让基线整体错位、混相位。
   这里用 FFT 补零 + 抛物线插值细化峰位置。
3. **不受采样频率干扰**：候选周期范围用**时间**（秒）表达，
   同一个「一天」在 5min 与 1h 粒度下不会被当成不同长度。

自相关用 FFT 卷积算（O(n log n)），长序列上比直接相关快一个量级。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.frequency import freq_seconds

#: 候选周期的默认时间范围：1 小时 ~ 30 天
DEFAULT_MIN_PERIOD_SECONDS = 3600.0
DEFAULT_MAX_PERIOD_SECONDS = 30 * 86400.0

#: 至少要能看见这么多个周期，否则无法区分「周期」与「趋势」
DEFAULT_MIN_CYCLES = 3

#: FFT 补零倍数：补零不增加真实信息，但能把峰位置插值得更细
_DEFAULT_FFT_PADDING = 8

#: 频谱峰突出度门槛：峰 / 背景中位数。低于此值认为没有周期。
MIN_FFT_PROMINENCE = 3.0

#: 周期估计的最低置信度：低于此值，调用方应当回退到默认周期
MIN_CONFIDENCE = 0.35


@dataclass(frozen=True)
class PeriodEstimate:
    """周期估计结果。"""

    period_points: int | None
    period_seconds: float | None
    confidence: float
    method: str

    @property
    def found(self) -> bool:
        return self.period_points is not None and self.period_points >= 2

    @property
    def usable(self) -> bool:
        """是否值得采用：检出了周期**且**置信度够高。

        纯噪声里也能挑出一个「看起来像周期」的峰，但置信度会很低——
        所以「检出了」与「该用」是两回事。
        """
        return self.found and self.confidence >= MIN_CONFIDENCE


def _detrend(values: np.ndarray) -> np.ndarray:
    """去线性趋势——否则趋势会主导低频谱。"""
    n = len(values)
    if n < 3:
        return values - values.mean() if n else values
    t = np.arange(n, dtype=float)
    return values - np.polyval(np.polyfit(t, values, 1), t)


def autocorrelate(values: np.ndarray, max_lag: int) -> np.ndarray:
    """归一化自相关（lag 0..max_lag），用 FFT 卷积算，O(n log n)。"""
    n = len(values)
    if n < 3 or max_lag < 1:
        return np.ones(1)
    size = 1
    while size < 2 * n:
        size *= 2
    spectrum = np.fft.rfft(values, size)
    full = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n]
    if full[0] <= 0:
        return np.zeros(max_lag + 1)
    normalized = full / full[0]
    return normalized[: max_lag + 1]


def _refine_peak(spectrum: np.ndarray, index: int) -> float:
    """抛物线插值细化谱峰位置（把 ±1 桶的误差降到亚桶级）。"""
    if index <= 0 or index >= len(spectrum) - 1:
        return float(index)
    left, center, right = spectrum[index - 1], spectrum[index], spectrum[index + 1]
    denominator = left - 2 * center + right
    if denominator == 0:
        return float(index)
    offset = 0.5 * (left - right) / denominator
    if not np.isfinite(offset) or abs(offset) > 1:
        return float(index)
    return float(index) + float(offset)


def _fft_period(
    detrended: np.ndarray, min_lag: int, max_lag: int, padding: int
) -> tuple[float | None, float]:
    """FFT 粗定位周期。返回 (周期点数, 峰突出度)。"""
    n = len(detrended)
    n_fft = max(64, n * padding)
    spectrum = np.abs(np.fft.rfft(detrended, n_fft))
    if len(spectrum) < 3:
        return None, 0.0
    # 周期与频率互为倒数：周期 p 点 ↔ 频率 bin k = n_fft / p
    k_min = max(1, int(np.floor(n_fft / max_lag)))
    k_max = min(len(spectrum) - 2, int(np.ceil(n_fft / min_lag)))
    if k_max <= k_min:
        return None, 0.0
    window = spectrum[k_min : k_max + 1]
    peak = int(np.argmax(window)) + k_min
    refined = _refine_peak(spectrum, peak)
    period = n_fft / refined if refined > 0 else None
    background = float(np.median(spectrum[k_min : k_max + 1])) or 1e-12
    prominence = float(spectrum[peak] / background)
    return period, prominence


def _acf_peak_near(
    acf: np.ndarray, target: float, min_lag: int, max_lag: int, n: int
) -> tuple[int | None, float]:
    """在目标周期附近找 ACF 局部峰，用于**验证** FFT 的结果。

    显著性用 3/sqrt(n) 作门槛：纯噪声的自相关峰值量级就在这儿，
    不设门槛会把随机波动当成周期。
    """
    if len(acf) < 3 or target < min_lag:
        return None, 0.0
    low = max(min_lag, int(np.floor(target * 0.85)))
    high = min(max_lag, int(np.ceil(target * 1.15)), len(acf) - 1)
    if high <= low:
        return None, 0.0
    best_lag: int | None = None
    best_value = -np.inf
    for lag in range(low, high + 1):
        value = float(acf[lag])
        if value > best_value:
            best_value = value
            best_lag = lag
    if best_lag is None or best_value <= 0:
        return None, 0.0
    threshold = max(0.1, 3.0 / np.sqrt(max(n, 1)))
    if best_value < threshold:
        return None, 0.0
    # 必须是局部峰（否则说明这附近根本没有周期）
    left = float(acf[best_lag - 1]) if best_lag > 0 else -np.inf
    right = float(acf[best_lag + 1]) if best_lag + 1 < len(acf) else -np.inf
    if best_value < left or best_value < right:
        return None, 0.0
    return best_lag, best_value


def estimate_period(
    values: np.ndarray,
    freq: str = "1min",
    *,
    min_period_seconds: float = DEFAULT_MIN_PERIOD_SECONDS,
    max_period_seconds: float = DEFAULT_MAX_PERIOD_SECONDS,
    min_cycles: int = DEFAULT_MIN_CYCLES,
    padding: int = _DEFAULT_FFT_PADDING,
) -> PeriodEstimate:
    """估计序列的主周期。

    候选范围用**时间**表达（默认 1 小时 ~ 30 天），换算成点数后
    再做 FFT/ACF，所以同一个「日周期」在不同采样粒度下都能被找到。
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 10 or np.std(values) < 1e-12:
        return PeriodEstimate(None, None, 0.0, "none")
    try:
        step = freq_seconds(freq)
    except ValueError:
        step = 1.0
    min_lag = max(2, int(np.ceil(min_period_seconds / step)))
    # 候选周期上限：数据长度与时间上限取小。**不**按 min_cycles 卡——
    # 数据只够 1.5 个周期时，把真周期排除在范围外反而会让它的谐波胜出。
    # 装不下几个周期交给 confidence 反映。
    max_lag = min(n - 1, int(max_period_seconds // step))
    if max_lag < min_lag:
        return PeriodEstimate(None, None, 0.0, "none")

    detrended = _detrend(values)
    fft_period, prominence = _fft_period(detrended, min_lag, max_lag, padding)
    if fft_period is None:
        return PeriodEstimate(None, None, 0.0, "none")
    if prominence < MIN_FFT_PROMINENCE:
        # 频谱上没有突出的峰——多半不是周期序列
        return PeriodEstimate(None, None, 0.0, "none")

    acf = autocorrelate(detrended, max_lag)
    peak_lag, peak_value = _acf_peak_near(acf, fft_period, min_lag, max_lag, n)

    # 周期取 FFT 的精修值（补零 + 抛物线插值，亚桶级精度），
    # ACF 峰只用来**验证**：确认这附近真的有周期，而不是靠它定位置——
    # ACF 峰的位置有 ±1 的误差，会让相位分组错位。
    period_points = float(np.clip(fft_period, min_lag, max_lag))
    agreement = 1.0 if peak_lag is not None and abs(peak_lag - period_points) <= 1.5 else 0.0
    method = "fft+acf" if agreement else "fft"

    cycles = n / period_points if period_points else 0.0
    confidence = _confidence(
        acf_value=peak_value if agreement else 0.0,
        prominence=prominence,
        agreement=agreement,
        cycles=cycles,
        min_cycles=min_cycles,
    )
    return PeriodEstimate(
        period_points=round(period_points),
        period_seconds=period_points * step,
        confidence=confidence,
        method=method,
    )


def detect_period(series, fallback: int = 24) -> int:
    """估计序列周期，拿不准时回退到 `fallback`。

    两个安全检查：

    - **置信度不够**就不用估计值——宁可用一个已知会错的默认值，
      也不要一个看起来精确但其实错位的周期（±1 的误差就会让相位分组错位）。
    - **装不下两个周期**也不用——相位分组要求每个相位至少 2 个点，
      STL 也要求至少两个完整周期。
    """
    estimate = estimate_period(series.values, series.freq)
    if not estimate.usable:
        return fallback
    period = int(estimate.period_points)
    if period * 2 > len(series.values):
        return fallback
    return period


def _confidence(
    *, acf_value: float, prominence: float, agreement: float, cycles: float, min_cycles: int
) -> float:
    """把几个信号合成一个 0~1 的置信度。

    周期候选的「看起来像周期」程度：ACF 峰值、FFT 峰突出度、两者是否一致、
    以及能不能装下足够多个周期（装不下说明这更像趋势）。
    """
    acf_part = float(np.clip(acf_value, 0.0, 1.0))
    prominence_part = float(np.clip(np.log10(max(prominence, 1.0)) / 2.0, 0.0, 1.0))
    cycle_part = float(np.clip(cycles / max(min_cycles, 1), 0.0, 1.0))
    score = 0.35 * acf_part + 0.25 * prominence_part + 0.25 * agreement + 0.15 * cycle_part
    # 只够 1 个多周期时，所谓的「周期」多半是趋势或偶然——大幅降权
    if cycles < 2:
        score *= 0.3
    return float(np.clip(score, 0.0, 1.0))
