"""服务自身可观测性：本地指标注册表 + OpenTelemetry 导出。

用法：

    from anomaly_lab.observability import get_observability

    obs = get_observability()
    obs.inc("job.runs", status="success")
    with obs.timer("detector.duration_ms", detector="iqr"):
        detector.detect(series)

⚠️ 埋点只写这一处 —— 同一行代码同时更新本地注册表（监控页读）
   和 OTel instruments（导出到 Collector）。不要在两处分别埋，
   否则监控页和 Grafana 的数字迟早对不上。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anomaly_lab.observability.otel import OtelBridge
from anomaly_lab.observability.registry import (
    DURATION_BUCKETS_MS,
    MetricsRegistry,
    MinutePoint,
    SystemStats,
)
from anomaly_lab.observability.sampler import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_MAX_POINTS,
    SnapshotLoop,
    SystemSampler,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DURATION_BUCKETS_MS",
    "MetricsRegistry",
    "MinutePoint",
    "Observability",
    "SystemStats",
    "configure_observability",
    "get_observability",
    "reset_observability",
]


class Observability:
    """埋点 facade。"""

    def __init__(
        self,
        *,
        service_name: str = "anomaly-lab",
        endpoint: str | None = None,
        data_root: Path | None = None,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        max_points: int = DEFAULT_MAX_POINTS,
        start_sampler: bool = False,
    ) -> None:
        self.service_name = service_name
        self.endpoint = endpoint
        from anomaly_lab.platform.timeutil import utcnow

        self.started_at = utcnow()
        self.registry = MetricsRegistry(max_points=max_points)
        self.otel = OtelBridge(
            self.registry, service_name=service_name, endpoint=endpoint
        )
        self.sampler = SystemSampler(data_root or Path("data"))
        self.loop = SnapshotLoop(self.registry, self.sampler, interval=interval)
        self._started = False
        if start_sampler:
            self.start()

    # ── 写入 ────────────────────────────────────────────────

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        self.registry.inc(name, value, **labels)
        self.otel.inc(name, value, _clean(labels))

    def observe_ms(self, name: str, value: float, **labels: str) -> None:
        self.registry.observe(name, value, **labels)
        self.otel.observe(name, value, _clean(labels))

    def gauge(self, name: str, value: float, **labels: str) -> None:
        self.registry.gauge(name, value, **labels)

    @contextmanager
    def timer(self, name: str, **labels: str) -> Iterator[None]:
        """记录一段代码的耗时（毫秒）。异常也记账，但调用方应自己标 status。"""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe_ms(name, (time.perf_counter() - started) * 1000.0, **labels)

    @contextmanager
    def span(self, name: str, **labels: str) -> Iterator[None]:
        """OTel 链路 span；没配导出时是空操作。"""
        with self.otel.span(name, _clean(labels)):
            yield

    # ── 生命周期 ────────────────────────────────────────────

    def start(self) -> None:
        if self._started:
            return
        self.loop.start()
        self._started = True

    def stop(self) -> None:
        """停掉采样线程。

        ⚠️ 不 shutdown OTel provider —— 测试里会反复建 app，
           provider 只能关一次，第二次再开始用会报错。
           进程退出时的 flush 交给 `shutdown()`。
        """
        if not self._started:
            return
        self.loop.stop()
        self._started = False

    def shutdown(self) -> None:
        self.stop()
        self.otel.shutdown()

    @property
    def sampler_running(self) -> bool:
        return self.loop.is_running

    def info(self) -> dict:
        import os as _os

        from anomaly_lab.platform.timeutil import to_iso, utcnow

        now = utcnow()
        snapshot_at = self.registry.snapshot_at
        return {
            "service_name": self.service_name,
            "pid": _os.getpid(),
            "started_at": to_iso(self.started_at),
            "uptime_seconds": max(0.0, (now - self.started_at).total_seconds()),
            "otel_enabled": self.otel.enabled,
            "otel_endpoint": self.endpoint or "",
            "sampler_running": self.sampler_running,
            "snapshot_at": to_iso(snapshot_at) if snapshot_at is not None else None,
        }


def _clean(labels: dict[str, str]) -> dict[str, str]:
    """OTel 属性值必须是原始类型；空值直接丢掉，别写 `label=""`。"""
    return {key: str(value) for key, value in labels.items() if value not in (None, "")}


_LOCK = threading.Lock()
_INSTANCE: Observability | None = None


def configure_observability(
    *,
    service_name: str | None = None,
    endpoint: str | None = None,
    data_root: Path | None = None,
    interval: float | None = None,
    max_points: int | None = None,
    start_sampler: bool = False,
) -> Observability:
    """创建（或返回已有的）可观测性实例。

    ⚠️ 幂等：OTel 的全局 provider 只能设置一次，重复创建会打架。
       测试里用 `reset_observability()` 清掉单例。
    """
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None:
            return _INSTANCE
        _INSTANCE = Observability(
            service_name=service_name
            or os.environ.get("ANOMALY_OTEL_SERVICE_NAME", "anomaly-lab"),
            endpoint=endpoint if endpoint is not None else os.environ.get("ANOMALY_OTEL_ENDPOINT") or None,
            data_root=data_root,
            interval=interval
            if interval is not None
            else float(os.environ.get("ANOMALY_MONITOR_INTERVAL", DEFAULT_INTERVAL_SECONDS)),
            max_points=max_points
            if max_points is not None
            else int(os.environ.get("ANOMALY_MONITOR_POINTS", DEFAULT_MAX_POINTS)),
            start_sampler=start_sampler,
        )
        return _INSTANCE


def get_observability() -> Observability:
    """拿全局实例；没配置过就按默认值建一个（不启动采样线程）。"""
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = Observability()
        return _INSTANCE


def reset_observability() -> None:
    """测试用：停掉线程并清空单例。"""
    global _INSTANCE
    with _LOCK:
        instance = _INSTANCE
        _INSTANCE = None
    if instance is not None:
        instance.stop()
