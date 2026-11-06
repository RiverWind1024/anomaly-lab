"""服务自身可观测性：OpenTelemetry 埋点 + 本地 SQLite 历史。

架构（这也是标准的 OTel 用法）：

```
埋点（中间件 / runner / scheduler）
        ↓ 只调用 OTel API
    MeterProvider
    ├── PeriodicExportingMetricReader(SqliteMetricExporter)  → metrics.db（30 天）
    └── PeriodicExportingMetricReader(OTLPMetricExporter)    → 外部后端（可选）
```

⚠️ 埋点只有一处，两个 reader 消费同一份数据。
   不要另建一套内存注册表 —— 那样监控页和 Grafana 的数字迟早对不上。
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from anomaly_lab.observability.buckets import DURATION_BUCKETS_MS, percentile
from anomaly_lab.observability.sqlite_exporter import (
    MetricsStore,
    SqliteMetricExporter,
)
from anomaly_lab.observability.system import (
    SYSTEM_GAUGES,
    SystemSampler,
    SystemStats,
    register_system_gauges,
)
from anomaly_lab.platform.timeutil import utcnow

logger = logging.getLogger(__name__)

__all__ = [
    "DURATION_BUCKETS_MS",
    "MetricsStore",
    "Observability",
    "SystemStats",
    "configure_observability",
    "get_observability",
    "percentile",
    "reset_observability",
]

#: 指标名 → 说明。统一声明，避免各处手写字符串拼错。
INSTRUMENTS: dict[str, str] = {
    "http.requests": "HTTP 请求数",
    "http.errors": "HTTP 5xx 响应数",
    "http.request_ms": "HTTP 请求耗时（毫秒）",
    "job.runs": "任务运行次数",
    "job.duration_ms": "任务总耗时（毫秒）",
    "job.stage_ms": "任务阶段耗时（毫秒）",
    "detector.calls": "检测器调用次数",
    "detector.duration_ms": "单条序列的检测耗时（毫秒）",
    "scheduler.ticks": "调度器 tick 次数",
    "scheduler.tick_ms": "调度器 tick 耗时（毫秒）",
    "scheduler.due_jobs": "本次到期任务数",
    "scheduler.last_tick_at": "最后一次 tick 的时间戳",
    "scheduler.prune_ms": "数据保留清理耗时（毫秒）",
    "alerts.fired": "报出的告警区间数",
}

#: 需要自定义桶的耗时指标（默认桶对 0.2ms 与 30s 都不合适）。
_TIMED = tuple(name for name in INSTRUMENTS if name.endswith("_ms"))

#: 需要瞬时值的指标（不走 counter）。
GAUGE_METRICS: frozenset[str] = frozenset(
    {"scheduler.due_jobs", "scheduler.last_tick_at"}
)

#: 系统类 gauge 由 ObservableGauge 回调上报，不在这里创建 instrument。
SYSTEM_GAUGE_NAMES: frozenset[str] = frozenset(name for name, _ in SYSTEM_GAUGES)

#: 全局 provider 只能设置一次（OTel 的限制），测试里反复建 app 不会打架。
_GLOBAL_METRICS_SET = False
_GLOBAL_TRACE_SET = False


def _normalize_endpoint(endpoint: str, suffix: str) -> str:
    """允许只写 `http://host:4318`，自动补 exporter 需要的路径。"""
    base = endpoint.rstrip("/")
    return base if base.endswith(suffix) else f"{base}{suffix}"


class Observability:
    """埋点 facade；对外的 `inc / observe_ms / gauge / timer / span` 就够用。"""

    def __init__(
        self,
        *,
        service_name: str = "anomaly-lab",
        data_root: Path | None = None,
        endpoint: str | None = None,
        export_interval_seconds: float = 15.0,
        retention_days: int = 30,
        enable: bool = True,
    ) -> None:
        self.service_name = service_name
        self.endpoint = endpoint
        self.export_interval_seconds = max(1.0, float(export_interval_seconds))
        self.retention_days = max(1, int(retention_days))
        self.started_at = utcnow()
        self.data_root = Path(data_root or Path("data"))
        # 监控库默认跟数据目录走；`ANOMALY_MONITOR_DB` 可以单独指定
        # （测试用它把库重定向到 tmp，避免污染仓库里的 data/）。
        self.metrics_db = Path(
            os.environ.get("ANOMALY_MONITOR_DB") or (self.data_root / "metrics.db")
        )
        #: 只有显式 `configure_observability()` 创建的实例才算「已配置」。
        #: 没有配置时埋点是 no-op，避免测试或一次性脚本往仓库里写 metrics.db。
        self.configured = enable
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._provider: Any = None
        self._tracer_provider: Any = None
        self._readers: list[Any] = []
        self.tracer: Any = None
        self.enabled = False
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._gauges: dict[str, Any] = {}
        if enable:
            self._initialize()

    # ── OTel 初始化 ─────────────────────────────────────────

    def _initialize(self) -> None:
        try:
            from opentelemetry import metrics
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.metrics.view import (
                ExplicitBucketHistogramAggregation,
                View,
            )
            from opentelemetry.sdk.resources import Resource
        except ImportError:
            logger.warning("未安装 opentelemetry-sdk，监控不可用")
            return

        resource = Resource.create({"service.name": self.service_name})
        try:
            self.metrics_db.parent.mkdir(parents=True, exist_ok=True)
            sqlite_exporter = SqliteMetricExporter(
                self.metrics_db, retention_days=self.retention_days
            )
        except Exception:
            logger.exception("初始化监控库失败（%s），监控页将没有数据", self.metrics_db)
            return

        readers = [
            PeriodicExportingMetricReader(
                sqlite_exporter,
                export_interval_millis=self.export_interval_seconds * 1000,
            )
        ]
        if self.endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                )

                readers.append(
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(
                            endpoint=_normalize_endpoint(self.endpoint, "/v1/metrics")
                        ),
                        export_interval_millis=self.export_interval_seconds * 1000,
                    )
                )
                self.enabled = True
            except ImportError:
                logger.warning(
                    "配了 ANOMALY_OTEL_ENDPOINT 但没装 OTLP exporter；"
                    "执行 `pip install -e '.[otel]'` 后重启"
                )

        views = [
            View(
                instrument_name=name,
                aggregation=ExplicitBucketHistogramAggregation(
                    boundaries=list(DURATION_BUCKETS_MS)
                ),
            )
            for name in _TIMED
        ]
        self._provider = MeterProvider(
            resource=resource, metric_readers=readers, views=views
        )
        self._readers = readers
        global _GLOBAL_METRICS_SET
        if not _GLOBAL_METRICS_SET:
            metrics.set_meter_provider(self._provider)
            _GLOBAL_METRICS_SET = True
        meter = self._provider.get_meter("anomaly_lab")

        for name in INSTRUMENTS:
            if name in _TIMED:
                self._histograms[name] = meter.create_histogram(name, unit="ms")
            elif name in GAUGE_METRICS:
                self._gauges[name] = meter.create_gauge(name)
            elif name in SYSTEM_GAUGE_NAMES:
                # 系统类 gauge 由 ObservableGauge 回调上报，不建同步 instrument
                continue
            else:
                self._counters[name] = meter.create_counter(name)

        register_system_gauges(meter, SystemSampler(self.data_root))

        if self.endpoint:
            self._setup_tracing(resource)

    def _setup_tracing(self, resource: Any) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            self._tracer_provider = TracerProvider(resource=resource)
            self._tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=_normalize_endpoint(self.endpoint or "", "/v1/traces")
                    )
                )
            )
            global _GLOBAL_TRACE_SET
            if not _GLOBAL_TRACE_SET:
                trace.set_tracer_provider(self._tracer_provider)
                _GLOBAL_TRACE_SET = True
            self.tracer = self._tracer_provider.get_tracer("anomaly_lab")
        except ImportError:
            logger.warning("没装 OTLP trace exporter，链路不会导出")

    # ── 写入 ────────────────────────────────────────────────

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        instrument = self._counters.get(name)
        if instrument is None:
            return
        instrument.add(float(value), _attributes(labels))

    def observe_ms(self, name: str, value: float, **labels: str) -> None:
        instrument = self._histograms.get(name)
        if instrument is None:
            return
        instrument.record(float(value), _attributes(labels))

    def gauge(self, name: str, value: float, **labels: str) -> None:
        instrument = self._gauges.get(name)
        if instrument is None:
            meter = self._provider.get_meter("anomaly_lab") if self._provider else None
            if meter is None:
                return
            instrument = meter.create_gauge(name)
            self._gauges[name] = instrument
        instrument.set(float(value), _attributes(labels))

    def inflight_add(self, delta: float) -> int:
        """进行中请求数 —— 瞬时值，不进历史指标，由 API 直接读。"""
        with self._inflight_lock:
            self._inflight = max(0, self._inflight + int(delta))
            return self._inflight

    @contextmanager
    def timer(self, name: str, **labels: str) -> Iterator[None]:
        """记录一段代码的耗时（毫秒）。异常也记账，调用方自己标 status。"""
        import time as _time

        started = _time.perf_counter()
        try:
            yield
        finally:
            self.observe_ms(name, (_time.perf_counter() - started) * 1000.0, **labels)

    @contextmanager
    def span(self, name: str, **labels: str) -> Iterator[None]:
        """OTel 链路 span；没配导出时是空操作。"""
        if self.tracer is None:
            yield None
            return
        with self.tracer.start_as_current_span(name, attributes=_attributes(labels)):
            yield None

    # ── 生命周期 ────────────────────────────────────────────

    def start(self) -> None:
        """reader 线程在创建时已启动，这里保留接口给 lifespan 调用。"""

    def stop(self) -> None:
        """不 shutdown provider —— 测试会反复建 app，provider 只能关一次。

        进程退出时的 flush 走 `shutdown()`（CLI 里注册到 atexit）。
        """

    def shutdown(self) -> None:
        if self._provider is not None:
            try:
                self._provider.shutdown()
            except Exception:
                logger.exception("关闭 OTel provider 失败")
            self._provider = None
        if self._tracer_provider is not None:
            try:
                self._tracer_provider.shutdown()
            except Exception:
                logger.exception("关闭 OTel tracer 失败")
            self._tracer_provider = None

    def force_flush(self) -> None:
        """测试 / 关停前用：先让 reader 收集，再把**当前分钟**也落库。"""
        for reader in self._readers:
            try:
                reader.force_flush()
                exporter = getattr(reader, "_exporter", None)
                if exporter is not None:
                    exporter.force_flush()
            except Exception:
                logger.exception("flush 失败")

    def store(self) -> MetricsStore:
        return MetricsStore(self.metrics_db)

    def info(self) -> dict:
        now = utcnow()
        return {
            "service_name": self.service_name,
            "pid": os.getpid(),
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "uptime_seconds": max(0.0, (now - self.started_at).total_seconds()),
            "otel_enabled": self.enabled,
            "otel_endpoint": self.endpoint or "",
            "export_interval_seconds": self.export_interval_seconds,
            "retention_days": self.retention_days,
            "metrics_db": str(self.metrics_db),
            "inflight": self._inflight,
        }


def _attributes(labels: dict[str, str]) -> dict[str, str]:
    """OTel 属性值必须是原始类型；空值丢掉，别写 `label=""`。"""
    return {key: str(value) for key, value in labels.items() if value not in (None, "")}


_LOCK = threading.Lock()
_INSTANCE: Observability | None = None


def configure_observability(
    *,
    service_name: str | None = None,
    endpoint: str | None = None,
    data_root: Path | None = None,
    export_interval_seconds: float | None = None,
    retention_days: int | None = None,
) -> Observability:
    """创建（或返回已有的）可观测性实例。

    ⚠️ 幂等：OTel 的全局 provider 只能设置一次，重复创建会打架。
       测试里用 `reset_observability()` 清掉单例。
    """
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None and _INSTANCE.configured:
            return _INSTANCE
        instance = Observability(
            service_name=service_name
            or os.environ.get("ANOMALY_OTEL_SERVICE_NAME", "anomaly-lab"),
            endpoint=endpoint
            if endpoint is not None
            else os.environ.get("ANOMALY_OTEL_ENDPOINT") or None,
            data_root=data_root,
            export_interval_seconds=export_interval_seconds
            if export_interval_seconds is not None
            else float(os.environ.get("ANOMALY_MONITOR_INTERVAL", "15")),
            retention_days=retention_days
            if retention_days is not None
            else int(os.environ.get("ANOMALY_MONITOR_RETENTION_DAYS", "30")),
            enable=True,
        )
        _INSTANCE = instance
        return instance


def get_observability() -> Observability:
    """拿全局实例。

    ⚠️ 没有显式配置时返回一个 **no-op** 实例（`configured=False`）——
       否则任何调用 `execute_job` 的测试都会在仓库里写出 `data/metrics.db`。
       生产入口 `create_app()` 会调用 `configure_observability()`。
    """
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = Observability(enable=False)
        return _INSTANCE


def reset_observability() -> None:
    """测试用：flush 并清掉单例。"""
    global _INSTANCE
    with _LOCK:
        instance = _INSTANCE
        _INSTANCE = None
    if instance is not None:
        instance.force_flush()
        instance.shutdown()
