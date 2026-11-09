"""平台只读 API：概览 / 目录 / 告警 / 检测记录。

从 `platform_routes.py` 拆出来：这一组只读、不碰配置与运行调度。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter

from anomaly_lab.platform.alert_events import collect_alert_events
from anomaly_lab.platform.detectors import detector_catalog
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.platform_common import (
    _at_or_after,
    _at_or_before,
    _parse_decision,
    _parse_ts,
)


def build_read_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()

    def _store() -> PlatformStore:
        return get_store()

    @router.get("/api/platform/overview")
    def overview() -> dict:
        """整个平台的运行概况 —— 概览页一次请求拿全。

        ⚠️ 别让前端自己去拼：那样每个任务都要单独查 runs 与 feedback，
           概览页（登录后第一屏）会发出 N+1 个请求。
        """
        store = _store()
        jobs = store.list_jobs()
        latest = store.latest_runs()
        run_stats = store.run_stats()
        feedback_stats = store.feedback_stats()

        events, skipped = collect_alert_events(store, get_data_root())

        by_level: dict[str, int] = {}
        by_job: dict[int, int] = {}
        by_series: dict[str, int] = {}
        for event in events:
            by_level[event.level] = by_level.get(event.level, 0) + 1
            by_job[event.job_id] = by_job.get(event.job_id, 0) + 1
            by_series[event.series_id] = by_series.get(event.series_id, 0) + 1

        job_name_by_id = {job.id: job.name for job in jobs}
        total_runs = sum(run_stats.values())
        return {
            "counts": {
                "sources": len(store.list_sources()),
                "metrics": len(store.list_metrics()),
                "jobs": len(jobs),
                "enabled_jobs": sum(1 for job in jobs if job.enabled),
            },
            "runs": {
                "total": total_runs,
                "success": run_stats.get("success", 0),
                "failed": run_stats.get("failed", 0),
                "running": run_stats.get("running", 0),
            },
            "alerts": {
                "total": len(events),
                "by_level": [
                    {"level": level, "count": count}
                    for level, count in sorted(
                        by_level.items(), key=lambda kv: (-kv[1], kv[0])
                    )
                ],
                "by_job": [
                    {"job_id": job_id, "job_name": job_name_by_id.get(job_id, str(job_id)),
                     "count": count}
                    for job_id, count in sorted(by_job.items(), key=lambda kv: (-kv[1], kv[0]))
                ],
                # 告警最多的序列 —— 用户最关心的就是「哪条序列在告」
                "top_series": [
                    {"series_id": series_id, "count": count}
                    for series_id, count in sorted(
                        by_series.items(), key=lambda kv: (-kv[1], kv[0])
                    )[:10]
                ],
                "skipped": len(skipped),
            },
            "feedback": {
                "total": sum(feedback_stats.values()),
                "by_kind": [
                    {"kind": kind, "count": count}
                    for kind, count in sorted(
                        feedback_stats.items(), key=lambda kv: (-kv[1], kv[0])
                    )
                ],
            },
            "jobs": [
                {
                    "id": job.id,
                    "name": job.name,
                    "enabled": job.enabled,
                    "detector": job.detector,
                    "metric_id": job.metric_id,
                    "last_run": (
                        {
                            "id": run.id,
                            "status": run.status,
                            "started_at": run.started_at,
                            "finished_at": run.finished_at,
                            "n_series": run.n_series,
                            "n_alerts": run.n_alerts,
                            "error": run.error,
                        }
                        if (run := latest.get(job.id)) is not None
                        else None
                    ),
                }
                for job in jobs
            ],
        }

    @router.get("/api/platform/catalog")
    def catalog() -> dict:
        store = _store()
        return {
            "sources": [asdict(item) for item in store.list_sources()],
            "metrics": [asdict(item) for item in store.list_metrics()],
            "jobs": [asdict(item) for item in store.list_jobs()],
            "detectors": detector_catalog(),
        }

    @router.get("/api/platform/alerts")
    def alerts(
        job_id: int | None = None,
        level: str | None = None,
        series_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        """跨任务汇总告警事件。

        ⚠️ 以每个任务的**最新一次运行**为准 —— 滚动窗口下同一段异常会被
        连续多次运行重复报出，扫全部历史 run 会刷屏。
        """
        store = _store()
        events, skipped = collect_alert_events(store, get_data_root())
        # ⚠️ 候选值（档位 / 序列）必须从**未筛选**的集合里汇总 ——
        #    否则选了 P1 之后下拉里就只剩 P1，用户再也改不回去，
        #    筛选器把自己锁死了。
        candidates = events
        if job_id is not None:
            events = [item for item in events if item.job_id == job_id]
        if level:
            events = [item for item in events if item.level == level]
        if series_id:
            events = [item for item in events if item.series_id == series_id]
        since_dt = _parse_ts(since)
        until_dt = _parse_ts(until)
        if since_dt is not None:
            events = [item for item in events if _at_or_after(item.start_ts, since_dt)]
        if until_dt is not None:
            events = [item for item in events if _at_or_before(item.start_ts, until_dt)]
        return {
            "events": [asdict(item) for item in events],
            "levels": sorted({item.level for item in candidates}),
            "series": sorted({item.series_id for item in candidates}),
            "jobs": [{"id": job.id, "name": job.name} for job in store.list_jobs()],
            "skipped": skipped,
        }

    @router.get("/api/platform/detections")
    def detections(
        job_id: int | None = None,
        only_alerts: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """**平台运行产生的检测记录** —— 每次运行 × 每条序列。

        ⚠️ 与 `/api/summary`（离线回测报告）是两回事：
           那边回答「算法在合成集上表现如何」，这边回答「我们的任务跑出了什么」。

        ⚠️ 与 `/api/platform/alerts` 也不同：告警记录只收 `n_alerts > 0` 的记录，
           这里**默认全收**（包括「跑了但没告警」）—— 「没有告警」本身是结论。
        """
        store = _store()
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        rows, total = store.detection_record_page(
            job_id=job_id, only_alerts=only_alerts, limit=limit, offset=offset
        )
        records = []
        for row in rows:
            decision = _parse_decision(row.get("decision_json"))
            threshold = decision.get("threshold") or {}
            records.append(
                {
                    "run_id": int(row["run_id"]),
                    "job_id": int(row["job_id"]),
                    "job_name": row["job_name"],
                    "metric_id": int(row["metric_id"]),
                    "metric_name": row["metric_name"],
                    "source_name": row["source_name"],
                    "started_at": row["started_at"],
                    "series_id": row["series_id"],
                    "group": row["group_name"],
                    "n": int(row["n"]),
                    "n_valid": int(row["n_valid"]),
                    "n_missing": int(row["n_missing"]),
                    "n_alerts": int(row["n_alerts"]),
                    "n_p0": int(row["n_p0"]),
                    "sufficient": bool(row["sufficient"]),
                    "detector": row["detector"],
                    "metric_class": row["metric_class"],
                    "fallback": bool(row["fallback"]),
                    "start_ts": row["start_ts"],
                    "end_ts": row["end_ts"],
                    # 尺度结论从决策链里取（run_series 没有单独的列）
                    "scale_source": threshold.get("scale_source") or "",
                    "scale_fallback": bool(threshold.get("scale_fallback")),
                    "status": threshold.get("status") or "ok",
                    "has_decision": bool(decision),
                }
            )
        return {
            "records": records,
            "total": total,
            "limit": limit,
            "offset": offset,
            "jobs": [{"id": job.id, "name": job.name} for job in store.list_jobs()],
        }


    return router
