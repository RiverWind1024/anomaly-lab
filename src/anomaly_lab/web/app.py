"""FastAPI 应用工厂：JSON API + 前端构建产物（SPA）托管。"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from anomaly_lab.config import CONFIG
from anomaly_lab.contracts import DetectionResult
from anomaly_lab.data.loader import load_dataset
from anomaly_lab.evaluation.badcases import attribute_badcases
from anomaly_lab.evaluation.exclusions import ExclusionStore, exclusion_key
from anomaly_lab.evaluation.production import (
    DEFAULT_MAX_PER_LAYER,
    DEFAULT_RATE_ALERT,
    DEFAULT_RATE_NORMAL,
    OUTCOME_LABELS,
    evaluate_production,
    list_samples,
)
from anomaly_lab.lab.truth import REVIEWED_TYPE, annotations_path, load_annotations
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.validation import validate_identifier
from anomaly_lab.web.biz_state import biz_headers
from anomaly_lab.web.json_utils import clean_floats
from anomaly_lab.web.lab_routes import build_lab_router
from anomaly_lab.web.platform_routes import build_router
from anomaly_lab.web.source_query_routes import build_source_query_router


def _data_root() -> Path:
    return Path(os.environ.get("ANOMALY_LAB_DATA_DIR", str(CONFIG.data_dir)))


def _dataset_dir() -> Path:
    root = _data_root()
    synthetic = root / "synthetic"
    return synthetic if synthetic.exists() else root


class AnnotationInterval(BaseModel):
    """一条标注。

    两种形态：

    - **异常区间**：填 `start` / `end`（时间戳，naive ISO），`type` 是异常类型；
    - **整条记录核对过**：`type="reviewed"`，**不填** `start` / `end` ——
      窗口从 `run_id` 对应的检测记录里取。用户点一下「这条记录正常」即可，
      不用画区间。

    ⚠️ `start` / `end` 是**时间戳**，不是数组下标 ——
       序列一旦滚动，同一个下标就指向完全不同的时刻。
    """

    start: str | None = None
    end: str | None = None
    type: str = "spike"
    #: 标这条时**它所在层的采样率**（P3 的分层抽样反算要用）。
    #: 不填 = 不知道采样率（老数据 / 手工标注）。
    rate: float | None = None
    #: 标这条时它所在层的候选总量。
    layer_size: int | None = None


class AnnotationPayload(BaseModel):
    intervals: list[AnnotationInterval]


class ExclusionIn(BaseModel):
    """要排除的一条检测记录（序列 + 算法）。"""

    series_id: str
    detector: str


def _exclusions(data_root: Path) -> ExclusionStore:
    return ExclusionStore(Path(data_root) / "evaluation_exclusions.json")


def _report_path() -> Path:
    return CONFIG.reports_dir / "latest" / "report.json"


def _run_dir(data_root: Path, run_id: int) -> Path:
    """某次运行的产物目录。"""
    return Path(data_root) / "cache" / "platform" / "runs" / str(run_id)


def _detections_root() -> Path:
    return _data_root() / "cache" / "detections"


def _annotations_path(series_id: str) -> Path:
    """标注文件路径 —— **按序列存，不按运行**。

    ⚠️ 真值是**数据的属性**，不是某次运行的属性。滚动窗口下同一个异常
       会被连续几十次运行报出，按 run 存等于让用户把同一段标几十次。
       `run_id` 只作为「标它时看的是哪次运行」存进记录，不进路径。
    """
    return annotations_path(_data_root(), series_id)


def _series_map() -> dict:
    try:
        return {s.series_id: s for s in load_dataset(_dataset_dir())}
    except Exception:
        return {}


def _find_frontend_dist() -> Path | None:
    """从本文件向上找 frontend/dist。

    比写死 parents[3] 稳 —— wheel 安装下 parents[3] 指向 site-packages。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "frontend" / "dist"
        if candidate.is_dir():
            return candidate
    return None


def _npz_list(data, key: str) -> list[float]:
    """npz 里的可选浮点数组 → 列表；缺键 / 空数组都给 `[]`。

    ⚠️ 不能直接 `list(data[key])`：标量（0 维）会抛 `TypeError`，
       而老产物里这些键可能缺失。
    """
    if key not in data:
        return []
    import numpy as np

    return [float(v) for v in np.asarray(data[key], dtype=float).ravel()]


