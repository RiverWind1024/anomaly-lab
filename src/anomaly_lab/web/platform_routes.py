"""平台 API：数据源 / 指标 / 检测任务的配置、运行与预览。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.alerts import (
    band_multiplier,
    highest_multiplier,
    parse_rules,
)
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DEFAULT_DETECTOR,
    create_detector,
    detector_catalog,
)
from anomaly_lab.platform.feedback import (
    Annotation,
    SeriesOutcome,
    suggest_multiplier,
)
from anomaly_lab.platform.store import PlatformStore

TimeFormat = Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]
MissingPolicy = Literal["drop", "interpolate", "error"]


class SourceIn(BaseModel):
    name: str
    path: str
    kind: str = "sqlite"


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
    enabled: bool


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
    """把告警倍数调到指定值（应用反馈建议）。"""

    multiplier: float


def _clean(values: np.ndarray) -> list[float | None]:
    """把 NaN/Inf 转成 None，避免 JSON 里出现非法值。"""
    result: list[float | None] = []
    for value in np.asarray(values, dtype=float):
        result.append(float(value) if np.isfinite(value) else None)
    return result


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

    @router.get("/platform", response_class=HTMLResponse)
    def platform_page(request: Request):
        from anomaly_lab.web.app import _TEMPLATES

        return _TEMPLATES.TemplateResponse(request, "platform.html", {})

    @router.get("/api/platform/catalog")
    def catalog() -> dict:
        store = _store()
        return {
            "sources": [asdict(item) for item in store.list_sources()],
            "metrics": [asdict(item) for item in store.list_metrics()],
            "jobs": [asdict(item) for item in store.list_jobs()],
            "detectors": detector_catalog(),
        }

    @router.post("/api/platform/sources")
    def create_source(payload: SourceIn) -> dict:
        try:
            source = _store().add_source(payload.name, payload.path, payload.kind)
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
        try:
            rule_dicts = (
                [rule.model_dump(exclude_none=True) for rule in payload.alert_rules]
                if payload.alert_rules
                else []
            )
            rules = parse_rules(rule_dicts) if rule_dicts else []
            if rules:
                # 规则表为准：阈值由规则推导（最低档/最高档的倍数）
                alert = band_multiplier(rules)
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
    def toggle_job(job_id: int, payload: JobToggleIn) -> dict:
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        store.set_job_enabled(job.id, payload.enabled)
        return asdict(store.get_job(job.id))

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
                raise HTTPException(status_code=404, detail="该任务还没有运行记录")
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
            raise HTTPException(status_code=404, detail="该次运行没有序列结果")
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

    # ---------- 人工反馈与阈值建议 ----------

    def _load_outcomes(run_id: int) -> list[SeriesOutcome]:
        """读出一次运行的分数与时间，供反馈评估使用。"""
        data_root = get_data_root()
        index = runner_module.read_run_index(data_root, run_id)
        target = runner_module.run_dir(data_root, run_id)
        outcomes: list[SeriesOutcome] = []
        for entry in index.get("series", []):
            if not entry.get("file"):
                continue
            payload = np.load(target / entry["file"], allow_pickle=False)
            outcomes.append(
                SeriesOutcome(
                    series_id=entry["series_id"],
                    timestamps=payload["timestamps"].astype("datetime64[ns]"),
                    scores=np.asarray(payload["scores"], dtype=float),
                )
            )
        return outcomes

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
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        chosen_run = run_id
        if chosen_run is None:
            latest = store.latest_run(job.id)
            if latest is None:
                raise HTTPException(status_code=404, detail="该任务还没有运行记录")
            chosen_run = latest.id
        try:
            store.get_run(chosen_run)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rules = parse_rules(job.alert_rules) if job.alert_rules else []
        current = band_multiplier(rules) if rules else job.alert_threshold
        annotations = [
            Annotation(
                series_id=item.series_id,
                start_ts=item.start_ts,
                end_ts=item.end_ts,
                kind=item.kind,
            )
            for item in store.list_feedback(job.id)
        ]
        suggestion = suggest_multiplier(
            _load_outcomes(chosen_run), annotations, current
        )
        return {"run_id": chosen_run, **suggestion.as_dict()}

    @router.post("/api/platform/jobs/{job_id}/apply-multiplier")
    def apply_multiplier(job_id: int, payload: ApplySuggestionIn) -> dict:
        """按比例整体缩放规则表里的倍数条件（等价于调 band 宽度）。"""
        store = _store()
        try:
            job = store.get_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        rules = parse_rules(job.alert_rules) if job.alert_rules else []
        if not rules:
            raise HTTPException(status_code=400, detail="该任务没有告警规则")
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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(updated)

    return router
