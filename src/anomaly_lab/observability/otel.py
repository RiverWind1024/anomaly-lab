"""OpenTelemetry 接入：把本地埋点同时导出到标准 OTLP 端点。

设计取向：

- **默认不导出** —— 不配 `ANOMALY_OTEL_ENDPOINT` 时仍然创建真实的 OTel
  instruments，只是没有 reader，代价接近零。本地监控页照常工作。
- **导出是可选依赖** —— `pip install -e '.[otel]'` 才有 OTLP exporter。
  没装时不报错，只是日志里说一句「已禁用导出」。
- **gauge 用 observable callback 读 registry** —— CPU / 内存 / 存储这些
  「当前值」不是事件，用计数器的语义会算错；回调式 gauge 天然对。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from anomaly_lab.observability.registry import MetricsRegistry

logger = logging.getLogger(__name__)

#: OTel 的全局 provider 只能被设置一次（再设会打 warning 且不生效）。
#: 我们的 instrument 直接来自各自的 provider，所以只需要第一次设置全局即可。
_GLOBAL_METRICS_SET = False
_GLOBAL_TRACE_SET = False

#: 观测指标名 → 说明。统一在这里声明，避免各处手写字符串拼错。
INSTRUMENTS: dict[str, str] = {
    "http.requests": "HTTP 请求数",
    "http.errors": "HTTP 5xx 响应数",
    "http.request_ms": "HTTP 请求耗时（毫秒）",
    "http.inflight": "进行中的 HTTP 请求数",
    "job.runs": "任务运行次数",
    "job.stage_ms": "任务阶段耗时（毫秒）",
    "detector.calls": "检测器调用次数",
    "detector.duration_ms": "单条序列的检测耗时（毫秒）",
    "scheduler.ticks": "调度器 tick 次数",
    "scheduler.tick_ms": "调度器 tick 耗时（毫秒）",
    "scheduler.due_jobs": "本次到期任务数",
    "scheduler.prune_ms": "数据保留清理耗时（毫秒）",
    "alerts.fired": "报出的告警区间数",
}

#: 用 observable gauge 导出的「当前值」指标。
OBSERVABLE_GAUGES: tuple[str, ...] = (
    "http.inflight",
    "process.cpu_percent",
    "process.memory_mb",
    "storage.db_bytes",
    "storage.runs_bytes",
    "storage.runs_count",
    "scheduler.due_jobs",
)


def _normalize_endpoint(endpoint: str, suffix: str) -> str:
    """允许用户只写 `http://host:4318`，自动补 exporter 需要的路径。"""
    base = endpoint.rstrip("/")
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


class OtelBridge:
    """OTel instruments 的薄封装；导入失败时自动降级为空实现。"""

    def __init__(
        self,
        registry: MetricsRegistry,
        *,
        service_name: str,
        endpoint: str | None = None,
        export_interval_ms: int = 15_000,
    ) -> None:
        self.registry = registry
        self.service_name = service_name
        self.endpoint = endpoint
        self.enabled = False
        self.tracer: Any = None
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._provider: Any = None
        self._tracer_provider: Any = None
        self._initialize(endpoint, export_interval_ms)

    def _initialize(self, endpoint: str | None, export_interval_ms: int) -> None:
        try:
            from opentelemetry import metrics, trace
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
        except ImportError:
            logger.warning("未安装 opentelemetry-sdk，监控页仍可用，但不会导出 OTel 指标")
            return

        resource = Resource.create({"service.name": self.service_name})
        readers = []
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                )

                readers.append(
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(
                            endpoint=_normalize_endpoint(endpoint, "/v1/metrics")
                        ),
                        export_interval_millis=export_interval_ms,
                    )
                )
            except ImportError:
                logger.warning(
                    "配了 ANOMALY_OTEL_ENDPOINT 但没装 OTLP exporter；"
                    "执行 `pip install -e '.[otel]'` 后重启"
                )

        self._provider = MeterProvider(resource=resource, metric_readers=readers)
        global _GLOBAL_METRICS_SET
        if not _GLOBAL_METRICS_SET:
            metrics.set_meter_provider(self._provider)
            _GLOBAL_METRICS_SET = True
        meter = self._provider.get_meter("anomaly_lab")

        for name in INSTRUMENTS:
            if name in OBSERVABLE_GAUGES:
                continue
            if name.endswith("_ms"):
                self._histograms[name] = meter.create_histogram(name, unit="ms")
            else:
                self._counters[name] = meter.create_counter(name)

        for name in OBSERVABLE_GAUGES:
            meter.create_observable_gauge(
                name,
                callbacks=[self._gauge_callback(name)],
            )

        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                self._tracer_provider = TracerProvider(resource=resource)
                self._tracer_provider.add_span_processor(
                    BatchSpanProcessor(
                        OTLPSpanExporter(
                            endpoint=_normalize_endpoint(endpoint, "/v1/traces")
                        )
                    )
                )
                global _GLOBAL_TRACE_SET
                if not _GLOBAL_TRACE_SET:
                    trace.set_tracer_provider(self._tracer_provider)
                    _GLOBAL_TRACE_SET = True
                self.tracer = self._tracer_provider.get_tracer("anomaly_lab")
                self.enabled = True
            except ImportError:
                logger.warning("没装 OTLP trace exporter，链路不会导出")
        else:
            self.enabled = False

    def _gauge_callback(self, name: str):
        from opentelemetry.metrics import Observation

        def callback(_options: Any) -> Iterator[Any]:
            values = self.registry.gauge_with_prefix(name)
            for key, value in values.items():
                # 单指标无标签时 key 就是指标名
                if key == name:
                    yield Observation(value)
                    continue
                _, labels = _split_keys(key)
                yield Observation(value, labels)

        return callback

    def inc(self, name: str, value: float, labels: dict[str, str]) -> None:
        instrument = self._counters.get(name)
        if instrument is not None:
            instrument.add(value, labels or None)

    def observe(self, name: str, value: float, labels: dict[str, str]) -> None:
        instrument = self._histograms.get(name)
        if instrument is not None:
            instrument.record(value, labels or None)

    @contextmanager
    def span(self, name: str, labels: dict[str, str] | None = None) -> Iterator[Any]:
        if self.tracer is None:
            yield None
            return
        with self.tracer.start_as_current_span(name, attributes=labels or {}) as current:
            yield current

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()
        if self._tracer_provider is not None:
            self._tracer_provider.shutdown()


def _split_keys(key: str) -> tuple[str, dict[str, str]]:
    from anomaly_lab.observability.registry import parse_key

    return parse_key(key)
