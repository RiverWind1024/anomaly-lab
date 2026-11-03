"""造数器：7 条确定性曲线，带尖峰 / 漂移 / 断流 / 值缺失 / 趋势 / 阶跃 / 稀疏事件。

⚠️ **确定性是硬要求** —— 同一 seed 造两次必须完全一样，
   否则测试没法断言、演示也没法复现。

做法：每点的「创新项」由 `np.random.default_rng([seed, index])` 取
（同一 index 恒等），基线与异常注入是纯函数，AR(1) 递推给出连续抖动。
不能用全局 RNG —— 它的状态依赖调用顺序，不满足「按 index 求值」。

⚠️ **不能用内置 `hash()`** —— 字符串的 hash 被 PYTHONHASHSEED 随机化，
   换个进程就变了。这里用 `zlib.crc32`（稳定）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import zlib
from dataclasses import dataclass

import numpy as np

#: 采样间隔（秒）—— 1 分钟。
SAMPLE_SECONDS = 60

#: 一天有多少个采样点（1 分钟采样 → 1440）。
POINTS_PER_DAY = 24 * 60

#: 默认保留窗口（小时）—— 假远端只保留最近这些小时的数据。
DEFAULT_RETENTION_HOURS = 6


def _stable_seed(name: str) -> int:
    """字符串 → 稳定的 32 位种子。

    ⚠️ 不能用内置 `hash()` —— 字符串的 hash 被 PYTHONHASHSEED 随机化。
    """
    return zlib.crc32(name.encode("utf-8")) % (2**32)


@dataclass(frozen=True)
class SeriesSpec:
    """一条曲线的规格。

    ⚠️ 字段全是「纯」的 —— 同样的参数必然给出同样的曲线。
    """

    name: str
    #: 基线类型：`constant` / `daily` / `trending` / `step` / `sparse`。
    baseline: str = "constant"
    #: 基线中心值。
    level: float = 0.0
    #: 基线振幅（`daily` 时是日周期的振幅）。
    amplitude: float = 0.0
    #: 噪声标准差。
    sigma: float = 0.0
    #: AR(1) 系数 —— 0 = 白噪声，接近 1 = 强相关（平滑）。
    phi: float = 0.0
    #: 尖峰：每隔多少个点出现一次。
    spike_every: int = 0
    #: 尖峰的持续点数。
    spike_width: int = 0
    #: 尖峰的倍数（相对基线）。
    spike_gain: float = 0.0
    #: 漂移：从第几个点开始，基线线性上移多少。
    drift_from: int = 0
    drift_span: int = 0
    drift_amount: float = 0.0
    #: 断流：从第几个点开始，连续多少个点**不产生**。
    gap_from: int = 0
    gap_len: int = 0
    #: 值缺失：每隔多少个点写一次 NULL。
    null_every: int = 0
    #: 趋势型：每点的增量（每小时 = 增量 × 60）。
    slope: float = 0.0
    #: 阶跃型（一次性）：第几个点跳变。
    step_at: int = 0
    #: 阶跃型（周期性）：每隔多少个点在两个水平间切换。0 = 不启用。
    step_period: int = 0
    #: 阶跃型：跳变的幅度（绝对值，不是倍数）。
    step_delta: float = 0.0
    #: 稀疏型：每点成为事件**起点**的概率。
    event_rate: float = 0.0
    #: 稀疏型：事件的持续点数。
    event_width: int = 1
    #: 稀疏型：事件的高度（绝对值 —— 稀疏型的基线通常是 0，乘法没意义）。
    event_value: float = 0.0


#: 七条曲线的规格 —— 前四条见 spec §5.1，后三条是形态演示用的。
SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec(
        name="web-traffic",
        baseline="daily",
        level=100.0,
        amplitude=30.0,
        sigma=3.0,
        phi=0.7,
    ),
    SeriesSpec(
        name="api-latency",
        baseline="constant",
        level=50.0,
        sigma=8.0,
        phi=0.6,
        null_every=50,
    ),
    SeriesSpec(
        name="db-pool",
        baseline="daily",
        level=20.0,
        amplitude=10.0,
        sigma=1.0,
        phi=0.5,
        spike_every=30,
        spike_width=2,
        spike_gain=3.0,
        gap_from=180,
        gap_len=20,
    ),
    SeriesSpec(
        name="cache-hit",
        baseline="daily",
        level=80.0,
        amplitude=5.0,
        sigma=0.5,
        phi=0.8,
        drift_from=120,
        drift_span=240,
        drift_amount=15.0,
    ),
    # ⚠️ 下面三条是**形态演示**用的 —— 演示「不同形态的数据，检测器表现不同」。
    #
    # ⚠️ `trend-load` 是**整条曲线都在涨**（不是 cache-hit 那种临时漂移）：
    #    线性趋势对 IQR 这类只看分位数的检测器**天然不敏感** ——
    #    窗口内单调递增，分位数间距稳定 → 不该误报。
    SeriesSpec(
        name="trend-load",
        baseline="trending",
        level=40.0,
        slope=0.02,
        sigma=1.2,
        phi=0.5,
    ),
    # ⚠️ `step-cache` 是**水平跳变**（changepoint）：
    #    每 3 小时在两个水平间切一次。
    #    为什么是**周期性**而不是一次性：假远端是持续运行的，
    #    一次性阶跃只发生一次 —— 演示时早就滚出保留窗口了，
    #    永远看不到「抓住跳变」的那一刻。周期性才能一直演到。
    SeriesSpec(
        name="step-cache",
        baseline="step",
        level=30.0,
        step_period=180,
        step_delta=25.0,
        sigma=1.5,
        phi=0.4,
    ),
    # ⚠️ `job-runs` 是**稀疏事件**：绝大多数点是 0，偶尔冒一个脉冲。
    #    这是 IQR 的**盲区** —— 窗口内 75% 分位数仍是 0 → IQR = 0 →
    #    分数算不出来（NaN）→ 一条都不报。
    #    留着这条不是为了好看，是为了说明「检测器各有各的盲区」。
    SeriesSpec(
        name="job-runs",
        baseline="sparse",
        level=0.0,
        sigma=0.0,
        event_rate=0.012,
        event_width=2,
        event_value=25.0,
    ),
)


#: 产出点的三种形态。
KIND_VALUE = "value"
#: 断流 —— 这个点**不存在**（不落库）。
KIND_GAP = "gap"
#: 值缺失 —— 行存在但值为 NULL。
KIND_NULL = "null"


@dataclass
class SeriesState:
    """一条曲线的递推状态（AR(1) 的上一个**噪声分量**）。"""

    spec: SeriesSpec
    #: 上一个点的噪声分量（不含基线）。
    noise: float = 0.0


def _event_uniform(name: str, index: int) -> float:
    """第 `index` 点的确定性伪随机数（`[0, 1)` 均匀分布）。

    ⚠️ **用 crc32 而不是 numpy 的 rng** —— 这个函数每个点要被调用
       `event_width` 次（判断事件窗口），`default_rng` 的构造开销太大。
       crc32 是 C 实现，快两个数量级。

    ⚠️ 与 `innovation()` 的噪声**完全独立** —— 两者的取值来源不同，
       不会互相干扰（否则噪声会「恰好」和事件重合）。
    """
    digest = zlib.crc32(f"{name}:{index}".encode())
    return (digest % 1_000_000) / 1_000_000


def _is_raw_event_start(spec: SeriesSpec, index: int) -> bool:
    """第 `index` 点是否是稀疏事件的**候选**起点。

    ⚠️ 「候选」≠「真的起点」—— 候选之间可能挨得太近，
       那会让两个事件连成一段（宽度就不再是配置的值了）。
       去重见 `_is_event_start`。
    """
    if spec.event_rate <= 0 or spec.event_width <= 0:
        return False
    if index < spec.event_width:
        return False
    return _event_uniform(f"{spec.name}#event", index) < spec.event_rate


def _is_event_start(spec: SeriesSpec, index: int) -> bool:
    """第 `index` 点是否是一个稀疏事件的**真起点**。

    ⚠️ **保证相邻的事件不重叠** —— 真起点之间至少隔 `event_width` 个点。

    做法：候选起点若与**前面 `event_width` 个点**里的候选挨着，就否决。
    ⚠️ 范围是 `width` 个点而不是 `width - 1` ——
       起点间隔 `width` 时，两个事件仍会首尾相接（连成 2×width 的一段），
       那就不是「宽度 = width」了。

    由于被否决的候选本身也会去否决更后面的候选 ——
    一串挨着的候选里**只有第一个**能活下来。

    ⚠️ 这样事件之间天然隔开，且判定仍是**纯函数**（不依赖递推状态）→
       重算同一段数据结果一致。
    """
    if not _is_raw_event_start(spec, index):
        return False
    for k in range(index - spec.event_width, index):
        if _is_raw_event_start(spec, k):
            return False
    return True


def _in_event_window(spec: SeriesSpec, index: int) -> bool:
    """第 `index` 点是否落在某个稀疏事件里。

    ⚠️ 事件覆盖 `[起点, 起点 + event_width - 1]` ——
       所以「当前点在事件里」= 「前面 `event_width` 个点里有一个起点」。
       这样判断是**纯函数**（不依赖递推状态）→ 重算同一段数据结果一致。
    """
    if spec.event_rate <= 0 or spec.event_width <= 0:
        return False
    start = index - spec.event_width + 1
    return any(
        _is_event_start(spec, k) for k in range(max(0, start), index + 1)
    )


def _baseline(spec: SeriesSpec, index: int) -> float:
    """第 `index` 点的基线值（含漂移，不含噪声）。"""
    if spec.baseline == "daily":
        # 日周期：0 点在谷底，周期中点在峰顶。
        phase = 2.0 * np.pi * (index % POINTS_PER_DAY) / POINTS_PER_DAY
        value = spec.level + spec.amplitude * np.sin(phase - np.pi / 2)
    elif spec.baseline == "trending":
        # ⚠️ **整条曲线都在涨**（不是一段临时漂移）——
        #    这类数据不该被「只看分位数」的检测器误报。
        value = spec.level + spec.slope * index
    elif spec.baseline == "step":
        # ⚠️ 两种跳变语义：
        #    `step_period > 0` → 每 period 点在两个水平间**切换**（持续可见）；
        #    `step_period == 0` → 第 `step_at` 点**一次性**跳变。
        if spec.step_period > 0:
            switched = (index // spec.step_period) % 2 == 1
            value = spec.level + (spec.step_delta if switched else 0.0)
        else:
            value = spec.level + (spec.step_delta if index >= spec.step_at else 0.0)
    elif spec.baseline == "sparse":
        # ⚠️ 平时是平的（`level` 通常取 0），偶尔冒一个脉冲。
        #    事件高度是**绝对值** —— 基线为 0 时乘法没意义。
        value = spec.level + (
            spec.event_value if _in_event_window(spec, index) else 0.0
        )
    else:
        value = spec.level
    if spec.drift_span > 0 and index >= spec.drift_from:
        progress = min(1.0, (index - spec.drift_from) / spec.drift_span)
        value += spec.drift_amount * progress
    return float(value)


def _is_gap(spec: SeriesSpec, index: int) -> bool:
    """第 `index` 点是否落在断流窗口里（该点**不产生**）。"""
    return spec.gap_len > 0 and spec.gap_from <= index < spec.gap_from + spec.gap_len


def _is_spike(spec: SeriesSpec, index: int) -> bool:
    """第 `index` 点是否落在尖峰窗口里。

    ⚠️ **从第一个完整周期开始**（`index >= spike_every`）——
       否则 index 0 就是尖峰，序列一开头就异常，看着像数据坏了。
    """
    if spec.spike_every <= 0 or index < spec.spike_every:
        return False
    return index % spec.spike_every < spec.spike_width


def _is_null(spec: SeriesSpec, index: int) -> bool:
    """第 `index` 点是否是「值缺失」（有行但值为 NULL）。"""
    return spec.null_every > 0 and index > 0 and index % spec.null_every == 0


def innovation(spec: SeriesSpec, index: int) -> float:
    """第 `index` 点的创新项（白噪声）。

    ⚠️ 确定性 —— 同一个 `(spec.name, index)` 永远给同一个值。
    """
    rng = np.random.default_rng([_stable_seed(spec.name), index % (2**32)])
    return float(rng.normal(0.0, spec.sigma))


def value_at(spec: SeriesSpec, index: int, previous_noise: float) -> float:
    """第 `index` 点的值。

    ⚠️ **不递推** —— AR(1) 的递推在 `Generator` 里做。
       这里只算「给定前一点的噪声分量」的结果。

    ⚠️ AR(1) 只作用于**噪声分量** —— 若把整条曲线的上一个值喂回去，
       基线的漂移会被当成噪声累积，漂移曲线会失控。
    """
    baseline = _baseline(spec, index)
    noise = spec.phi * previous_noise + innovation(spec, index)
    if _is_spike(spec, index):
        # ⚠️ 尖峰放大的是**基线**，不是噪声 ——
        #    放大噪声的话，噪声为 0 时尖峰根本看不见（0 × 3 还是 0）。
        return float(baseline * spec.spike_gain + noise)
    return float(baseline + noise)


class Generator:
    """按时间顺序造数的状态机。

    ⚠️ **只能顺序推进** —— AR(1) 依赖前一点的噪声。
       重启后要续上，得先补算到目标 index（`advance_to`）。
    """

    def __init__(self, series: tuple[SeriesSpec, ...] = SERIES) -> None:
        self._specs = series
        self._states: dict[str, SeriesState] = {
            spec.name: SeriesState(spec=spec) for spec in series
        }
        self._index = 0

    @property
    def index(self) -> int:
        """已经算到第几个点。"""
        return self._index

    @property
    def series_names(self) -> list[str]:
        return [spec.name for spec in self._specs]

    def advance_to(self, target_index: int) -> list[tuple[str, int, float | None, str]]:
        """推进到 `target_index`（不含），返回这批新点。

        返回的元组是 `(series_name, index, value, kind)`；
        `kind` 说明这个点是什么 —— `value`（正常）/ `gap`（断流，不落库）/
        `null`（有行但值为 NULL）。

        ⚠️ **不落库的行也照样推进状态之外的东西** ——
           调用方按 `kind` 决定写不写，但造数本身必须走完，
           否则不同序列的 index 会错位。
        """
        if target_index < self._index:
            raise ValueError(
                f"造数器只能向前推进（当前 {self._index}，目标 {target_index}）"
            )
        produced: list[tuple[str, int, float | None, str]] = []
        while self._index < target_index:
            index = self._index
            for spec in self._specs:
                if _is_gap(spec, index):
                    # ⚠️ 断流 = 不产生这个点 —— AR(1) 的状态**不推进**，
                    #    否则「没数据」会被当成一次真实的观测。
                    produced.append((spec.name, index, None, KIND_GAP))
                    continue
                state = self._states[spec.name]
                value = value_at(spec, index, state.noise)
                state.noise = value - _baseline(spec, index)
                if _is_null(spec, index):
                    produced.append((spec.name, index, None, KIND_NULL))
                else:
                    produced.append((spec.name, index, value, KIND_VALUE))
            self._index += 1
        return produced


def series_at(spec: SeriesSpec, count: int) -> list[float | None]:
    """算一条曲线的前 `count` 个点（测试用）。

    ⚠️ 断流与值缺失的点都返回 `None`。
    """
    generator = Generator((spec,))
    return [value for _, _, value, _ in generator.advance_to(count)]


def spec_fingerprint() -> str:
    """序列定义的指纹 —— 改了定义却用旧 db，数据会**悄悄对不上**。

    ⚠️ 为什么要指纹：db 里存的是**按旧定义造出来的历史数据**。
       改了曲线定义（比如加了一条新曲线）之后，
       旧 db 里没有新曲线的历史、新曲线的 index 也对不齐 ——
       这种错位**不会报错**，只会让图看起来莫名其妙。

       所以：指纹对不上就**明确报错**，让人删掉 db 重造。
    """
    payload = json.dumps(
        [dataclasses.asdict(spec) for spec in SERIES], sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
