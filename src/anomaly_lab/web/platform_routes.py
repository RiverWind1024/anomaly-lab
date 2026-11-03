"""平台 API：数据源 / 指标 / 检测任务的配置、运行与预览。"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from anomaly_lab.platform import retention
from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.alert_events import collect_alert_events
from anomaly_lab.platform.alerts import (
    band_multiplier,
    band_multiplier_or_none,
    highest_multiplier,
    level_labels,
    parse_rules,
    rules_to_dicts,
)
from anomaly_lab.platform.compare import compare_series
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DEFAULT_DETECTOR,
    DEFAULT_DETECTOR_SET,
    DETECTOR_FACTORIES,
    create_detector,
    detector_available,
    detector_catalog,
    resolve_detector,
)
from anomaly_lab.platform.feedback import (
    Annotation,
    SeriesOutcome,
    suggest_setting,
)
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import freq_delta, utcnow
from anomaly_lab.web.biz_state import biz_headers
from anomaly_lab.web.json_utils import clean_floats

TimeFormat = Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]
MissingPolicy = Literal["drop", "interpolate", "error"]


class SourceIn(BaseModel):
    name: str
    path: str = ""
    kind: str = "sqlite"
    config: dict | None = None


class SourcePatchIn(BaseModel):
    """数据源更新：**全部可选** —— 只传要改的字段。"""

    name: str | None = None
    path: str | None = None
    kind: str | None = None
    config: dict | None = None


class MetricPatchIn(BaseModel):
    """指标更新：**全部可选** —— 只传要改的字段。"""

    name: str | None = None
    query: str | None = None
    time_column: str | None = None
    value_column: str | None = None
    group_column: str | None = None
    time_format: TimeFormat | None = None
    freq: str | None = None
    source_timezone: str | None = None
    missing_policy: MissingPolicy | None = None


class MetricIn(BaseModel):
    source_id: int
    name: str
    query: str
    time_column: str
    value_column: str
    group_column: str | None = None
    time_format: TimeFormat = "iso_utc"
    freq: str = "5min"
    source_timezone: str = "UTC"
    missing_policy: MissingPolicy = "drop"


class JobIn(BaseModel):
    metric_id: int
    name: str
    detector: str = "auto"
    alert_threshold: float | None = None
    critical_threshold: float | None = None
    window_points: int = 500
    interval_seconds: int = 300
    enabled: bool = True
    alert_rules: list[AlertRuleIn] | None = None


class JobToggleIn(BaseModel):
    """任务配置更新：**全部可选** —— 只传要改的字段。

    ⚠️ `alert_rules` **不在其中** —— 告警规则不能自由编辑（spec §8.3），
       只能通过「应用反馈建议」按比例缩放。
    """

    name: str | None = None
    metric_id: int | None = None
    enabled: bool | None = None
    detector: str | None = None
    alert_threshold: float | None = None
    critical_threshold: float | None = None
    window_points: int | None = None
    interval_seconds: int | None = None


class AlertRuleIn(BaseModel):
    """一条告警规则。

    两种条件二选一：`multiplier` 是倍数条件（缩放因子），
    `op`+`value` 是绝对值条件（如「值 > 50 记 P1」）。
    """

    level: str
    multiplier: float | None = None
    op: str | None = None
    value: float | None = None


class FeedbackIn(BaseModel):
    """一条人工反馈：某段时间内检测行为对不对（粒度对齐 CloudWatch）。"""

    job_id: int
    series_id: str
    start_ts: str
    end_ts: str
    kind: Literal["correct", "false_alarm", "missed", "other"]
    note: str = ""
    run_id: int | None = None


class ApplySuggestionIn(BaseModel):
    """应用反馈建议：可同时改告警倍数与检测算法。"""

    multiplier: float
    detector: str | None = None


#: NaN/Inf → None，避免 JSON 里出现非法值（实现见 web/json_utils.py）
_clean = clean_floats


def _not_found(exc: ValueError) -> HTTPException:
    """「资源不存在」→ 404。

    ⚠️ **不要用「消息里有没有『不存在』」来判断** ——
       「不支持的检测器: 不存在的算法」也会命中那个词。
    """
    return HTTPException(status_code=404, detail=str(exc))


def _parse_ts(value: str | None) -> datetime | None:
    """解析 ISO 时间戳；解析不了就返回 None（当作没这个筛选条件）。

    ⚠️ **不能直接拿字符串比较时间** —— 事件的时间戳是 `2026-10-30T07:23:00`，
       浏览器给的可能是 `2026-10-30T07:23:00.000Z`，
       两种格式字典序一比就错了。
    """
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # 没带时区的按 UTC 解释（平台侧的时间一律是 UTC）
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _at_or_after(event_ts: str, moment: datetime) -> bool:
    """事件时间是否在 moment 之后（含）。

    事件时间解析不出来时**保留**该事件 —— 宁可多给一条，
    也不要因为格式问题把用户的告警藏起来。
    """
    parsed = _parse_ts(event_ts)
    if parsed is None:
        return True
    return parsed >= moment


def _at_or_before(event_ts: str, moment: datetime) -> bool:
    parsed = _parse_ts(event_ts)
    if parsed is None:
        return True
    return parsed <= moment


MAX_PREVIEW_POINTS = 2000


def _sample_indices(n: int, max_points: int) -> np.ndarray | None:
    """点数过多时等间隔抽样；返回 None 表示不需要抽样。"""
    if n <= max_points:
        return None
    return np.unique(np.linspace(0, n - 1, max_points).round().astype(int))


def build_router(
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

    @router.post("/api/platform/sources")
    def create_source(payload: SourceIn) -> dict:
        try:
            source = _store().add_source(
                payload.name, payload.path, payload.kind, payload.config or {}
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(source)

    @router.patch("/api/platform/sources/{source_id}")
    def patch_source(source_id: int, payload: SourcePatchIn) -> dict:
        store = _store()
        try:
            store.get_source(source_id)
        except ValueError as exc:
            raise _not_found(exc) from exc
        try:
            source = store.update_source(
                source_id,
                name=payload.name,
                path=payload.path,
                kind=payload.kind,
                config=payload.config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(source)

    @router.post("/api/platform/metrics")
    def create_metric(payload: MetricIn) -> dict:
        try:
            metric = _store().add_metric(
                source_id=payload.source_id,
                name=payload.name,
                query=payload.query,
                time_column=payload.time_column,
                value_column=payload.value_column,
                group_column=payload.group_column,
                time_format=payload.time_format,
                freq=payload.freq,
                source_timezone=payload.source_timezone,
                missing_policy=payload.missing_policy,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(metric)

    @router.patch("/api/platform/metrics/{metric_id}")
    def patch_metric(metric_id: int, payload: MetricPatchIn) -> dict:
        store = _store()
        try:
            store.get_metric(metric_id)
        except ValueError as exc:
            raise _not_found(exc) from exc
        try:
            metric = store.update_metric(
                metric_id, **payload.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(metric)

    @router.post("/api/platform/jobs")
    def create_job(payload: JobIn) -> dict:
        store = _store()
        try:
            detector = create_detector(payload.detector)
            default_threshold = float(detector.default_threshold)
        except ValueError as exc:
            if payload.detector != AUTO_DETECTOR:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # auto 没有单一默认阈值，用兜底算法的默认值
            default_threshold = float(create_detector(DEFAULT_DETECTOR).default_threshold)
        # 可用性前置检查：Chronos 这类可选依赖缺失时，创建阶段就说清楚，
        # 不让用户等到定时任务跑起来才看到一个 failed 运行记录。
        available, reason = detector_available(payload.detector)
        if not available:
            raise HTTPException(
                status_code=400,
                detail=f"检测算法 {payload.detector} 当前不可用：{reason}",
            )
        try:
            rule_dicts = (
                [rule.model_dump(exclude_none=True) for rule in payload.alert_rules]
                if payload.alert_rules
                else []
            )
            rules = parse_rules(rule_dicts) if rule_dicts else []
            if rules:
                # 规则表为准：阈值由规则推导（最低档/最高档的倍数）
                # 没有倍数条件（规则全是绝对值条件）→ 退回到检测器默认阈值
                alert = band_multiplier_or_none(rules)
                if alert is None:
                    alert = default_threshold
                critical = highest_multiplier(rules) or alert
            else:
                alert = (
                    float(payload.alert_threshold)
                    if payload.alert_threshold is not None
                    else default_threshold
                )
                critical = (
                    float(payload.critical_threshold)
                    if payload.critical_threshold is not None
                    else alert * 1.5
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            job = store.add_job(
                metric_id=payload.metric_id,
                name=payload.name,
                detector=payload.detector,
                alert_threshold=alert,
                critical_threshold=critical,
                window_points=payload.window_points,
                interval_seconds=payload.interval_seconds,
                enabled=payload.enabled,
                alert_rules=rule_dicts or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(job)

    @router.patch("/api/platform/jobs/{job_id}")
    def patch_job(job_id: int, payload: JobToggleIn) -> dict:
        store = _store()
        try:
            store.get_job(job_id)
        except ValueError as exc:
            raise _not_found(exc) from exc
        try:
            job = store.update_job_config(job_id, **payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(job)

    @router.post("/api/platform/jobs/{job_id}/run")
    def run_job(job_id: int) -> dict:
        store = _store()
        try:
            store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            run_id = runner_module.execute_job(store, job_id, data_root=get_data_root())
        except Exception as exc:  # 任何失败都要把原因告诉调用方，而不是 500
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        return {"run_id": run_id, "status": store.get_run(run_id).status}

    @router.post("/api/platform/jobs/{job_id}/test-run")
    def test_run(job_id: int) -> dict:
        """**试跑**一次检测：真实执行，但**不落库**。

        ⚠️ 与 `/run` 的区别只有「不写 `runs` 表、不写结果文件」——
           取数、检测器选择、打分、分级全都走同一段代码，
           所以试跑看到的就是真跑会得到的。

        ⚠️ 告警点**逐个列出**，不做抽样 ——
           抽样可能正好丢掉告警点，用户会误以为「没有告警」。
        """
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            result = runner_module.execute_job_test(
                store, job_id, data_root=get_data_root()
            )
        except Exception as exc:  # 任何失败都要把原因告诉调用方，而不是 500
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc

        entries: list[dict] = []
        results: list[dict] = []
        alerts: list[dict] = []
        # 规则表与档位名取自**执行结果** —— 任务可能没存 alert_rules，
        # runner 会回落到「按两个阈值生成默认规则」，前端要看到的是实际用的那份。
        rules: list[dict] = []
        levels: list[str] = ["正常"]
        detector = ""
        metric_class = ""
        detector_rationale = ""
        detector_fallback = False
        score_type = ""
        for outcome in result.outcomes:
            entry = dict(outcome.entry)
            entry.pop("file", None)
            entries.append(entry)
            arrays = outcome.arrays
            if not arrays:
                # 数据不足：明确说明，绝不返回「一切正常」的错觉
                results.append(
                    {
                        "series_id": entry["series_id"],
                        "group": entry.get("group"),
                        "sufficient": False,
                        "insufficient_reason": (
                            f"有效点仅 {entry.get('n_valid', 0)} 个，不足以做检测"
                        ),
                        "n": entry.get("n", 0),
                        "n_valid": entry.get("n_valid", 0),
                        "n_missing": entry.get("n_missing", 0),
                        "n_alerts": 0,
                        "n_p0": 0,
                        "timestamps": [],
                        "values": [],
                        "scores": [],
                        "baseline": None,
                        "lower": None,
                        "upper": None,
                        "severity": [],
                    }
                )
                continue

            if not rules:
                rules = outcome.alert_rules
                levels = outcome.levels
                detector = str(arrays["detector"])
                metric_class = str(arrays["metric_class"])
                detector_rationale = str(arrays["detector_rationale"])
                detector_fallback = bool(entry.get("fallback", False))
                score_type = str(arrays["score_type"])

            timestamps = arrays["timestamps"].astype("datetime64[s]")
            values = arrays["values"]
            scores = arrays["scores"]
            severity = arrays["severity"]
            baseline = arrays["baseline"]
            lower = arrays["lower"]
            upper = arrays["upper"]
            has_bands = baseline.size > 0

            for index, level_index in enumerate(severity):
                level_index = int(level_index)
                if level_index <= 0:
                    continue
                alerts.append(
                    {
                        "series_id": entry["series_id"],
                        "group": entry.get("group"),
                        "index": index,
                        "timestamp": str(timestamps[index]),
                        "value": float(values[index]),
                        "score": float(scores[index]),
                        "severity": level_index,
                        "level": levels[level_index] if level_index < len(levels) else "P1",
                    }
                )

            results.append(
                {
                    "series_id": entry["series_id"],
                    "group": entry.get("group"),
                    "sufficient": True,
                    "insufficient_reason": "",
                    "n": entry.get("n", 0),
                    "n_valid": entry.get("n_valid", 0),
                    "n_missing": entry.get("n_missing", 0),
                    "n_alerts": entry.get("n_alerts", 0),
                    "n_p0": entry.get("n_p0", 0),
                    "timestamps": [str(item) for item in timestamps],
                    "values": _clean(values),
                    "scores": _clean(scores),
                    "baseline": _clean(baseline) if has_bands else None,
                    "lower": _clean(lower) if has_bands else None,
                    "upper": _clean(upper) if has_bands else None,
                    "severity": [int(item) for item in severity],
                }
            )

        return {
            "job_id": job.id,
            "detector": detector,
            "requested_detector": job.detector,
            "metric_class": metric_class,
            "detector_rationale": detector_rationale,
            "detector_fallback": detector_fallback,
            "score_type": score_type,
            "n_series": len(entries),
            "n_alerts": result.n_alerts,
            "n_p0": result.n_p0,
            "n_insufficient": result.n_insufficient,
            "alert_threshold": job.alert_threshold,
            "critical_threshold": job.critical_threshold,
            "alert_rules": rules,
            "levels": levels,
            "series": entries,
            "results": results,
            "alerts": alerts,
        }

    @router.get("/api/platform/jobs/{job_id}/runs")
    def list_runs(job_id: int) -> dict:
        store = _store()
        try:
            store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"runs": [asdict(item) for item in store.list_runs(job_id)]}

    @router.get("/api/platform/jobs/{job_id}/preview")
    def preview(job_id: int, run_id: int | None = None, series_id: str | None = None) -> dict:
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        chosen_run = run_id
        if chosen_run is None:
            latest = store.latest_run(job.id)
            if latest is None:
                raise HTTPException(
                    status_code=404,
                    detail="该任务还没有运行记录",
                    headers=biz_headers("no_run"),
                )
            chosen_run = latest.id
        try:
            run = store.get_run(chosen_run)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if run.job_id != job.id:
            raise HTTPException(
                status_code=404,
                detail=f"run_id {chosen_run} 不属于任务 {job_id}",
            )
        try:
            index = runner_module.read_run_index(get_data_root(), chosen_run)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        entries = index.get("series", [])
        if not entries:
            raise HTTPException(
                status_code=404,
                detail="该次运行没有序列结果",
                headers=biz_headers("no_series"),
            )
        entry = entries[0]
        if series_id:
            matched = next((item for item in entries if item["series_id"] == series_id), None)
            if matched is None:
                raise HTTPException(status_code=404, detail=f"序列不存在: {series_id}")
            entry = matched

        if entry.get("file") is None:
            # 数据不足的序列没有检测结果：明确说明，绝不返回「一切正常」的错觉
            n_valid = int(entry.get("n_valid", 0))
            return {
                "run_id": chosen_run,
                "job_id": job.id,
                "detector": job.detector,
                "requested_detector": job.detector,
                "metric_class": "",
                "detector_rationale": "",
                "detector_fallback": False,
                "score_type": "",
                "series_id": entry["series_id"],
                "group": entry.get("group"),
                "n": int(entry.get("n", 0)),
                "n_valid": n_valid,
                "n_missing": int(entry.get("n_missing", 0)),
                "n_alerts": 0,
                "n_p0": 0,
                "sufficient": False,
                "insufficient_reason": f"有效点仅 {n_valid} 个，不足以做检测",
                "timestamps": [],
                "values": [],
                "scores": [],
                "baseline": None,
                "lower": None,
                "upper": None,
                "severity": [],
                "alert_threshold": job.alert_threshold,
                "critical_threshold": job.critical_threshold,
                "alert_rules": job.alert_rules,
                "levels": ["正常"],
                "series": entries,
            }

        target = runner_module.run_dir(get_data_root(), chosen_run)
        payload = np.load(target / entry["file"], allow_pickle=False)
        timestamps = payload["timestamps"].astype("datetime64[ns]")
        baseline = payload["baseline"]
        lower = payload["lower"]
        upper = payload["upper"]
        has_bands = baseline.size > 0

        values_all = payload["values"]
        scores_all = payload["scores"]
        severity_all = payload["severity"]
        index = _sample_indices(len(values_all), MAX_PREVIEW_POINTS)
        sampled = index is not None
        if sampled:
            values_all = values_all[index]
            scores_all = scores_all[index]
            severity_all = severity_all[index]
            timestamps = timestamps[index]
            if has_bands:
                baseline = baseline[index]
                lower = lower[index]
                upper = upper[index]

        return {
            "run_id": chosen_run,
            "job_id": job.id,
            "detector": str(payload["detector"]),
            "requested_detector": str(payload["requested_detector"]),
            "metric_class": str(payload["metric_class"]),
            "detector_rationale": str(payload["detector_rationale"]),
            "detector_fallback": bool(entry.get("fallback", False)),
            "score_type": str(payload["score_type"]),
            "series_id": entry["series_id"],
            "group": entry.get("group"),
            "n": entry["n"],
            "n_valid": int(entry.get("n_valid", entry["n"])),
            "n_missing": int(entry.get("n_missing", 0)),
            "n_alerts": entry.get("n_alerts", 0),
            "n_p0": entry.get("n_p0", 0),
            "sufficient": bool(entry.get("sufficient", True)),
            "insufficient_reason": "",
            "sampled": sampled,
            "original_n": int(entry["n"]),
            "timestamps": [str(item) for item in timestamps.astype("datetime64[s]")],
            "values": _clean(values_all),
            "scores": _clean(scores_all),
            "baseline": _clean(baseline) if has_bands else None,
            "lower": _clean(lower) if has_bands else None,
            "upper": _clean(upper) if has_bands else None,
            "severity": [int(item) for item in severity_all],
            "alert_threshold": float(payload["alert_threshold"]),
            "critical_threshold": float(payload["critical_threshold"]),
            "alert_rules": json.loads(str(payload["alert_rules"])),
            "levels": json.loads(str(payload["levels"])),
            "series": entries,
        }

    # ---------- 多算法对比 ----------

    @router.get("/api/platform/jobs/{job_id}/compare")
    def compare(
        job_id: int,
        series_id: str | None = None,
        detectors: str | None = None,
    ) -> dict:
        """同一条序列用多个算法各跑一遍，供选算法时对照。

        这是探索功能：不产生告警、不落盘，只回传各自的基线/上下界/告警点。
        """
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            metric = store.get_metric(job.metric_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rules = runner_module.job_rules(job)
        # 没有倍数条件时用最低档检测器的默认阈值（分数是 0~1 时尤其需要）
        band_width = band_multiplier_or_none(rules)
        if band_width is None:
            band_width = float(
                create_detector(DEFAULT_DETECTOR).default_threshold
            )
        end_time = utcnow()
        start_time = end_time - freq_delta(metric.freq) * job.window_points
        # ⚠️ 走连接器层 —— HTTP 数据源的 path 是空的，不能按本地文件解析
        series_list = runner_module.load_series(
            store, metric, get_data_root(), start_time, end_time
        )
        if not series_list:
            raise HTTPException(
                status_code=404,
                detail="该窗口内没有取到数据",
                headers=biz_headers("no_data"),
            )
        series = series_list[0]
        if series_id:
            matched = next((item for item in series_list if item.series_id == series_id), None)
            if matched is None:
                raise HTTPException(status_code=404, detail=f"序列不存在: {series_id}")
            series = matched
        if not bool(series.meta.get("sufficient", True)):
            n_valid = int(series.meta.get("n_valid", 0))
            raise HTTPException(
                status_code=404,
                detail=f"序列 {series.series_id} 有效点仅 {n_valid} 个，不足以做检测",
                headers=biz_headers("insufficient_data"),
            )

        resolution = resolve_detector(AUTO_DETECTOR, series)
        # 可选项：任务配置的算法 + auto 推荐的候选（用户能勾选的全部）
        available: list[str] = []
        if job.detector != AUTO_DETECTOR:
            available.append(job.detector)
        available.extend(resolution.candidates)
        available = [
            name for name in dict.fromkeys(available) if name in DETECTOR_FACTORIES
        ]
        names = [
            name.strip()
            for name in (detectors or "").split(",")
            if name.strip() and name.strip() != AUTO_DETECTOR
        ]
        if not names:
            names = list(available)
        seen: list[str] = []
        for name in names:
            if name in DETECTOR_FACTORIES and name not in seen:
                seen.append(name)
        if not seen:
            raise HTTPException(
                status_code=400,
                detail="没有可对比的算法",
                headers=biz_headers("no_algorithms"),
            )
        # 不可用的算法（Chronos 缺依赖/权重）跳过并说明原因，
        # 不让一个不可用算法把整张对比表拖垮。
        usable: list[str] = []
        skipped: list[dict] = []
        for name in seen:
            ok, reason = detector_available(name)
            if ok:
                usable.append(name)
            else:
                skipped.append({"name": name, "reason": reason})
        if not usable:
            raise HTTPException(
                status_code=400,
                detail="没有可对比的算法",
                headers=biz_headers("no_algorithms"),
            )

        outcomes = compare_series(series, usable, rules, band_width)
        index = _sample_indices(len(series.values), MAX_PREVIEW_POINTS)
        sampled = index is not None
        timestamps = series.timestamps
        values = series.values
        if sampled:
            timestamps = timestamps[index]
            values = values[index]

        def _take(array: np.ndarray | None) -> list[float | None] | None:
            if array is None:
                return None
            return _clean(array[index] if sampled else array)

        return {
            "job_id": job.id,
            "series_id": series.series_id,
            "group": series.meta.get("group"),
            "n": int(series.n),
            "sampled": sampled,
            "original_n": int(series.n),
            "timestamps": [str(item) for item in timestamps.astype("datetime64[s]")],
            "values": _clean(values),
            "metric_class": resolution.metric_class,
            "confidence": resolution.confidence,
            "reasons": resolution.reasons,
            "recommendation": {
                "detectors": list(resolution.candidates),
                "rationale": resolution.rationale,
            },
            "auto_detector": resolution.detector,
            "auto_fallback": resolution.fallback,
            "auto_rationale": resolution.rationale,
            "available": available,
            "skipped": skipped,
            "detectors": [
                {
                    **outcome.as_dict(),
                    "baseline": _take(outcome.baseline),
                    "lower": _take(outcome.lower),
                    "upper": _take(outcome.upper),
                    "scores": _take(outcome.scores),
                    "severity": [
                        int(item) for item in (outcome.severity[index] if sampled else outcome.severity)
                    ],
                    "is_auto": outcome.name == resolution.detector,
                }
                for outcome in outcomes
            ],
            "levels": level_labels(rules),
            "alert_rules": rules_to_dicts(rules),
            "band_width": band_width,
        }

    # ---------- 人工反馈与阈值建议 ----------

    # ---------- 删除 ----------

    def _delete_run_dirs(run_ids: list[int]) -> None:
        """删掉 run 目录 —— 数据库外键管不到文件系统。

        不清的话 `cache/platform/runs/{run_id}/` 会变成孤儿垃圾。
        删失败不回滚数据库：DB 一致性优先，文件残留只是占地方。
        """
        for run_id in run_ids:
            directory = runner_module.run_dir(get_data_root(), run_id)
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

    @router.delete("/api/platform/jobs/{job_id}")
    def delete_job(job_id: int) -> dict:
        store = _store()
        if runner_module.is_running(job_id):
            raise HTTPException(
                status_code=409, detail="任务正在运行中，请等本次运行结束后再删除"
            )
        try:
            stats = store.delete_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _delete_run_dirs(stats.pop("run_ids", []))
        return {"deleted": stats}

    @router.delete("/api/platform/metrics/{metric_id}")
    def delete_metric(metric_id: int) -> dict:
        store = _store()
        try:
            stats = store.delete_metric(metric_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _delete_run_dirs(stats.pop("run_ids", []))
        return {"deleted": stats}

    @router.delete("/api/platform/sources/{source_id}")
    def delete_source(source_id: int) -> dict:
        store = _store()
        try:
            stats = store.delete_source(source_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _delete_run_dirs(stats.pop("run_ids", []))
        return {"deleted": stats}

    @router.post("/api/platform/feedback")
    def create_feedback(payload: FeedbackIn) -> dict:
        store = _store()
        try:
            item = store.add_feedback(
                job_id=payload.job_id,
                series_id=payload.series_id,
                start_ts=payload.start_ts,
                end_ts=payload.end_ts,
                kind=payload.kind,
                note=payload.note,
                run_id=payload.run_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(item)

    @router.get("/api/platform/jobs/{job_id}/feedback")
    def list_feedback(job_id: int) -> dict:
        store = _store()
        try:
            store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"feedback": [asdict(item) for item in store.list_feedback(job_id)]}

    @router.get("/api/platform/jobs/{job_id}/feedback/suggestion")
    def feedback_suggestion(job_id: int, run_id: int | None = None) -> dict:
        """根据反馈给出「用哪个算法 + 用哪个倍数」的建议。

        评估要比较不同算法，所以这里**重新取数并跑一遍候选算法**——
        run 落盘的只有任务当时选中的那一个算法的分数。
        """
        store = _store()
        try:
            job = store.get_job(job_id)
            metric = store.get_metric(job.metric_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        chosen_run = run_id
        if chosen_run is None:
            latest = store.latest_run(job.id)
            chosen_run = latest.id if latest else None
        elif chosen_run is not None:
            try:
                store.get_run(chosen_run)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        rules = runner_module.job_rules(job)
        current_multiplier = band_multiplier(rules)
        annotations = [
            Annotation(
                series_id=item.series_id,
                start_ts=item.start_ts,
                end_ts=item.end_ts,
                kind=item.kind,
            )
            for item in store.list_feedback(job.id)
        ]
        candidates = _suggestion_candidates(job, metric)
        outcomes = _collect_outcomes(job, metric, candidates)
        suggestion = suggest_setting(
            outcomes, annotations, job.detector, current_multiplier
        )
        return {
            "run_id": chosen_run,
            # 注意：键名不能叫 candidates——suggestion.as_dict() 里也有同名键，
            # 展开会覆盖它。这里放的是「实际参与比较的算法」。
            "evaluated_detectors": sorted(outcomes),
            **suggestion.as_dict(),
        }

    def _suggestion_candidates(job, metric) -> list[str]:
        """建议要比较的算法集合：当前设置 + 形态推荐的候选。"""
        names: list[str] = []
        # auto 作为「当前设置」参与比较——它是逐序列选算法的混合表现
        names.append(job.detector)
        try:
            series_list = _load_window_series(job, metric)
        except (ValueError, FileNotFoundError):
            series_list = []
        for series in series_list:
            resolution = resolve_detector(AUTO_DETECTOR, series)
            names.append(resolution.detector)
            names.extend(resolution.candidates)
        unique = [
            name
            for name in dict.fromkeys(names)
            if name in DETECTOR_FACTORIES or name == AUTO_DETECTOR
        ]
        return unique or list(DEFAULT_DETECTOR_SET)

    def _load_window_series(job, metric) -> list:
        end_time = utcnow()
        start_time = end_time - freq_delta(metric.freq) * job.window_points
        # ⚠️ 走连接器层 —— HTTP 数据源的 path 是空的，不能按本地文件解析
        return runner_module.load_series(
            _store(), metric, get_data_root(), start_time, end_time
        )

    def _collect_outcomes(job, metric, detectors: list[str]) -> dict:
        """按算法收集各序列的分数，供反馈评估使用。

        `auto` 不是具体算法——它是「每条序列各自选一个」的混合表现，
        所以按序列分别取它会选中的那个算法来算。
        """
        series_list = _load_window_series(job, metric)
        outcomes: dict[str, list[SeriesOutcome]] = {}
        for detector_name in detectors:
            items: list[SeriesOutcome] = []
            for series in series_list:
                if not bool(series.meta.get("sufficient", True)):
                    continue
                if detector_name == AUTO_DETECTOR:
                    actual = resolve_detector(AUTO_DETECTOR, series).detector
                else:
                    actual = detector_name
                detector = create_detector(actual).fit(series)
                items.append(
                    SeriesOutcome(
                        series_id=series.series_id,
                        timestamps=series.timestamps,
                        scores=np.asarray(detector.score(series), dtype=float),
                    )
                )
            outcomes[detector_name] = items
        return outcomes

    @router.post("/api/platform/jobs/{job_id}/apply-suggestion")
    def apply_suggestion(job_id: int, payload: ApplySuggestionIn) -> dict:
        """应用建议：可同时改算法与倍数（倍数按比例整体缩放规则表）。"""
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rules = runner_module.job_rules(job)
        current = band_multiplier(rules)
        if current <= 0:
            raise HTTPException(status_code=400, detail="当前倍数无效")
        ratio = float(payload.multiplier) / current
        if ratio <= 0:
            raise HTTPException(status_code=400, detail="倍数必须为正数")
        scaled = []
        for rule in rules:
            if rule.multiplier is None:
                scaled.append(rule.as_dict())
            else:
                scaled.append(
                    {**rule.as_dict(), "multiplier": round(rule.multiplier * ratio, 6)}
                )
        try:
            updated = store.update_job_rules(job.id, scaled)
            if payload.detector:
                updated = store.set_job_detector(updated.id, payload.detector)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(updated)

    @router.get("/api/platform/storage")
    def storage() -> dict:
        """当前占用与保留策略 —— 让「自动清理」可见。

        ⚠️ 「自动清理」如果完全不可见，用户没法判断它在不在工作 ——
           作品集演示时，「数据在自动滚动」本身就是个卖点。
        """
        return retention.storage_usage(_store(), get_data_root())

    @router.post("/api/platform/prune")
    def prune_now() -> dict:
        """立即清理超出保留窗口的数据（调度器也会每小时自动清一次）。"""
        store = _store()
        result = retention.prune(store, get_data_root())
        return {
            **result.as_dict(),
            "storage": retention.storage_usage(store, get_data_root()),
        }

    return router
