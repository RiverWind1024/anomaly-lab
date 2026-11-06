"""进程内指标注册表：累计计数 + 按分钟的历史快照。

为什么要有这一层，而不是直接读 OTel 的 reader：

- OTel 的 counter / histogram 是**累计量**，本地监控页要的是「最近 N 分钟
  每分钟各发生了多少」。差值必须有人来算，而且要有地方放历史。
- OTel 的 metric reader 是给导出器用的，没有「按分钟切片」的语义。

⚠️ 这一层**不替代** OTel：埋点入口是 `Observability`，它把同一次记录同时
   写进这里（本地页读）和 OTel instruments（导出到 Collector / Grafana）。
   两边的埋点只有一处，不会漂移。
"""

from __future__ import annotations

import bisect
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

#: 耗时直方图的桶上界（毫秒）。
#:
#: ⚠️ 跨越 1ms ~ 5min，因为同一套桶要同时装下「接口 3ms」和「Chronos 单条 300ms」
#:    以及「一次任务几十秒」。桶太密会让 ring buffer 变重，太疏分位数就是瞎猜。
DURATION_BUCKETS_MS: tuple[float, ...] = (
    1.0,
    2.0,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,
    300_000.0,
)

#: 每分钟历史里保留哪些累计指标（其余只留累计值，避免 ring buffer 膨胀）。
TIMELINE_COUNTERS: frozenset[str] = frozenset(
    {"http.requests", "http.errors", "job.runs", "alerts.fired"}
)
TIMELINE_HISTOGRAMS: frozenset[str] = frozenset({"http.request_ms"})


def flat_key(name: str, labels: dict[str, str] | None = None) -> str:
    """`http.requests` + `{method: GET}` → `http.requests|{"method":"GET"}`。

    ⚠️ 标签值里可能有 `{` / `}`（路由模板 `/jobs/{job_id}`），
       所以不能用 `name{key=value}` 这种格式 —— 解析时会被模板的花括号劈开。
       JSON 让值天然安全。

    ⚠️ 标签按 key 排序 —— 同样的标签换个顺序必须是同一个 key，
       否则同一个指标会被拆成两条。
    """
    if not labels:
        return name
    import json

    return f"{name}|{json.dumps(dict(sorted(labels.items())), ensure_ascii=False)}"


def parse_key(key: str) -> tuple[str, dict[str, str]]:
    """`flat_key` 的逆运算；没有标签时返回空 dict。"""
    name, sep, payload = key.partition("|")
    if not sep:
        return name, {}
    import json

    try:
        labels = json.loads(payload)
    except ValueError:
        return key, {}
    return name, {str(k): str(v) for k, v in labels.items()}


@dataclass
class SystemStats:
    """一次系统采样的结果；取不到的项是 None（不编造 0）。"""

    cpu_percent: float | None = None
    memory_mb: float | None = None
    db_bytes: int | None = None
    runs_bytes: int | None = None
    runs_count: int | None = None


@dataclass
class MinutePoint:
    """一分钟的增量快照。"""

    at: datetime
    counters: dict[str, float] = field(default_factory=dict)
    histograms: dict[str, float] = field(default_factory=dict)
    #: 每分钟的**总体** HTTP 延迟分位（毫秒）。
    #: 路由级分位在接口表里用累计直方图算，这里只关心整体趋势。
    latency: dict[str, float] = field(default_factory=dict)
    system: SystemStats = field(default_factory=SystemStats)


@dataclass
class _HistogramData:
    counts: list[int]
    total: float
    count: int

    @classmethod
    def empty(cls) -> _HistogramData:
        return cls([0] * len(DURATION_BUCKETS_MS), 0.0, 0)

    def bucket_index(self, value: float) -> int:
        index = bisect.bisect_left(DURATION_BUCKETS_MS, value)
        return min(index, len(DURATION_BUCKETS_MS) - 1)


def percentile(counts: Iterable[int], count: int, quantile: float) -> float | None:
    """直方图近似分位：在命中的桶里做线性插值。

    ⚠️ 只返回桶上界会让「平均 11ms」的请求显示成 P95=25ms —— 看着像两个数量级。
       桶内均匀分布的假设不精确，但比直接取上界贴近真实值。
       真实分位要存每个样本，内存随请求量线性涨，不值得。
    """
    if count <= 0:
        return None
    target = quantile * count
    cumulative = 0
    lower = 0.0
    for upper, bucket in zip(DURATION_BUCKETS_MS, counts):
        if bucket and cumulative + bucket >= target:
            position = (target - cumulative) / bucket
            return lower + (upper - lower) * min(1.0, max(0.0, position))
        cumulative += bucket
        lower = upper
    return float(DURATION_BUCKETS_MS[-1])


