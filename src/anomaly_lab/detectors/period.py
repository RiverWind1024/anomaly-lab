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

from anomaly_lab.detectors.robust import winsorize
from anomaly_lab.frequency import freq_seconds

#: 候选周期的默认时间范围：5 分钟 ~ 30 天
#:
#: 下限取 5 分钟而不是 1 小时，是因为分钟级的短周期很常见（心跳、批处理、
#: 定时任务）。下限太长会把真周期直接排除在候选之外——那就再也检不出来了。
DEFAULT_MIN_PERIOD_SECONDS = 300.0
DEFAULT_MAX_PERIOD_SECONDS = 30 * 86400.0

#: 至少要能看见这么多个周期，否则无法区分「周期」与「趋势」
DEFAULT_MIN_CYCLES = 3

#: FFT 补零倍数：补零不增加真实信息，但能把峰位置插值得更细
_DEFAULT_FFT_PADDING = 8

#: 精修阶段的目标桶间距（以周期点为单位）：越小越准，代价是 FFT 变长
_REFINE_BUCKET_TARGET = 4.0

#: 精修阶段 FFT 长度的上限（2^20）
_MAX_FFT_SIZE = 1 << 20

#: 频谱峰突出度门槛：峰 / 背景中位数。低于此值认为没有周期。
MIN_FFT_PROMINENCE = 3.0

#: 谐波验证门槛：p、2p、3p 处的 ACF 超过此值才算「有支持」。
#:
#: 实测的分离度很清晰：真实周期序列的谐波值 ≥ 0.26，而由注入异常
#: （drift / flatline / freq_shift）造成的伪周期 ≤ 0.08。
#: 0.15 落在两者之间，约等于噪声 ACF 基线（1/√n）的 3σ。
HARMONIC_THRESHOLD = 0.15

#: 候选周期的最少点数。少于 4 个点的「周期」没有统计意义——
#: 相位分组每相位只有 1~2 个点，MAD 会退化。
MIN_PERIOD_POINTS = 4

#: 每个相位至少要有这么多个样本，相位内的中位数与 MAD 才稳定，
#: 解释力也不会因为自由度太低而虚高。
#: 它等价于「周期至少要出现 3 次」——2 个周期时相位内只有 2 个点，
#: 中位数与 MAD 都退化了。
MIN_SAMPLES_PER_PHASE = 3

#: 周期解释力门槛：按该周期分组后，组内方差占总方差的比例至少要这么低。
#: 实测：真实周期序列 ≥ 0.17，被误判成周期的非周期序列 ≤ 0.023。
MIN_PHASE_EXPLAINED_VARIANCE = 0.08

#: 周期估计的最低置信度：低于此值，调用方应当回退到默认周期
MIN_CONFIDENCE = 0.35

#: 回退周期的默认时间长度：1 天
DEFAULT_FALLBACK_SECONDS = 86400.0


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


def _fft_peaks(spectrum: np.ndarray, k_min: int, k_max: int) -> list[int]:
    """频谱上的全部局部峰，按幅度降序。

    不能只取 argmax：**谐波歧义**是这里最大的坑。真周期 24 的脉冲序列，
    频谱在 5 倍频（周期 4.8）处的振幅比基频还高（55.8 vs 16.4），
    argmax 会选中它。所以要遍历所有候选，交给 ACF 去裁决。
    """
    window = spectrum[k_min : k_max + 1]
    peaks = [
        i + k_min
        for i in range(1, len(window) - 1)
        if window[i] >= window[i - 1] and window[i] > window[i + 1]
    ]
    peaks.sort(key=lambda k: -spectrum[k])
    return peaks


def _prominence(spectrum: np.ndarray, k: int, k_min: int, k_max: int) -> float:
    """谱峰相对背景中位数的突出度。"""
    background = float(np.median(spectrum[k_min : k_max + 1])) or 1e-12
    return float(spectrum[k] / background)


def _acf_near(
    acf: np.ndarray, target: float, min_lag: int, max_lag: int, n: int
) -> tuple[int | None, float]:
    """在目标周期附近找 ACF 峰。

    选**谐波支持最好**的位置，而不是单纯的最大值：被异常污染时，
    真周期位置（lag 10，ACF 0.213）常被旁边的噪声峰（lag 11，ACF 0.259）
    盖过，但真周期位置的谐波重复性更好——p、2p、3p 都在。

    显著性门槛用 1.5/√n：噪声的自相关峰值量级就在 1/√n 附近，
    但不能定得太严——离群点会把峰压低（实测 0.824 → 0.26），
    定太严会让**有异常的那段数据**检不出周期，反而漏报。
    """
    low = max(min_lag, int(np.floor(target * 0.85)))
    high = min(max_lag, int(np.ceil(target * 1.15)), len(acf) - 1)
    if high <= low:
        return None, 0.0
    threshold = 1.5 / np.sqrt(max(n, 1))
    best_lag: int | None = None
    best_value = -np.inf
    best_supported = -1
    for lag in range(low, high + 1):
        value = float(acf[lag])
        if value < threshold:
            continue
        supported = _harmonic_support(acf, lag, max_lag)
        if (supported, value) > (best_supported, best_value):
            best_lag = lag
            best_value = value
            best_supported = supported
    if best_lag is None:
        return None, 0.0
    return best_lag, best_value


