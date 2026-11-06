"""服务监控 API：把本地指标注册表转成页面要的形状。

⚠️ 这组端点回答的是「服务自己现在怎么样」，不是「业务数据有没有异常」——
   后者是告警与检测记录的事。不要混在一起。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import APIRouter

from anomaly_lab.observability import get_observability
from anomaly_lab.observability.registry import MetricsRegistry, parse_key
from anomaly_lab.platform.timeutil import to_iso, utcnow

#: 调度器多久没 tick 就判定为「停滞」。
#: 默认 poll 是 2 秒，30 秒是留了足够余量的保守阈值。
SCHEDULER_STALE_SECONDS = 30.0


def _groups(registry: MetricsRegistry, name: str) -> Iterator[tuple[dict[str, str], float]]:
    """按指标名取 (标签, 值)，**严格匹配名字**。

    ⚠️ 只按前缀过滤是不够的：`http.request` 会把 `http.request_ms` 也捞进来。
    """
    for key, value in registry.counter_with_prefix(name).items():
        parsed_name, labels = parse_key(key)
        if parsed_name == name:
            yield labels, value


def _histograms(registry: MetricsRegistry, name: str) -> Iterator[tuple[dict[str, str], dict]]:
    for key, summary in registry.histogram_with_prefix(name).items():
        parsed_name, labels = parse_key(key)
        if parsed_name == name:
            yield labels, summary


def _sum(registry: MetricsRegistry, name: str) -> float:
    return sum(value for _labels, value in _groups(registry, name))


def _http_table(registry: MetricsRegistry) -> dict:
    routes: dict[tuple[str, str], dict] = {}

    def entry(labels: dict[str, str]) -> dict:
        key = (labels.get("method", ""), labels.get("route", "<unmatched>"))
        return routes.setdefault(
            key,
            {
                "method": key[0],
                "route": key[1],
                "count": 0,
                "errors": 0,
                "avg_ms": None,
                "p95_ms": None,
            },
        )

    for labels, value in _groups(registry, "http.requests"):
        entry(labels)["count"] += int(value)
    for labels, value in _groups(registry, "http.errors"):
        entry(labels)["errors"] += int(value)
    for labels, summary in _histograms(registry, "http.request_ms"):
        target = entry(labels)
        target["avg_ms"] = summary["avg_ms"]
        target["p95_ms"] = summary["p95_ms"]

    rows = sorted(routes.values(), key=lambda row: row["count"], reverse=True)
    return {
        "total": int(_sum(registry, "http.requests")),
        "errors": int(_sum(registry, "http.errors")),
        "routes": rows,
    }


def _detector_table(registry: MetricsRegistry) -> list[dict]:
    detectors: dict[str, dict] = {}

    def entry(name: str) -> dict:
        return detectors.setdefault(
            name,
            {
                "detector": name,
                "calls": 0,
                "fallbacks": 0,
                "errors": 0,
                "avg_ms": None,
                "p95_ms": None,
                "p99_ms": None,
            },
        )

    for labels, value in _groups(registry, "detector.calls"):
        target = entry(labels.get("detector", "<unknown>"))
        target["calls"] += int(value)
        status = labels.get("status", "ok")
        if status == "fallback":
            target["fallbacks"] += int(value)
        elif status == "error":
            target["errors"] += int(value)

    for labels, summary in _histograms(registry, "detector.duration_ms"):
        target = entry(labels.get("detector", "<unknown>"))
        target["avg_ms"] = summary["avg_ms"]
        target["p95_ms"] = summary["p95_ms"]
        target["p99_ms"] = summary["p99_ms"]

    return sorted(detectors.values(), key=lambda row: row["calls"], reverse=True)


def _job_table(registry: MetricsRegistry) -> list[dict]:
    jobs: dict[str, dict] = {}

    def entry(name: str) -> dict:
        return jobs.setdefault(
            name,
            {"job": name, "runs": 0, "failed": 0, "insufficient": 0, "avg_ms": None, "p95_ms": None},
        )

    for labels, value in _groups(registry, "job.runs"):
        target = entry(labels.get("job", "<unknown>"))
        target["runs"] += int(value)
        status = labels.get("status", "success")
        if status == "failed":
            target["failed"] += int(value)
        elif status == "insufficient_data":
            target["insufficient"] += int(value)

    for labels, summary in _histograms(registry, "job.duration_ms"):
        target = entry(labels.get("job", "<unknown>"))
        target["avg_ms"] = summary["avg_ms"]
        target["p95_ms"] = summary["p95_ms"]

    return sorted(jobs.values(), key=lambda row: row["runs"], reverse=True)


def _stage_table(registry: MetricsRegistry) -> list[dict]:
    stages: dict[str, dict] = {}
    for labels, summary in _histograms(registry, "job.stage_ms"):
        stage = labels.get("stage", "<unknown>")
        stages[stage] = {
            "stage": stage,
            "count": summary["count"],
            "avg_ms": summary["avg_ms"],
            "p95_ms": summary["p95_ms"],
        }
    return sorted(stages.values(), key=lambda row: (row["avg_ms"] or 0), reverse=True)


def _scheduler_section(registry: MetricsRegistry) -> dict:
    last_tick = registry.gauge_value("scheduler.last_tick_at")
    alive = False
    if last_tick is not None:
        alive = (utcnow().timestamp() - last_tick) < SCHEDULER_STALE_SECONDS
    tick = next(iter(_histograms(registry, "scheduler.tick_ms")), (None, {}))[1]
    prune = next(iter(_histograms(registry, "scheduler.prune_ms")), (None, {}))[1]
    due = registry.gauge_value("scheduler.due_jobs")
    return {
        "alive": alive,
        "ticks": int(_sum(registry, "scheduler.ticks")),
        "avg_tick_ms": tick.get("avg_ms"),
        "p95_tick_ms": tick.get("p95_ms"),
        "due_jobs": int(due) if due is not None else None,
        "last_tick_at": _ts_iso(last_tick) if last_tick is not None else None,
        "avg_prune_ms": prune.get("avg_ms"),
    }


def _ts_iso(epoch_seconds: float) -> str:
    from datetime import UTC, datetime

    return to_iso(datetime.fromtimestamp(float(epoch_seconds), tz=UTC))


def _current_section(registry: MetricsRegistry) -> dict:
    def gauge(name: str):
        return registry.gauge_value(name)

    return {
        "cpu_percent": gauge("process.cpu_percent"),
        "memory_mb": gauge("process.memory_mb"),
        "db_bytes": gauge("storage.db_bytes"),
        "runs_bytes": gauge("storage.runs_bytes"),
        "runs_count": gauge("storage.runs_count"),
        "inflight": gauge("http.inflight") or 0,
        "due_jobs": gauge("scheduler.due_jobs"),
    }


def _timeline(registry: MetricsRegistry, window: int) -> list[dict]:
    points = registry.points()[-max(1, window) :]
    rows: list[dict] = []
    for point in points:
        counters = {"http.requests": 0, "http.errors": 0, "job.runs": 0, "alerts.fired": 0}
        failed = 0
        insufficient = 0
        p0 = 0
        for key, value in point.counters.items():
            name, labels = parse_key(key)
            if name in counters:
                counters[name] += int(value)
            if name == "job.runs" and labels.get("status") == "failed":
                failed += int(value)
            if name == "job.runs" and labels.get("status") == "insufficient_data":
                insufficient += int(value)
            if name == "alerts.fired" and labels.get("level") == "P0":
                p0 += int(value)
        rows.append(
            {
                "at": to_iso(point.at),
                "requests": counters["http.requests"],
                "errors": counters["http.errors"],
                "runs": counters["job.runs"],
                "failed_runs": failed,
                "insufficient_runs": insufficient,
                "alerts": counters["alerts.fired"],
                "p0": p0,
                "p50_ms": point.latency.get("p50"),
                "p95_ms": point.latency.get("p95"),
                "p99_ms": point.latency.get("p99"),
                "cpu_percent": point.system.cpu_percent,
                "memory_mb": point.system.memory_mb,
                "db_bytes": point.system.db_bytes,
                "runs_bytes": point.system.runs_bytes,
                "runs_count": point.system.runs_count,
            }
        )
    return rows


def build_observability_router(
    get_data_root: Callable[[], Path] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/platform/observability")
    def observability(window_minutes: int = 60) -> dict:
        """服务自身状态 + 最近 N 分钟的时序 + 算法/接口/任务统计。

        ⚠️ 一次请求返回全页所需 —— 监控页 15 秒刷新一次，
           拆成五个端点就是五倍请求、五倍慢查询。
        """
        obs = get_observability()
        registry = obs.registry
        window = max(1, min(int(window_minutes), 360))
        return {
            "service": obs.info(),
            "interval_seconds": obs.loop.interval,
            "current": _current_section(registry),
            "timeline": _timeline(registry, window),
            "http": _http_table(registry),
            "alerts": {
                "total": int(_sum(registry, "alerts.fired")),
                "p0": int(
                    sum(
                        value
                        for labels, value in _groups(registry, "alerts.fired")
                        if labels.get("level") == "P0"
                    )
                ),
            },
            "detectors": _detector_table(registry),
            "jobs": _job_table(registry),
            "stages": _stage_table(registry),
            "scheduler": _scheduler_section(registry),
            "otel": {
                "enabled": obs.otel.enabled,
                "endpoint": obs.endpoint or "",
                "hint": (
                    "指标与链路已按 OTLP 导出"
                    if obs.otel.enabled
                    else "未配置 ANOMALY_OTEL_ENDPOINT，指标只留在本地"
                ),
            },
        }

    return router
