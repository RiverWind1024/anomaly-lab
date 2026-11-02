"""造数器：4 条确定性曲线，带尖峰 / 漂移 / 断流 / 值缺失。

⚠️ **确定性是硬要求** —— 同一 seed 造两次必须完全一样，
   否则测试没法断言、演示也没法复现。

做法：每点的「创新项」由 `np.random.default_rng([seed, index])` 取
（同一 index 恒等），基线与异常注入是纯函数，AR(1) 递推给出连续抖动。
不能用全局 RNG —— 它的状态依赖调用顺序，不满足「按 index 求值」。

⚠️ **不能用内置 `hash()`** —— 字符串的 hash 被 PYTHONHASHSEED 随机化，
   换个进程就变了。这里用 `zlib.crc32`（稳定）。
"""

from __future__ import annotations

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
    #: 基线类型：`constant` 或 `daily`（每天一个波峰）。
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


#: 四条曲线的规格 —— 见 spec §5.1。
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


def _baseline(spec: SeriesSpec, index: int) -> float:
    """第 `index` 点的基线值（含漂移，不含噪声）。"""
    if spec.baseline == "daily":
        # 日周期：0 点在谷底，周期中点在峰顶。
        phase = 2.0 * np.pi * (index % POINTS_PER_DAY) / POINTS_PER_DAY
        value = spec.level + spec.amplitude * np.sin(phase - np.pi / 2)
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
