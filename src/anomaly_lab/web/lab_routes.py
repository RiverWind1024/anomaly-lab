"""指标预检实验台（Lab）的 HTTP 入口。

⚠️ P0 只有**一次调用**：取数 → 采样 → 体检 → 形态推断。
   不落盘、不建任务、不写 reports/latest。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from anomaly_lab.lab.detect import run_experiment, window_detail
from anomaly_lab.lab.evaluate import evaluate_experiment
from anomaly_lab.lab.inspect import inspect
from anomaly_lab.lab.records import (
    build_job_draft,
    list_experiments,
    load_experiment,
    save_experiment,
)
from anomaly_lab.lab.spec import DataSpec, PublicSpec, SamplingSpec, SyntheticSpec
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import parse_iso

TimeFormat = Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]


class SamplingIn(BaseModel):
    """采样参数。默认值与 docs/LAB.md 一致。"""

    mode: Literal["recent", "even", "stratified"] = "even"
    window_points: int = Field(default=500, gt=0)
    stride_points: int | None = Field(default=None, gt=0)
    max_points: int = Field(default=10_000, gt=0)
    max_windows: int = Field(default=100, gt=0)
    min_valid_ratio: float = Field(default=0.8, ge=0.0, le=1.0)
    seed: int = 42


class SyntheticIn(BaseModel):
    """合成数据参数（P3）。"""

    metric_class: str = "stationary"
    n_points: int = Field(default=1000, gt=0)
    n_anomalies: int = Field(default=5, ge=0)
    anomaly_types: list[str] = Field(default_factory=list)
    seed: int = 42


class PublicIn(BaseModel):
    """公开集参数（P3）。"""

    dataset: Literal["nab", "ucr"] = "nab"
    name: str | None = None
    limit: int = Field(default=20, gt=0)


class LabInspectIn(BaseModel):
    """一次预检请求。"""

    kind: Literal["metric", "sql", "synthetic", "public"]
    start: str
    end: str
    metric_id: int | None = None
    source_id: int | None = None
    sql: str | None = None
    time_column: str | None = None
    value_column: str | None = None
    group_column: str | None = None
    time_format: TimeFormat = "iso_utc"
    source_timezone: str = "UTC"
    freq: str | None = None
    missing_policy: str | None = None
    max_series: int = Field(default=20, gt=0)
    sampling: SamplingIn = Field(default_factory=SamplingIn)
    #: 真值来源（P3）：`annotation` = 读人工标注文件。
    truth: Literal["none", "annotation"] = "none"
    synthetic: SyntheticIn = Field(default_factory=SyntheticIn)
    public: PublicIn = Field(default_factory=PublicIn)


class LabRunIn(LabInspectIn):
    """一次多算法对比实验请求。

    ⚠️ `detectors` 留空 → 用 `auto` + 形态推荐的候选。
    """

    detectors: list[str] | None = None
    #: 倍数敏感性的档位；留空用默认（1.5 ~ 4.0）。
    multipliers: list[float] | None = None


class LabEvaluateIn(LabRunIn):
    """一次**有真值**的评估请求（P3）。

    ⚠️ `split_ratio` = 校准集占比；剩下的时间给测试集。
    """

    #: 校准 / 测试的切分比例 —— 前一份校准，后一份测试。
    split_ratio: float = Field(default=0.5, gt=0.0, lt=1.0)


class LabExperimentIn(LabRunIn):
    """保存一条实验记录。

    ⚠️ `result` 是 `/api/lab/run` 的返回 —— 后端**不重跑**，
       记录的就是用户屏幕上看到的那一份（重跑会因数据源变化而对不上）。
    """

    result: dict


class LabWindowIn(LabInspectIn):
    """拉单个窗口的详细时序数据（画图用）。"""

    series_id: str
    window_index: int
    #: 要画哪些算法；留空只画 `auto`。
    detectors: list[str] | None = None


def _to_spec(payload: LabInspectIn) -> DataSpec:
    sampling = SamplingSpec(**payload.sampling.model_dump())
    return DataSpec(
        kind=payload.kind,
        start=parse_iso(payload.start),
        end=parse_iso(payload.end),
        metric_id=payload.metric_id,
        source_id=payload.source_id,
        sql=payload.sql,
        time_column=payload.time_column,
        value_column=payload.value_column,
        group_column=payload.group_column,
        time_format=payload.time_format,
        source_timezone=payload.source_timezone,
        freq=payload.freq,
        missing_policy=payload.missing_policy,
        max_series=payload.max_series,
        sampling=sampling,
        truth=payload.truth,
        synthetic=SyntheticSpec(
            metric_class=payload.synthetic.metric_class,
            n_points=payload.synthetic.n_points,
            n_anomalies=payload.synthetic.n_anomalies,
            anomaly_types=tuple(payload.synthetic.anomaly_types),
            seed=payload.synthetic.seed,
        ),
        public=PublicSpec(
            dataset=payload.public.dataset,
            name=payload.public.name,
            limit=payload.public.limit,
        ),
    )


def _check_refs(store: PlatformStore, spec: DataSpec) -> None:
    """确认 spec 引用的对象存在（不存在 → 404）。

    ⚠️ 合成 / 公开集**不引用平台里的任何对象** —— 它们自己就是数据。
    """
    if spec.kind == "metric":
        store.get_metric(spec.metric_id)  # type: ignore[arg-type]
    elif spec.kind == "sql":
        store.get_source_raw(spec.source_id)  # type: ignore[arg-type]


def build_lab_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/lab/inspect")
    def lab_inspect(payload: LabInspectIn) -> dict:
        """跑一次预检。"""
        store = get_store()

        # 先校验参数（缺字段 / 范围非法 → 400），再确认引用的对象存在（→ 404）。
        try:
            spec = _to_spec(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            _check_refs(store, spec)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            return inspect(store, get_data_root(), spec)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/lab/run")
    def lab_run(payload: LabRunIn) -> dict:
        """在同一批窗口上跑多个检测器，产出对比画像。

        ⚠️ **不落盘** —— 产物全在响应里。
        """
        store = get_store()

        try:
            spec = _to_spec(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            _check_refs(store, spec)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            return run_experiment(
                store,
                get_data_root(),
                spec,
                detectors=payload.detectors,
                multipliers=payload.multipliers,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/lab/evaluate")
    def lab_evaluate(payload: LabEvaluateIn) -> dict:
        """有真值的评估（P3）：校准集选阈值，测试集报 F1。

        ⚠️ **不落盘** —— 产物全在响应里。
        """
        store = get_store()

        try:
            spec = _to_spec(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            _check_refs(store, spec)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            return evaluate_experiment(
                store,
                get_data_root(),
                spec,
                detectors=payload.detectors,
                split_ratio=payload.split_ratio,
                multipliers=payload.multipliers,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/lab/window")
    def lab_window(payload: LabWindowIn) -> dict:
        """单个窗口的详细时序数据 —— 供前端画图。

        ⚠️ **按需拉取**：一次实验可能上百个窗口，全量带曲线会把响应撑爆。
        """
        store = get_store()

        try:
            spec = _to_spec(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            _check_refs(store, spec)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            return window_detail(
                store,
                get_data_root(),
                spec,
                series_id=payload.series_id,
                window_index=payload.window_index,
                detectors=payload.detectors,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/lab/experiments")
    def lab_save_experiment(payload: LabExperimentIn) -> dict:
        """保存一条实验记录（spec + env + result）。

        ⚠️ 落在 `{data_root}/lab/experiments/` —— 与 `reports/latest/` 物理隔离。
        """
        store = get_store()

        try:
            spec = _to_spec(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        metric_name: str | None = None
        metric_freq: str | None = None
        try:
            if spec.kind == "metric":
                metric = store.get_metric(spec.metric_id)  # type: ignore[arg-type]
                metric_name = metric.name
                metric_freq = metric.freq
            elif spec.kind == "sql":
                store.get_source_raw(spec.source_id)  # type: ignore[arg-type]
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        # 记录「实际跑了什么」—— 以结果为准，不以请求为准
        detectors = [
            str(item.get("detector")) for item in payload.result.get("results", []) if item.get("detector")
        ]
        multipliers = payload.result.get("multipliers") or payload.multipliers
        if multipliers:
            multipliers = [float(value) for value in multipliers]

        return save_experiment(
            get_data_root(),
            spec=spec,
            result=payload.result,
            detectors=detectors,
            multipliers=multipliers,
            metric_name=metric_name,
            freq=metric_freq,
        )

    @router.get("/api/lab/experiments")
    def lab_list_experiments() -> list[dict]:
        """实验记录列表 —— 新的在前，每条只带摘要。"""
        return list_experiments(get_data_root())

    @router.get("/api/lab/experiments/{record_id}")
    def lab_get_experiment(record_id: str) -> dict:
        """实验记录详情（含完整结果）。"""
        try:
            return load_experiment(get_data_root(), record_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/lab/experiments/{record_id}/job-draft")
    def lab_job_draft(record_id: str) -> dict:
        """从实验记录生成任务草稿 —— **只回填表单，不创建任务**。"""
        try:
            record = load_experiment(get_data_root(), record_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            return build_job_draft(record)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
