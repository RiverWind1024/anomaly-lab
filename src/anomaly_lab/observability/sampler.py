"""系统与存储的周期性采样。

⚠️ 放在后台线程里跑，**不在请求路径上**：
   遍历 run 目录（几千个）要几百毫秒，挂到任何一个 API 上都会拖慢它。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from anomaly_lab.observability.registry import MetricsRegistry, SystemStats

logger = logging.getLogger(__name__)

#: 采样间隔（秒）。一分钟足够看趋势，也让 ring buffer 只占几百个点。
DEFAULT_INTERVAL_SECONDS = 60.0

#: 默认保留多少个点（360 × 60s = 6 小时）。
DEFAULT_MAX_POINTS = 360


def _read_memory_mb() -> float | None:
    """进程常驻内存（MB）。优先读 /proc，跨平台时退到 rusage。"""
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    # 形如 "VmRSS:     123456 kB"
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux 是 KB，macOS 是字节
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
    """CPU / 内存 / 存储的采样器。

    ⚠️ CPU 用「两次采样之间的进程 CPU 时间 ÷ 墙钟时间」——
       不是 `psutil.cpu_percent()`，因为那需要额外依赖，而且进程 CPU
       比整机 CPU 更贴近「这个服务花了多少」。
    """

    def __init__(self, data_root: Path, runs_dir: Path | None = None) -> None:
        self.data_root = Path(data_root)
        self.runs_dir = runs_dir or (self.data_root / "cache" / "platform" / "runs")
        self._last_cpu = time.process_time()
        self._last_wall = time.monotonic()

    def sample(self) -> SystemStats:
        wall = time.monotonic()
        cpu = time.process_time()
        elapsed = wall - self._last_wall
        cpu_percent = (cpu - self._last_cpu) / elapsed * 100.0 if elapsed > 0 else None
        self._last_cpu = cpu
        self._last_wall = wall

        db_path = self.data_root / "platform.db"
        try:
            db_bytes = db_path.stat().st_size
        except OSError:
            db_bytes = None

        runs_bytes, runs_count = _dir_usage(self.runs_dir)

        return SystemStats(
            cpu_percent=max(0.0, cpu_percent) if cpu_percent is not None else None,
            memory_mb=_read_memory_mb(),
            db_bytes=db_bytes,
            runs_bytes=runs_bytes,
            runs_count=runs_count,
        )


class SnapshotLoop:
    """每 N 秒把累计指标差成增量，推进 ring buffer。"""

    def __init__(
        self,
        registry: MetricsRegistry,
        sampler: SystemSampler,
        interval: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self.registry = registry
        self.sampler = sampler
        self.interval = max(1.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def tick(self, now: datetime | None = None) -> None:
        """采一次样。**同步**，测试直接调这个，不用等线程。"""
        from anomaly_lab.platform.timeutil import utcnow

        with self._lock:
            stats = self.sampler.sample()
            if stats.cpu_percent is not None:
                self.registry.gauge("process.cpu_percent", stats.cpu_percent)
            if stats.memory_mb is not None:
                self.registry.gauge("process.memory_mb", stats.memory_mb)
            if stats.db_bytes is not None:
                self.registry.gauge("storage.db_bytes", stats.db_bytes)
            if stats.runs_bytes is not None:
                self.registry.gauge("storage.runs_bytes", stats.runs_bytes)
                self.registry.gauge("storage.runs_count", stats.runs_count or 0)
            self.registry.take_snapshot(now or utcnow(), stats)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        # 先采一次，页面第一秒就有点可看，不用等 60 秒。
        try:
            self.tick()
        except Exception:
            logger.exception("监控采样初始化失败")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="anomaly-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:
                # ⚠️ 一次采样失败不该把线程带走 —— 否则监控页从此不再更新，
                #    而且没有任何提示。
                logger.exception("监控采样失败")