def _is_base_frequency(
    acf: np.ndarray, period: float, base_value: float, min_lag: int, max_lag: int
) -> bool:
    """候选是**基频**，还是它的 2 倍 / 3 倍谐波？

    谐波位置的 ACF 也会很高，但它的**分数约数**（period/2、period/3）
    位置上会有更高的 ACF 峰——那才是基频的峰。

    注意要带 ±1 容差：ACF 的峰可能很窄（实测 lag 24 是 0.525，
    lag 25 就掉到 -0.086），取整偏 1 就会找不到基频的峰。
    """
    for divisor in (2, 3):
        sub = period / divisor
        if sub < min_lag or sub > max_lag:
            continue
        center = round(sub)
        low = max(0, center - 1)
        high = min(len(acf) - 1, center + 1)
        if float(acf[low : high + 1].max()) > base_value:
            return False
    return True


def phase_explained_variance(values: np.ndarray, period: int) -> float:
    """按周期分组后，**组内**方差占总方差的比例（1 = 完全被周期解释）。

    这是判断「这个周期能不能用来做相位分组」的最直接指标：
    真周期的各相位高度一致（组内方差小），解释方差高；
    噪声或异常造成的伪周期，组内方差和总方差差不多，解释方差接近 0。

    实测分离度很清晰：真实周期序列 ≥ 0.17，而被误判成周期的
    非周期序列 ≤ 0.023——中间有 7 倍以上的间隔。
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if period < 2 or n < period * 2:
        return 0.0
    total = float(values.var())
    if total <= 0:
        return 1.0
    phases = np.arange(n) % period
    # 向量化：每相位的样本数、和、平方和
    counts = np.bincount(phases, minlength=period).astype(float)
    sums = np.bincount(phases, weights=values, minlength=period)
    sumsq = np.bincount(phases, weights=values * values, minlength=period)
    valid = counts >= 2
    if not valid.any():
        return 0.0
    means = np.divide(sums, counts, out=np.zeros(period), where=counts > 0)
    variances = np.divide(
        sumsq - counts * means * means, counts, out=np.zeros(period), where=counts > 0
    )
    within = float(np.sum(np.clip(variances, 0.0, None) * counts[valid])) / n
    return float(np.clip(1.0 - within / total, 0.0, 1.0))


def _harmonic_support(acf: np.ndarray, lag: int, max_lag: int) -> int:
    """周期在 `p`、`2p`、`3p` 处是否**重复**出现。

    真正的周期会在 p、2p、3p 处都留下自相关峰；偶然峰不会。
    这比「单个 lag 的 ACF 超过固定门槛」稳健得多：

    - 单点门槛会被**单个异常点**抬高——监控数据里恰恰是有异常的那段
      最容易被误判，周期估计失效 → 基线失效 → 漏报；
    - 单点门槛也会给**噪声序列的随机峰**放行；
    - 重复性用的是**结构**而不是幅度，对离群点天然鲁棒。

    这是**硬门槛**：至少要有 2 个谐波得到支持，否则一律不接受。
    实测真周期的谐波值 ≥ 0.26，而异常造成的伪周期 ≤ 0.08。
    """
    supported = 0
    for k in (1, 2, 3):
        target = lag * k
        if target > max_lag or target >= len(acf):
            continue
        if float(acf[target]) > HARMONIC_THRESHOLD:
            supported += 1
    return supported


def _refine_period(detrended: np.ndarray, period: float, anchor: int) -> float:
    """用**更高补零倍数**的 FFT 精修周期位置。

    补零后频率 bin 间距换算成周期是 `P² / n_fft`：主流程用 8 倍补零时，
    周期 168 对应的桶间距高达 12 个周期点——抛物线插值也救不回来，
    会估成 170。这里按周期长度自适应补零，把桶间距压到 0.25 个周期点以内。

    搜索用**两级窗口**：

    - ACF 锚点与候选一致时（差 ≤ 1）用窄窗口（±2 个 bin）——窄窗最准，
      宽窗会选到噪声造出的假峰（实测周期 288 被估成 292）。
    - 两者不一致时（候选本身偏了几个点）才放宽到 ±15%。
    """
    n = len(detrended)
    needed = int(np.ceil(_REFINE_BUCKET_TARGET * period * period))
    n_fft = max(64, n * _DEFAULT_FFT_PADDING, min(needed, _MAX_FFT_SIZE))
    spectrum = np.abs(np.fft.rfft(detrended, n_fft))
    center = n_fft / period
    aligned = abs(anchor - period) <= 1.0
    widths = (2,) if aligned else (2, int(np.ceil(center * 0.15)))
    for width in widths:
        low = max(1, int(np.floor(center)) - width)
        high = min(len(spectrum) - 2, int(np.ceil(center)) + width)
        if high <= low:
            continue
        k = int(np.argmax(spectrum[low : high + 1])) + low
        value = n_fft / k
        if not aligned and abs(value - period) > 0.15 * period:
            continue
        refined = _refine_peak(spectrum, k)
        if refined <= 0:
            return value
        return n_fft / refined
    return period


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

    候选范围用**时间**表达（默认 5 分钟 ~ 30 天），换算成点数后
    再做 FFT/ACF，所以同一个「日周期」在不同采样粒度下都能被找到。

    ## 为什么是「FFT 找候选 + ACF 裁决」

    两套方法各有盲区，必须互补：

    - **FFT** 能看见长周期（ACF 的 lag 上限有限），但怕**谐波歧义**：
      真周期 24 的脉冲序列，频谱在 5 倍频（周期 4.8）处振幅比基频还高
      （55.8 vs 16.4），单取 argmax 会选中它。
    - **ACF** 天然对谐波不敏感（p、2p、3p 都在，但基频 p 处最高），
      但长周期的 ACF 峰是**宽平台**，局部峰判据会偏几个点。

    所以流程是：FFT 列出全部局部峰（按幅度降序），逐个交给 ACF 裁决——
    要求 ACF 在候选附近有峰、候选不是别人的谐波、且谐波重复性够强。
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    if n < 10 or np.std(values) < 1e-12:
        return PeriodEstimate(None, None, 0.0, "none")
    try:
        step = freq_seconds(freq)
    except ValueError:
        step = 1.0
    min_lag = max(MIN_PERIOD_POINTS, int(np.ceil(min_period_seconds / step)))
    # 候选周期上限：数据长度与时间上限取小。**不**按 min_cycles 卡——
    # 数据只够 1.5 个周期时，把真周期排除在范围外反而会让它的谐波胜出。
    # 装不下几个周期交给 confidence 反映。
    max_lag = min(n - 1, int(max_period_seconds // step))
    if max_lag < min_lag:
        return PeriodEstimate(None, None, 0.0, "none")

    detrended = _detrend(winsorize(values))
    n_fft = max(64, n * padding)
    spectrum = np.abs(np.fft.rfft(detrended, n_fft))
    # 周期 p 点 ↔ 频率 bin k = n_fft / p
    k_min = max(1, int(np.floor(n_fft / max_lag)))
    k_max = min(len(spectrum) - 2, int(np.ceil(n_fft / min_lag)))
    if k_max <= k_min:
        return PeriodEstimate(None, None, 0.0, "none")

    acf = autocorrelate(detrended, max_lag)
    candidates: list[tuple[float, int, int, float, int, int, float]] = []
    for k in _fft_peaks(spectrum, k_min, k_max):
        period = n_fft / k
        if period < min_lag or period > max_lag:
            continue
        lag, peak_value = _acf_near(acf, period, min_lag, max_lag, n)
        if lag is None:
            continue
        if abs(lag - period) > max(2.0, 0.15 * period):
            # ACF 与 FFT 说的不是一回事
            continue
        if not _is_base_frequency(acf, period, peak_value, min_lag, max_lag):
            # 这是别人的谐波，基频在它的分数约数位置上
            continue
        supported = _harmonic_support(acf, lag, max_lag)
        if supported < 2:
            # 谐波重复性不够：多半是偶然的峰，不是周期
            continue
        # 周期位置用 FFT 的浮点值取整（亚桶级精度，避免 ACF 峰的 ±1 误差——
        # 相位分组时 ±1 会让基线整体错位）；但**基频身份**由 ACF 判定。
        points = round(period)
        if n // points < MIN_SAMPLES_PER_PHASE:
            # 每相位样本太少：组内中位数/MAD 都不稳定，解释力也会虚高
            # （实测真周期 24 的序列会被误判成周期 167——每相位仅 3 个点）
            continue
        explained = phase_explained_variance(values, points)
        if explained < MIN_PHASE_EXPLAINED_VARIANCE:
            # 按这个周期分组，各相位并不一致——相位基线会混相位
            continue
        candidates.append((explained, points, k, peak_value, supported, lag, period))

    if not candidates:
        return PeriodEstimate(None, None, 0.0, "none")

    # 倍数消歧：真周期的**整数倍**解释力往往更高（把相位合并了），
    # 所以不能简单地取解释力最大——那会选到 2 倍/4 倍谐波。
    # 在候选集合里剔除那些是别的候选整数倍的候选。
    def _is_multiple_of_others(points: int) -> bool:
        for _, other, *_ in candidates:
            if other >= points:
                continue
            for multiplier in (2, 3, 4, 5, 6):
                target = other * multiplier
                if abs(points - target) <= 0.15 * target:
                    return True
        return False

    base_candidates = [c for c in candidates if not _is_multiple_of_others(c[1])]
    if not base_candidates:
        base_candidates = candidates

    explained, points, k, peak_value, supported, anchor, period_float = max(
        base_candidates, key=lambda c: c[0]
    )
    prominence = _prominence(spectrum, k, k_min, k_max)
    # 精修位置：长周期下 8 倍补零的桶间距太大（周期 168 → 12 个周期点），
    # 这里按周期长度自适应提高补零倍数
    period_points = float(
        np.clip(
            round(_refine_period(detrended, period_float, anchor)), min_lag, max_lag
        )
    )
    cycles = n / period_points if period_points else 0.0
    confidence = _confidence(
        acf_value=peak_value,
        prominence=prominence,
        agreement=supported / 3.0,
        explained=explained,
        cycles=cycles,
        min_cycles=min_cycles,
    )
    return PeriodEstimate(
        period_points=round(period_points),
        period_seconds=period_points * step,
        confidence=confidence,
        method="fft+acf",
    )


def default_fallback_period(freq: str, n: int) -> int:
    """按**时间**给出兜底周期，而不是写死点数。

    「一天」在 1min 粒度下是 1440 点，在 1h 粒度下是 24 点。写死 24 点
    在 1min 粒度下等于 24 分钟——相位分组整个错位，基线混相位。

    同时保证**每个相位有足够的样本**（至少 `MIN_SAMPLES_PER_PHASE` 个）：
    相位内只有 2~3 个点时，中位数与 MAD 都不稳定，分组出来的基线是噪声。
    """
    try:
        step = freq_seconds(freq)
    except ValueError:
        step = 60.0
    points = max(2, int(DEFAULT_FALLBACK_SECONDS // step))
    points = min(points, max(2, n // MIN_SAMPLES_PER_PHASE))
    return points


def usable_period(series) -> int | None:
    """返回**可信**的周期点数；拿不准时返回 None。

    与 `detect_period` 的区别：这里不猜。猜一个周期去做相位分组，
    只会造出混相位的基线——比不做季节性更糟。
    """
    estimate = estimate_period(series.values, series.freq)
    if not estimate.usable:
        return None
    period = int(estimate.period_points)
    if period * 2 > len(series.values):
        return None
    return period


def detect_period(series, fallback: int | None = None) -> int:
    """估计序列周期，拿不准时回退。

    三个安全检查：

    - **置信度不够**就不用估计值——宁可用一个已知会错的默认值，
      也不要一个看起来精确但其实错位的周期（±1 的误差就会让相位分组错位）。
    - **装不下两个周期**也不用——相位分组要求每个相位至少 2 个点，
      STL 也要求至少两个完整周期。

    `fallback` 显式给点数就按点数用；不给则按**时间**回退到默认周期
    （见 `default_fallback_period`）。

    注意这只是「给出一个数」。想知道周期**是否可信**，用 `usable_period`。
    """
    period = usable_period(series)
    if period is not None:
        return period
    if fallback is not None:
        return fallback
    return default_fallback_period(series.freq, len(series.values))


def _confidence(
    *,
    acf_value: float,
    prominence: float,
    agreement: float,
    explained: float,
    cycles: float,
    min_cycles: int,
) -> float:
    """把几个信号合成一个 0~1 的置信度。

    五个信号：相位解释力（最本质——直接对应「相位基线靠不靠谱」）、
    谐波重复性、ACF 峰幅度、FFT 峰突出度、能装下几个周期。
    """
    explained_part = float(np.clip(explained, 0.0, 1.0))
    acf_part = float(np.clip(acf_value, 0.0, 1.0))
    prominence_part = float(np.clip(np.log10(max(prominence, 1.0)) / 2.0, 0.0, 1.0))
    cycle_part = float(np.clip(cycles / max(min_cycles, 1), 0.0, 1.0))
    score = (
        0.30 * explained_part
        + 0.25 * float(np.clip(agreement, 0.0, 1.0))
        + 0.20 * acf_part
        + 0.15 * prominence_part
        + 0.10 * cycle_part
    )
    # 只够 1 个多周期时，所谓的「周期」多半是趋势或偶然——大幅降权
    if cycles < 2:
        score *= 0.3
    return float(np.clip(score, 0.0, 1.0))
