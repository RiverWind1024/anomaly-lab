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
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.biz_state import biz_headers
from anomaly_lab.web.platform_routes import build_router


def _data_root() -> Path:
    return Path(os.environ.get("ANOMALY_LAB_DATA_DIR", str(CONFIG.data_dir)))


def _dataset_dir() -> Path:
    root = _data_root()
    synthetic = root / "synthetic"
    return synthetic if synthetic.exists() else root


class AnnotationInterval(BaseModel):
    start: int
    end: int
    type: str = "spike"


class AnnotationPayload(BaseModel):
    intervals: list[AnnotationInterval]


def _report_path() -> Path:
    return CONFIG.reports_dir / "latest" / "report.json"


def _detections_root() -> Path:
    return _data_root() / "cache" / "detections"


def _annotations_path(series_id: str) -> Path:
    return _data_root() / "annotations" / f"{series_id}.jsonl"


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
    def save_annotation(series_id: str, payload: AnnotationPayload) -> dict:
        path = _annotations_path(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(UTC).isoformat()
        with path.open("a", encoding="utf-8") as handle:
            for item in payload.intervals:
                record = {
                    "series_id": series_id,
                    "start": item.start,
                    "end": item.end,
                    "type": item.type,
                    "created_at": created_at,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"saved": len(payload.intervals), "path": str(path)}

    @app.get("/api/annotate/{series_id}")
    def list_annotations(series_id: str) -> dict:
        path = _annotations_path(series_id)
        records = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        return {"series_id": series_id, "intervals": records}

    @app.get("/api/summary")
    def summary() -> dict:
        path = _report_path()
        if not path.exists():
            return {"generated_at": None, "title": "", "summary": {}, "rows": []}
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/badcases")
    def badcases(series_id: str) -> dict:
        series = _series_map().get(series_id)
        if series is None:
            raise HTTPException(status_code=404, detail="序列不存在")
        detection_dir = _detections_root() / "iqr"
        path = detection_dir / f"{series_id}.npz"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="该序列还没有检测结果",
                headers=biz_headers("no_result"),
            )
        import numpy as np

        data = np.load(path, allow_pickle=False)
        result = DetectionResult(
            series_id=series_id,
            scores=data["scores"].astype(float),
            score_type=str(data["score_type"]),
            is_anomaly=data["is_anomaly"].astype(bool),
            threshold=float(data["threshold"]),
            detector=str(data["detector"]),
            elapsed_ms=float(data["elapsed_ms"]),
        )
        cases = attribute_badcases(series, result)
        return {
            "series_id": series_id,
            "detector": result.detector,
            "threshold": result.threshold,
            "score_type": result.score_type,
            "timestamps": [str(ts) for ts in series.timestamps],
            "values": [float(v) for v in series.values],
            "scores": [float(v) for v in result.scores],
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
            "timestamps": [str(ts) for ts in series.timestamps],
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
