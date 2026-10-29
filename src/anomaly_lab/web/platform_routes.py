"""平台 API：数据源 / 指标 / 检测任务的配置、运行与预览。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.detectors import create_detector, detector_catalog
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
    detector: str = "seasonal"
    alert_threshold: float | None = None
    critical_threshold: float | None = None
    window_points: int = 500
    interval_seconds: int = 300
    enabled: bool = True


class JobToggleIn(BaseModel):
    enabled: bool


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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        alert = (
            float(payload.alert_threshold)
            if payload.alert_threshold is not None
            else float(detector.default_threshold)
        )
        critical = (
            float(payload.critical_threshold)
            if payload.critical_threshold is not None
            else alert * 1.5
        )
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
            "series": entries,
        }

    return router
