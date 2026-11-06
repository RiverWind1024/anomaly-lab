"""进程与存储的采样，作为 OTel ObservableGauge 的回调。

⚠️ 不需要自己的采样线程 —— `PeriodicExportingMetricReader` 每次 collect
   都会调用回调，由它驱动采样频率。
⚠️ 必须带缓存：5 个 gauge 会在同一轮 collect 里各调一次回调，
   每次遍历 run 目录（几千个文件）会白白拖慢导出。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SystemStats:
    """一次系统采样的结果；取不到的项是 None（不编造 0）。"""

    cpu_percent: float | None = None
    memory_mb: float | None = None
    db_bytes: int | None = None
    runs_bytes: int | None = None
    runs_count: int | None = None


def _read_memory_mb() -> float | None:
    """进程常驻内存（MB）。优先读 /proc，跨平台时退到 rusage。"""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage / 1024.0 if os.uname().sysname == "Linux" else usage / (1024.0 * 1024.0)
    except (ImportError, OSError, ValueError):
        return None


def _dir_usage(path: Path) -> tuple[int, int]:
    """目录占用（字节, 文件数）。目录不存在时返回 (0, 0)。"""
    if not path.is_dir():
        return 0, 0
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
                count += 1
            except OSError:
                continue
    return total, count


class SystemSampler:
    """CPU / 内存 / 存储采样器，带短缓存。

    ⚠️ CPU 用「两次采样之间的进程 CPU 时间 ÷ 墙钟时间」——
       不是整机 CPU，也不是 `psutil`（避免多一个依赖）。
    """

    def __init__(
        self,
        data_root: Path,
        runs_dir: Path | None = None,
        cache_seconds: float = 5.0,
    ) -> None:
        self.data_root = Path(data_root)
        self.runs_dir = runs_dir or (self.data_root / "cache" / "platform" / "runs")
        self.cache_seconds = max(0.0, float(cache_seconds))
        self._last_cpu = time.process_time()
        self._last_wall = time.monotonic()
        self._cached_at = 0.0
        self._cached: SystemStats | None = None

    def snapshot(self) -> SystemStats:
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self.cache_seconds:
            return self._cached

        cpu = time.process_time()
        elapsed = now - self._last_wall
        cpu_percent = (cpu - self._last_cpu) / elapsed * 100.0 if elapsed > 0 else None
        self._last_cpu = cpu
        self._last_wall = now

        db_path = self.data_root / "platform.db"
        try:
            db_bytes = db_path.stat().st_size
        except OSError:
            db_bytes = None

        runs_bytes, runs_count = _dir_usage(self.runs_dir)

        self._cached = SystemStats(
            cpu_percent=max(0.0, cpu_percent) if cpu_percent is not None else None,
            memory_mb=_read_memory_mb(),
            db_bytes=db_bytes,
            runs_bytes=runs_bytes,
            runs_count=runs_count,
        )
        self._cached_at = now
        return self._cached


#: gauge 名 → 从 SystemStats 取哪个字段。
SYSTEM_GAUGES: tuple[tuple[str, str], ...] = (
    ("process.cpu_percent", "cpu_percent"),
    ("process.memory_mb", "memory_mb"),
    ("storage.db_bytes", "db_bytes"),
    ("storage.runs_bytes", "runs_bytes"),
    ("storage.runs_count", "runs_count"),
)


def register_system_gauges(meter, sampler: SystemSampler) -> None:
    """把系统指标注册成 ObservableGauge。

    ⚠️ 取不到值时**不 yield** —— 上报 0 会被读成「CPU 占用 0%」，
       而真相是「这次没采到」。
    """
    from opentelemetry.metrics import Observation

    for name, field in SYSTEM_GAUGES:
        def callback(_options, _field=field):
            value = getattr(sampler.snapshot(), _field)
            if value is not None:
                yield Observation(float(value))

        meter.create_observable_gauge(name, callbacks=[callback])
