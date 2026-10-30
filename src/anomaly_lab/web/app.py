"""FastAPI 应用工厂：页面、序列 API 与静态资源。"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from anomaly_lab.config import CONFIG
from anomaly_lab.contracts import DetectionResult
from anomaly_lab.data.loader import load_dataset
from anomaly_lab.evaluation.badcases import attribute_badcases
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.biz_state import biz_headers
from anomaly_lab.web.platform_routes import build_router

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


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


def create_app(
    platform_store: PlatformStore | None = None,
    platform_data_root: Path | None = None,
    start_scheduler: bool = False,
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
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
    app.include_router(build_router(get_store, lambda: data_root))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return _TEMPLATES.TemplateResponse(
            request, "index.html", {"series_count": len(_series_map())}
        )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/series")
    def list_series() -> list[dict]:
        return [
            {
                "series_id": s.series_id,
                "metric_class": s.meta.get("metric_class", "unknown"),
                "n": len(s.values),
                "n_anomalies": int(s.labels.sum()),
            }
            for s in _series_map().values()
        ]

    @app.get("/annotate", response_class=HTMLResponse)
    def annotate_page(request: Request):
        return _TEMPLATES.TemplateResponse(request, "annotate.html", {})

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

    @app.get("/report", response_class=HTMLResponse)
    def report_page(request: Request):
        return _TEMPLATES.TemplateResponse(request, "report.html", {})

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

    return app
