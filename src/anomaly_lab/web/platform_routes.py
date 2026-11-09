"""平台 API：数据源 / 指标 / 检测任务的配置、运行与预览。"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from anomaly_lab.platform import retention
from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.alerts import (
    band_multiplier_or_none,
    highest_multiplier,
    level_labels,
    parse_rules,
    rules_to_dicts,
)
from anomaly_lab.platform.capability import probe
from anomaly_lab.platform.compare import compare_series
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DEFAULT_DETECTOR,
    DETECTOR_FACTORIES,
    create_detector,
    detector_available,
    resolve_detector,
)
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import freq_delta, utcnow
from anomaly_lab.web.biz_state import biz_headers
from anomaly_lab.web.platform_common import (
    MAX_PREVIEW_POINTS,
    JobIn,
    JobToggleIn,
    MetricIn,
    MetricPatchIn,
    SourceIn,
    SourcePatchIn,
    _clean,
    _not_found,
    _sample_indices,
)
from anomaly_lab.web.platform_feedback_routes import build_feedback_router
from anomaly_lab.web.platform_read_routes import build_read_router


def build_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()
    router.include_router(build_read_router(get_store, get_data_root))
    router.include_router(build_feedback_router(get_store, get_data_root))

    def _store() -> PlatformStore:
        return get_store()

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
                alert_direction=payload.alert_direction or "both",
                detect_points=payload.detect_points,
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
        # 能力探测的周期判定要用真实频率 —— 用错频率会把长周期误判成不存在
        freq = store.get_metric(job.metric_id).freq
        for outcome in result.outcomes:
            entry = dict(outcome.entry)
            entry.pop("file", None)
            arrays = outcome.arrays
            # 能力探测只**报告**，不改数据 —— 与 lab 的体检同一套结论。
            # ⚠️ 数据不足时没有 values，无法探测：`results` 与 `series` 都不加
            #    这个键，前端只在 `sufficient` 时读它。
            cap_payload: dict | None = None
            if arrays:
                cap = probe(arrays["values"], freq)
                cap_payload = {
                    "zero_ratio": cap.zero_ratio,
                    "n_nonzero": cap.n_nonzero,
                    "count_ready": cap.count_ready,
                    "verdict": cap.verdict,
                    "warnings": [
                        {"detector": w.detector, "reason": w.reason}
                        for w in cap.warnings
                    ],
                    "shape_warnings": [
                        {"detector": w.detector, "reason": w.reason}
                        for w in cap.shape_warnings
                    ],
                    "has_period": cap.has_period,
                    "detrended_structure": cap.detrended_structure,
                    "message": cap.message,
                }
                entry["capability"] = cap_payload
            entries.append(entry)
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

            # ⚠️ 必须**先**转 `datetime64[ns]` 再转 `[s]` ——
            #    数组里存的是 int64 纳秒，直接转 `[s]` 会把纳秒当成秒，
            #    时间戳变成「五百年后」这种看不懂的东西。
            timestamps = arrays["timestamps"].astype("datetime64[ns]").astype("datetime64[s]")
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
                    "capability": cap_payload,
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
            "alert_direction": job.alert_direction,
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
                "scale_source": "",
                "status": "ok",
                "scale_fallback": False,
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
                "alert_direction": "both",
                "direction_applied": True,                # 数据不足时决策链只有 quality + capability —— index.json 里已有的就是那段
                "decision": entry.get("decision") or {},
                "series": entries,
            }

        target = runner_module.run_dir(get_data_root(), chosen_run)
        payload = np.load(target / entry["file"], allow_pickle=False)
        timestamps = payload["timestamps"].astype("datetime64[ns]")
        baseline_arr = payload["baseline"]
        lower = payload["lower"]
        upper = payload["upper"]
        has_bands = baseline_arr.size > 0

        values_all = payload["values"]
        scores_all = payload["scores"]
        severity_all = payload["severity"]
        sample_index = _sample_indices(len(values_all), MAX_PREVIEW_POINTS)
        sampled = sample_index is not None
        if sampled:
            values_all = values_all[sample_index]
            scores_all = scores_all[sample_index]
            severity_all = severity_all[sample_index]
            timestamps = timestamps[sample_index]
            if has_bands:
                baseline_arr = baseline_arr[sample_index]
                lower = lower[sample_index]
                upper = upper[sample_index]

        return {
            "run_id": chosen_run,
            "job_id": job.id,
            "detector": str(payload["detector"]),
            "requested_detector": str(payload["requested_detector"]),
            "metric_class": str(payload["metric_class"]),
            "detector_rationale": str(payload["detector_rationale"]),
            "detector_fallback": bool(entry.get("fallback", False)),
            "score_type": str(payload["score_type"]),
            # ⚠️ 老产物没有这两个键 —— 用 get 兜底，不能 KeyError。
            "scale_source": entry.get("scale_source", ""),
            "status": entry.get("status", "ok"),
            "scale_fallback": bool(entry.get("scale_fallback", False)),
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
            "baseline": _clean(baseline_arr) if has_bands else None,
            "lower": _clean(lower) if has_bands else None,
            "upper": _clean(upper) if has_bands else None,
            "severity": [int(item) for item in severity_all],
            "alert_threshold": float(payload["alert_threshold"]),
            "critical_threshold": float(payload["critical_threshold"]),
            "alert_rules": json.loads(str(payload["alert_rules"])),
            "levels": json.loads(str(payload["levels"])),
            "alert_direction": entry.get("alert_direction", "both"),
            "direction_applied": bool(entry.get("direction_applied", True)),
            # 决策链 —— 与当时落库的那份一致，不在读的时候重算。
            "decision": entry.get("decision") or {},
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
