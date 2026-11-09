"""平台反馈 API：人工反馈与「算法 × 倍数」调参建议。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.alerts import band_multiplier
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DEFAULT_DETECTOR_SET,
    DETECTOR_FACTORIES,
    create_detector,
    resolve_detector,
)
from anomaly_lab.platform.feedback import Annotation, SeriesOutcome, suggest_setting
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import freq_delta, utcnow
from anomaly_lab.web.platform_common import ApplySuggestionIn, FeedbackIn


def build_feedback_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()

    def _store() -> PlatformStore:
        return get_store()

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


    return router