class MetricsRegistry:
    """线程安全的指标容器。

    ⚠️ 必须加锁：HTTP 请求线程、调度线程、60 秒采样线程会同时写。
       RLock 是因为 `take_snapshot` 会读自己写的那些表。
    """

    def __init__(self, max_points: int = 360) -> None:
        self._lock = threading.RLock()
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, _HistogramData] = {}
        self._gauges: dict[str, float] = {}
        self._points: deque[MinutePoint] = deque(maxlen=max(1, int(max_points)))
        self._prev_counters: dict[str, float] = {}
        self._prev_histograms: dict[str, _HistogramData] = {}
        self._snapshot_at: datetime | None = None

    # ── 写入 ────────────────────────────────────────────────

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = flat_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        """记录一个耗时 / 数值样本（毫秒）。"""
        key = flat_key(name, labels)
        sample = float(value)
        with self._lock:
            data = self._histograms.get(key)
            if data is None:
                data = _HistogramData.empty()
                self._histograms[key] = data
            data.counts[data.bucket_index(sample)] += 1
            data.total += sample
            data.count += 1

    def gauge(self, name: str, value: float, **labels: str) -> None:
        key = flat_key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def inc_gauge(self, name: str, delta: float = 1.0, **labels: str) -> None:
        """增减型 gauge（进行中请求数这类）。

        ⚠️ 「读出来 +1 再写回去」在并发下会丢计数，所以增减必须原子。
        """
        key = flat_key(name, labels)
        with self._lock:
            self._gauges[key] = self._gauges.get(key, 0.0) + float(delta)

    # ── 读取 ────────────────────────────────────────────────

    def counter(self, name: str, **labels: str) -> float:
        with self._lock:
            return self._counters.get(flat_key(name, labels), 0.0)

    def gauge_value(self, name: str, **labels: str) -> float | None:
        with self._lock:
            return self._gauges.get(flat_key(name, labels))

    def gauge_with_prefix(self, prefix: str) -> dict[str, float]:
        with self._lock:
            return {key: value for key, value in self._gauges.items() if key.startswith(prefix)}

    def counter_with_prefix(self, prefix: str) -> dict[str, float]:
        with self._lock:
            return {
                key: value for key, value in self._counters.items() if key.startswith(prefix)
            }

    def histogram_with_prefix(self, prefix: str) -> dict[str, dict]:
        """按标签前缀导出直方图摘要（count / avg / p50 / p95 / p99）。"""
        with self._lock:
            items = [
                (key, data) for key, data in self._histograms.items() if key.startswith(prefix)
            ]
        result: dict[str, dict] = {}
        for key, data in items:
            result[key] = {
                "count": data.count,
                "total_ms": data.total,
                "avg_ms": (data.total / data.count) if data.count else None,
                "p50_ms": percentile(data.counts, data.count, 0.50),
                "p95_ms": percentile(data.counts, data.count, 0.95),
                "p99_ms": percentile(data.counts, data.count, 0.99),
            }
        return result

    def points(self) -> list[MinutePoint]:
        with self._lock:
            return list(self._points)

    # ── 采样 ────────────────────────────────────────────────

    def take_snapshot(self, now: datetime, system: SystemStats) -> MinutePoint:
        """把累计值差成本分钟的增量，推进 ring buffer。"""
        with self._lock:
            counters: dict[str, float] = {}
            for key, value in self._counters.items():
                name, _ = parse_key(key)
                if name not in TIMELINE_COUNTERS:
                    continue
                delta = value - self._prev_counters.get(key, 0.0)
                if delta:
                    counters[key] = delta

            histograms: dict[str, float] = {}
            merged_latency = [0] * len(DURATION_BUCKETS_MS)
            merged_count = 0
            for key, data in self._histograms.items():
                name, _ = parse_key(key)
                if name not in TIMELINE_HISTOGRAMS:
                    continue
                previous = self._prev_histograms.get(key)
                if previous is None:
                    current = _HistogramData(list(data.counts), data.total, data.count)
                else:
                    current = _HistogramData(
                        [
                            value - base
                            for value, base in zip(data.counts, previous.counts, strict=True)
                        ],
                        data.total - previous.total,
                        data.count - previous.count,
                    )
                if current.count:
                    histograms[key] = current.total
                    if name == "http.request_ms":
                        for index, bucket in enumerate(current.counts):
                            merged_latency[index] += bucket
                        merged_count += current.count

            latency: dict[str, float] = {}
            if merged_count:
                latency = {
                    "p50": percentile(merged_latency, merged_count, 0.50) or 0.0,
                    "p95": percentile(merged_latency, merged_count, 0.95) or 0.0,
                    "p99": percentile(merged_latency, merged_count, 0.99) or 0.0,
                }

            point = MinutePoint(
                at=now,
                counters=counters,
                histograms=histograms,
                latency=latency,
                system=system,
            )
            self._points.append(point)
            self._prev_counters = dict(self._counters)
            self._prev_histograms = {
                key: _HistogramData(list(data.counts), data.total, data.count)
                for key, data in self._histograms.items()
            }
            self._snapshot_at = now
            return point

    @property
    def snapshot_at(self) -> datetime | None:
        with self._lock:
            return self._snapshot_at

    def reset(self) -> None:
        """测试用：清空所有状态。"""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()
            self._points.clear()
            self._prev_counters.clear()
            self._prev_histograms.clear()
            self._snapshot_at = None