def create_app(
    platform_store: PlatformStore | None = None,
    platform_data_root: Path | None = None,
    start_scheduler: bool = False,
    frontend_dist: Path | None = None,
) -> FastAPI:
    data_root = Path(platform_data_root or _data_root())
    store = platform_store

    def get_store() -> PlatformStore:
        nonlocal store
        if store is None:
            store = PlatformStore(data_root / "platform.db")
        return store

    scheduler = None
    if start_scheduler:
        from anomaly_lab.platform.scheduler import Scheduler

        scheduler = Scheduler(get_store(), data_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scheduler is not None:
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.stop()

    app = FastAPI(title="anomaly-lab", lifespan=lifespan)
    app.include_router(build_router(get_store, lambda: data_root))
    app.include_router(build_source_query_router(get_store, lambda: data_root))
    app.include_router(build_lab_router(get_store, lambda: data_root))

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/series")
    def list_series() -> list[dict]:
        rows = []
        for s in _series_map().values():
            stamps = s.timestamps
            rows.append(
                {
                    "series_id": s.series_id,
                    "metric_class": s.meta.get("metric_class", "unknown"),
                    "n": len(s.values),
                    # ⚠️ labels 可能是 None（label_source == "none"）—— 直接 .sum() 会崩
                    "n_anomalies": int(s.labels.sum()) if s.labels is not None else 0,
                    # 时间范围 —— 前端要按时间筛序列
                    "start_ts": str(stamps[0])[:19] if len(stamps) else None,
                    "end_ts": str(stamps[-1])[:19] if len(stamps) else None,
                    # 数据来源维度 —— 评估报告按它聚合
                    "source": str(s.meta.get("source", "synthetic")),
                }
            )
        return rows

    @app.post("/api/annotate/{series_id}")
    def save_annotation(
        series_id: str, payload: AnnotationPayload, run_id: int | None = None
    ) -> dict:
        """保存一条标注。

        ⚠️ **按序列存** —— 一条标注覆盖所有时间轴包含该时段的检测记录。
           `run_id` 只记进记录里做溯源，不影响存储路径。
        """
        path = _annotations_path(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(UTC).isoformat()
        with path.open("a", encoding="utf-8") as handle:
            for item in payload.intervals:
                review = item.type == REVIEWED_TYPE
                # ⚠️ 异常区间必须有边界；「整条记录核对过」不需要 ——
                #    它的窗口从 run_id 对应的检测记录里取。
                if not review and (not item.start or not item.end):
                    raise HTTPException(
                        status_code=422,
                        detail=f"异常标注缺少时间边界：{item.type}",
                    )
                if review and run_id is None:
                    raise HTTPException(
                        status_code=422,
                        detail="「整条记录核对过」必须带 run_id",
                    )
                record = {
                    "series_id": series_id,
                    "type": item.type,
                    "created_at": created_at,
                }
                if item.start and item.end:
                    record["start"] = item.start
                    record["end"] = item.end
                if run_id is not None:
                    record["run_id"] = run_id
                # ⚠️ 采样率**跟着标注一起存** —— 采样率后来变了，
                #    这条标注仍按它当初的权重反算总体。
                if item.rate is not None:
                    record["rate"] = float(item.rate)
                if item.layer_size is not None:
                    record["layer_size"] = int(item.layer_size)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"saved": len(payload.intervals), "path": str(path)}

    @app.get("/api/annotate/{series_id}")
    def list_annotations(series_id: str, run_id: int | None = None) -> dict:
        """一条序列的全部标注（含旧的按 run 存的格式）。

        ⚠️ `run_id` 保留在签名里只为兼容老前端 —— 标注不再按 run 分开。
        """
        records = load_annotations(_data_root(), series_id)
        return {"series_id": series_id, "run_id": run_id, "intervals": records}

    @app.get("/api/evaluation/production")
    def production_evaluation(
        job_id: int | None = None,
        rate_alert: float = DEFAULT_RATE_ALERT,
        rate_normal: float = DEFAULT_RATE_NORMAL,
        max_per_layer: int | None = DEFAULT_MAX_PER_LAYER,
    ) -> dict:
        """生产检测记录 × 人工标注 → 分层的 P / R / F1。

        ⚠️ **流程是「先采样、再标注、最后评估」** ——
        `rate_alert` / `rate_normal` 决定各层抽多少比例的候选记录送去标注，
        评估用**所有已标注**的记录按各自采样率反算。

        ⚠️ **异常层与正常层分开采样** —— 正常记录远多于异常记录，
        同一个采样率要么标不完，要么异常样本太少。

        ⚠️ **只覆盖被标注过的那部分** —— 真值是人工标的，不是全集。
        """
        return evaluate_production(
            get_store(),
            data_root,
            job_id=job_id,
            rate_alert=rate_alert,
            rate_normal=rate_normal,
            max_per_layer=max_per_layer,
        )

    @app.get("/api/evaluation/production/samples")
    def production_samples(
        job_id: int | None = None,
        limit: int = 50,
        rate_alert: float = DEFAULT_RATE_ALERT,
        rate_normal: float = DEFAULT_RATE_NORMAL,
        max_per_layer: int | None = DEFAULT_MAX_PER_LAYER,
        todo: bool = False,
    ) -> list[dict]:
        """采样后的生产检测记录清单 —— 标注页的下拉用它。

        ⚠️ `todo=true` → 只给**还没标**的（待办队列）。
        """
        samples = list_samples(
            get_store(),
            data_root,
            job_id=job_id,
            rate_alert=rate_alert,
            rate_normal=rate_normal,
            max_per_layer=max_per_layer,
            limit=limit,
            todo_only=todo,
        )
        return [
            {
                "run_id": item.run_id,
                "series_id": item.series_id,
                "group": item.group,
                "job_id": item.job_id,
                "detector": item.detector,
                "source_id": item.source_id,
                "source_name": item.source_name,
                "metric_id": item.metric_id,
                "metric_name": item.metric_name,
                "n": item.n,
                "n_alerts": item.n_alerts,
                "start_ts": item.start_ts,
                "end_ts": item.end_ts,
                "n_annotations": item.n_annotations,
                "n_truth": item.n_truth,
                # ⚠️ 「核对过」= 评估有没有资格给这次运行打分。
                "reviewed": item.reviewed,
                "outcome": item.outcome,
                "outcome_label": OUTCOME_LABELS[item.outcome],
                # ⚠️ 采样率要带到前端 —— 标注时一起存下来，反算时按它加权。
                "rate": item.rate,
                "layer_size": item.layer_size,
            }
            for item in samples
        ]

    @app.get("/api/runs/{run_id}/series/{series_id}")
    def run_series_detail(run_id: int, series_id: str) -> dict:
        """某次运行里一条序列的完整时序 —— 标注页画波形用。

        ⚠️ **不用重新取数** —— run 的 npz 里已经存了 `timestamps / values /
           scores / severity`，直接读最准（跟当时跑的那份完全一致）。
        """
        index_path = _run_dir(data_root, run_id) / "index.json"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="该运行没有产物")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        matched = next(
            (
                entry
                for entry in index.get("series", [])
                if entry.get("series_id") == series_id
            ),
            None,
        )
        if matched is None:
            raise HTTPException(status_code=404, detail="该运行里没有这条序列")
        file_name = matched.get("file")
        if not file_name:
            raise HTTPException(status_code=404, detail="该运行里没有这条序列")
        npz_path = _run_dir(data_root, run_id) / file_name
        if not npz_path.is_file():
            raise HTTPException(status_code=404, detail="该运行的检测结果文件缺失")

        import numpy as np

        with np.load(npz_path) as data:
            stamps = np.asarray(data["timestamps"], dtype=np.int64)
            # ⚠️ **先按 ns 解释，再降到秒** —— 直接 `astype("datetime64[s]")`
            #    会把纳秒数值当成秒数，数值直接溢出。
            seconds = stamps.astype("datetime64[ns]").astype("datetime64[s]")
            return {
                "run_id": run_id,
                "series_id": series_id,
                "detector": str(data["detector"]) if "detector" in data else "",
                # ⚠️ 老产物没有这两个键 —— 缺失时按「正常尺度」兜底。
                "scale_source": str(data["scale_source"]) if "scale_source" in data else "",
                "status": str(data["status"]) if "status" in data else "ok",
                "scale_fallback": bool(data["scale_fallback"]) if "scale_fallback" in data else False,
                # 决策链来自本次运行的 index.json；老产物没有这一段 → 空对象。
                "decision": matched.get("decision") or {},
                "timestamps": [str(ts)[:19] for ts in seconds],
                "values": [float(v) for v in np.asarray(data["values"], dtype=float)],
                "scores": [float(v) for v in np.asarray(data["scores"], dtype=float)],
                "severity": [int(v) for v in np.asarray(data["severity"], dtype=int)],
                # 基线三件套 / 阈值 / 档位名 —— 有就带上，老产物缺键时给空值。
                # ⚠️ 空数组 ≠ null：前端按长度判断「有没有带」，别把空数组当「有带」。
                "baseline": _npz_list(data, "baseline"),
                "lower": _npz_list(data, "lower"),
                "upper": _npz_list(data, "upper"),
                "alert_threshold": (
                    float(data["alert_threshold"]) if "alert_threshold" in data else 0.0
                ),
                "critical_threshold": (
                    float(data["critical_threshold"])
                    if "critical_threshold" in data
                    else 0.0
                ),
                "score_type": str(data["score_type"]) if "score_type" in data else "",
                "levels": (
                    json.loads(str(data["levels"])) if "levels" in data else ["正常"]
                ),
                # ⚠️ 生产数据没有自带真值 —— 恒为空，真值来自人工标注。
                "labels": [],
            }

    @app.get("/api/summary")
    def summary() -> dict:
        path = _report_path()
        excluded = _exclusions(data_root).list()
        if not path.exists():
            return {
                "generated_at": None,
                "title": "",
                "summary": {},
                "rows": [],
                "excluded": excluded,
            }
        payload = json.loads(path.read_text(encoding="utf-8"))
        # 被排除的记录不展示 —— 但清单要一起给前端，
        # 好让用户看到「我排除了哪些」并能恢复。
        keys = {item["key"] for item in excluded}
        payload["rows"] = [
            row
            for row in payload.get("rows", [])
            if exclusion_key(str(row.get("series_id", "")), str(row.get("detector", "")))
            not in keys
        ]
        payload["excluded"] = excluded
        return payload

    @app.get("/api/evaluation/exclusions")
    def list_exclusions() -> dict:
        return {"excluded": _exclusions(data_root).list()}

    @app.post("/api/evaluation/exclusions")
    def add_exclusion(payload: ExclusionIn) -> dict:
        return _exclusions(data_root).add(payload.series_id, payload.detector)

    @app.delete("/api/evaluation/exclusions/{series_id}/{detector}")
    def remove_exclusion(series_id: str, detector: str) -> dict:
        if not _exclusions(data_root).remove(series_id, detector):
            raise HTTPException(status_code=404, detail="该记录不在排除清单里")
        return {"restored": True}

    @app.get("/api/badcases")
    def badcases(series_id: str, detector: str = "iqr") -> dict:
        """一条序列在某个检测算法下的结果。

        ⚠️ `detector` 会拼进文件路径（`cache/detections/<detector>/<id>.npz`）——
           **必须校验**，否则就是路径穿越。用 `validate_identifier`：
           无点、无斜杠，而 `stl_residual` / `deseasonalized_iqr` 这类名字都合法。

        ⚠️ 默认 `iqr` —— 老调用方（不带这个参数）行为不变。
        """
        series = _series_map().get(series_id)
        if series is None:
            raise HTTPException(status_code=404, detail="序列不存在")
        try:
            validate_identifier(detector, "detector")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        detection_dir = _detections_root() / detector
        path = detection_dir / f"{series_id}.npz"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="该序列还没有检测结果",
                headers=biz_headers("no_result"),
            )
        import numpy as np

        data = np.load(path, allow_pickle=False)
        # 基线三件套是**可选**的：旧版落盘的 npz 没有这三个键，
        # 只有三者都在、长度都对齐时才填进契约（契约要求同生同灭）。
        bands: dict[str, np.ndarray] = {}
        for key in ("expected", "lower", "upper"):
            if key in data.files:
                array = data[key].astype(float)
                if array.size == len(data["scores"]):
                    bands[key] = array
        has_bands = len(bands) == 3
        # 带的语义：老版本落盘的 npz 没有这个键
        band_kind = str(data["band_kind"]) if "band_kind" in data.files else ""
        result = DetectionResult(
            series_id=series_id,
            scores=data["scores"].astype(float),
            score_type=str(data["score_type"]),
            is_anomaly=data["is_anomaly"].astype(bool),
            threshold=float(data["threshold"]),
            detector=str(data["detector"]),
            elapsed_ms=float(data["elapsed_ms"]),
            expected=bands.get("expected"),
            lower=bands.get("lower"),
            upper=bands.get("upper"),
            band_kind=band_kind or None,  # type: ignore[arg-type]
        )
        cases = attribute_badcases(series, result)
        return {
            "series_id": series_id,
            "detector": result.detector,
            "threshold": result.threshold,
            "score_type": result.score_type,
            # ⚠️ 截到秒 —— datetime64[ns] 直接 str() 会带 9 位纳秒，
            #    图表 x 轴的标签会变成「2026-01-01T00:00:00.000000000」
            "timestamps": [str(ts)[:19] for ts in series.timestamps],
            "values": [float(v) for v in series.values],
            "scores": [float(v) for v in result.scores],
            # 基线带：NaN → None（前端会把 null 断线，不会画出假基线）
            "baseline": clean_floats(bands["expected"]) if has_bands else None,
            "lower": clean_floats(bands["lower"]) if has_bands else None,
            "upper": clean_floats(bands["upper"]) if has_bands else None,
            "band_kind": result.band_kind,
            "badcases": [
                {
                    "kind": case.kind,
                    "group": case.group,
                    "reason": case.reason,
                    "indices": case.indices,
                }
                for case in cases
            ],
        }

    @app.get("/api/series/{series_id}/values")
    def series_values(series_id: str) -> dict:
        series = _series_map().get(series_id)
        if series is None:
            raise HTTPException(status_code=404, detail="序列不存在")
        return {
            "series_id": series.series_id,
            # ⚠️ 截到秒 —— datetime64[ns] 直接 str() 会带 9 位纳秒，
            #    图表 x 轴的标签会变成「2026-01-01T00:00:00.000000000」
            "timestamps": [str(ts)[:19] for ts in series.timestamps],
            "values": [float(v) for v in series.values],
            "labels": [int(v) for v in series.labels],
        }

    # ---------- SPA 托管 ----------
    # ⚠️ 必须在所有 /api/* 路由之后（Starlette 按注册顺序匹配）。
    # ⚠️ 不要用 app.mount("/", ...)：Mount("/") 的正则会 FULL 匹配一切路径，
    #    注册在它之后的 catch-all 永远不会被命中。
    dist = frontend_dist if frontend_dist is not None else _find_frontend_dist()
    has_dist = dist is not None and dist.is_dir()
    assets_dir = dist / "assets" if has_dist else None

    # /assets 只在目录存在时挂载。
    # ⚠️ 不要用 check_dir=False 当安全网：Starlette 只跳过构造期检查，
    #    首次请求时 check_config() 仍会抛 RuntimeError。
    if assets_dir is not None and assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # 拼错的 API 不该拿到 HTML —— 这个判断要在 503 之前
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if not has_dist:
            raise HTTPException(
                status_code=503,
                detail="前端未构建，请先执行 make frontend-build",
            )
        # ⚠️ 安全：必须把 target 限制在 dist 之内。
        # 直接 dist / full_path 会形成任意文件读取：
        # GET /..%2fsecret.txt → full_path='../secret.txt' → dist/../secret.txt 存在
        # （字面量 '..' 会被 httpx 规范化掉，但百分号编码的 %2f 会原样到达 Starlette。）
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and target.is_relative_to(dist.resolve()):
            return FileResponse(target)
        return FileResponse(dist / "index.html")

    return app
