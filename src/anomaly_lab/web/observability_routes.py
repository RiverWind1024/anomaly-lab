"""服务监控 API：从 SQLite 里读 OTel 导出的指标，组装成页面要的形状。

⚠️ 这里**只读** `metrics.db`，不碰平台业务库 —— 监控数据与业务数据是两套东西，
   混在一个库里会互相抢写锁。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter

from anomaly_lab.observability import get_observability
from anomaly_lab.observability.buckets import percentile
from anomaly_lab.platform.timeutil import utcnow

#: 调度器多久没导出 tick 就判定为「停滞」。
SCHEDULER_STALE_SECONDS = 45.0

#: 时间线里每个点固定读这些 gauge。
_GAUGE_FIELDS = {
    "process.cpu_percent": "cpu_percent",
    "process.memory_mb": "memory_mb",
    "storage.db_bytes": "db_bytes",
    "storage.runs_bytes": "runs_bytes",
    "storage.runs_count": "runs_count",
}


def _labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return {str(key): str(item) for key, item in value.items()} if isinstance(value, dict) else {}


def _buckets(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [int(item) for item in value] if isinstance(value, list) else []


def _sum_metric(rows: Iterable[dict], metric: str, **match: str) -> float:
    total = 0.0
    for row in rows:
        if row["metric"] != metric:
            continue
        if match and any(_labels(row["labels"]).get(key) != value for key, value in match.items()):
            continue
        total += float(row["value"] or 0.0)
    return total


def _merge_histogram(rows: Iterable[dict]) -> tuple[int, list[int], float]:
    count = 0
    buckets: list[int] = []
    total = 0.0
    for row in rows:
        count += int(row["count"] or 0)
        total += float(row["sum"] or 0.0)
        current = _buckets(row["buckets"])
        if not buckets:
            buckets = current
        else:
            for index, value in enumerate(current):
                if index < len(buckets):
                    buckets[index] += value
    return count, buckets, total


def _timeline(rows: Sequence[dict]) -> list[dict]:
    by_minute: dict[str, list[dict]] = {}
    for row in rows:
        by_minute.setdefault(row["minute"], []).append(row)

    points: list[dict] = []
    for minute in sorted(by_minute):
        group = by_minute[minute]
        latency_count, latency_buckets, _ = _merge_histogram(
            row for row in group if row["metric"] == "http.request_ms"
        )
        point = {
            "at": f"{minute}:00+00:00",
            "requests": int(_sum_metric(group, "http.requests")),
            "errors": int(_sum_metric(group, "http.errors")),
            "runs": int(_sum_metric(group, "job.runs")),
            "failed_runs": int(_sum_metric(group, "job.runs", status="failed")),
            "insufficient_runs": int(
                _sum_metric(group, "job.runs", status="insufficient_data")
            ),
            "alerts": int(_sum_metric(group, "alerts.fired")),
            "p0": int(_sum_metric(group, "alerts.fired", level="P0")),
            "p50_ms": percentile(latency_buckets, latency_count, 0.50) if latency_count else None,
            "p95_ms": percentile(latency_buckets, latency_count, 0.95) if latency_count else None,
            "p99_ms": percentile(latency_buckets, latency_count, 0.99) if latency_count else None,
        }
        for metric, field in _GAUGE_FIELDS.items():
            point[field] = next(
                (
                    float(row["value"])
                    for row in group
                    if row["metric"] == metric and row["value"] is not None
                ),
                None,
            )
        points.append(point)
    return points


def _http_table(totals: Sequence[dict]) -> dict:
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

    for row in totals:
        labels = _labels(row["labels"])
        if row["metric"] == "http.requests":
            entry(labels)["count"] += int(row["value"] or 0)
        elif row["metric"] == "http.errors":
            entry(labels)["errors"] += int(row["value"] or 0)

    # 延迟按 (method, route) 合并 —— 每个路由一行 histogram
    latency: dict[tuple[str, str], list[dict]] = {}
    for row in totals:
        if row["metric"] != "http.request_ms":
            continue
        labels = _labels(row["labels"])
        latency.setdefault((labels.get("method", ""), labels.get("route", "")), []).append(row)
    for key, rows in latency.items():
        count, buckets, total = _merge_histogram(rows)
        target = routes.get(key)
        if target is None or count == 0:
            continue
        target["avg_ms"] = total / count
        target["p95_ms"] = percentile(buckets, count, 0.95)

    rows = sorted(routes.values(), key=lambda row: row["count"], reverse=True)
    return {
        "total": int(sum(row["count"] for row in rows)),
        "errors": int(sum(row["errors"] for row in rows)),
        "routes": rows,
    }


def _detector_table(totals: Sequence[dict]) -> list[dict]:
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

    for row in totals:
        labels = _labels(row["labels"])
        if row["metric"] == "detector.calls":
            target = entry(labels.get("detector", "<unknown>"))
            target["calls"] += int(row["value"] or 0)
            status = labels.get("status", "ok")
            if status == "fallback":
                target["fallbacks"] += int(row["value"] or 0)
            elif status == "error":
                target["errors"] += int(row["value"] or 0)
        elif row["metric"] == "detector.duration_ms":
            target = entry(labels.get("detector", "<unknown>"))
            count = int(row["count"] or 0)
            if count:
                target["avg_ms"] = float(row["sum"] or 0.0) / count
                buckets = _buckets(row["buckets"])
                target["p95_ms"] = percentile(buckets, count, 0.95)
                target["p99_ms"] = percentile(buckets, count, 0.99)

    return sorted(detectors.values(), key=lambda row: row["calls"], reverse=True)


def _job_table(totals: Sequence[dict]) -> list[dict]:
    jobs: dict[str, dict] = {}

    def entry(name: str) -> dict:
        return jobs.setdefault(
            name,
            {
                "job": name,
                "runs": 0,
                "failed": 0,
                "insufficient": 0,
                "avg_ms": None,
                "p95_ms": None,
            },
        )

    for row in totals:
        labels = _labels(row["labels"])
        if row["metric"] == "job.runs":
            target = entry(labels.get("job", "<unknown>"))
            target["runs"] += int(row["value"] or 0)
            status = labels.get("status", "success")
            if status == "failed":
                target["failed"] += int(row["value"] or 0)
            elif status == "insufficient_data":
                target["insufficient"] += int(row["value"] or 0)
        elif row["metric"] == "job.duration_ms":
            target = entry(labels.get("job", "<unknown>"))
            count = int(row["count"] or 0)
            if count:
                target["avg_ms"] = float(row["sum"] or 0.0) / count
                target["p95_ms"] = percentile(_buckets(row["buckets"]), count, 0.95)

    return sorted(jobs.values(), key=lambda row: row["runs"], reverse=True)


def _stage_table(totals: Sequence[dict]) -> list[dict]:
    stages: dict[str, dict] = {}
    for row in totals:
        if row["metric"] != "job.stage_ms":
            continue
        labels = _labels(row["labels"])
        stage = labels.get("stage", "<unknown>")
        count = int(row["count"] or 0)
        stages[stage] = {
            "stage": stage,
            "count": count,
            "avg_ms": (float(row["sum"] or 0.0) / count) if count else None,
            "p95_ms": percentile(_buckets(row["buckets"]), count, 0.95) if count else None,
        }
    return sorted(stages.values(), key=lambda row: row["avg_ms"] or 0, reverse=True)


def _current(totals: Sequence[dict], inflight: int) -> dict:
    def latest(metric: str) -> float | None:
        values = [
            float(row["value"])
            for row in totals
            if row["metric"] == metric and row["value"] is not None
        ]
        return values[-1] if values else None

    return {
        "cpu_percent": latest("process.cpu_percent"),
        "memory_mb": latest("process.memory_mb"),
        "db_bytes": latest("storage.db_bytes"),
        "runs_bytes": latest("storage.runs_bytes"),
        "runs_count": latest("storage.runs_count"),
        "inflight": inflight,
        "due_jobs": latest("scheduler.due_jobs"),
    }


def _scheduler_section(totals: Sequence[dict]) -> dict:
    ticks = [
        float(row["value"]) for row in totals if row["metric"] == "scheduler.ticks"
    ]
    tick_rows = [row for row in totals if row["metric"] == "scheduler.tick_ms"]
    tick_count, tick_buckets, tick_total = _merge_histogram(tick_rows)
    last_tick = [
        float(row["value"])
        for row in totals
        if row["metric"] == "scheduler.last_tick_at" and row["value"] is not None
    ]
    due = [
        float(row["value"])
        for row in totals
        if row["metric"] == "scheduler.due_jobs" and row["value"] is not None
    ]
    last_tick_at = last_tick[-1] if last_tick else None
    return {
        # ⚠️ 用「最近一次 tick 的时间」判断，而不是线程对象 ——
        #    监控数据来自另一个进程时（未来多进程），线程对象根本读不到。
        "alive": bool(
            last_tick_at is not None
            and utcnow().timestamp() - last_tick_at < SCHEDULER_STALE_SECONDS
        ),
        "ticks": int(ticks[-1]) if ticks else 0,
        "avg_tick_ms": (tick_total / tick_count) if tick_count else None,
        "p95_tick_ms": percentile(tick_buckets, tick_count, 0.95) if tick_count else None,
        "due_jobs": int(due[-1]) if due else None,
        "last_tick_at": (
            datetime.fromtimestamp(last_tick_at, tz=UTC).isoformat(timespec="seconds")
            if last_tick_at is not None
            else None
        ),
        "avg_prune_ms": None,
    }


def build_observability_router(
    get_data_root: Callable[[], Path] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/platform/observability")
    def observability(window_minutes: int = 60) -> dict:
        """服务自身状态 + 最近 N 分钟的时序 + 算法/接口/任务统计。

        ⚠️ 一次请求返回全页所需 —— 监控页 15 秒刷新一次，
           拆成五个端点就是五倍的请求与查询。
        """
        obs = get_observability()
        window = max(1, min(int(window_minutes), 24 * 60))
        since = (utcnow() - timedelta(minutes=window)).strftime("%Y-%m-%dT%H:%M")
        store = obs.store()
        totals = store.total_rows()
        timeline = _timeline(store.timeline_rows(since))
        info = obs.info()

        return {
            "service": {
                **info,
                "sampler_running": bool(timeline),
                "snapshot_at": timeline[-1]["at"] if timeline else None,
            },
            "interval_seconds": info["export_interval_seconds"],
            "current": _current(totals, info["inflight"]),
            "timeline": timeline,
            "http": _http_table(totals),
            "alerts": {
                "total": int(
                    sum(
                        float(row["value"] or 0.0)
                        for row in totals
                        if row["metric"] == "alerts.fired"
                    )
                ),
                "p0": int(
                    sum(
                        float(row["value"] or 0.0)
                        for row in totals
                        if row["metric"] == "alerts.fired"
                        and _labels(row["labels"]).get("level") == "P0"
                    )
                ),
            },
            "detectors": _detector_table(totals),
            "jobs": _job_table(totals),
            "stages": _stage_table(totals),
            "scheduler": _scheduler_section(totals),
            "otel": {
                "enabled": info["otel_enabled"],
                "endpoint": info["otel_endpoint"],
                "hint": (
                    "指标与链路已按 OTLP 导出"
                    if info["otel_enabled"]
                    else "未配置 ANOMALY_OTEL_ENDPOINT，指标只写本地 SQLite"
                ),
            },
        }

    return router
