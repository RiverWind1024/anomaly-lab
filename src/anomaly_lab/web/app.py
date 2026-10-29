"""FastAPI 应用工厂：页面、序列 API 与静态资源。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from anomaly_lab.config import CONFIG
from anomaly_lab.data.loader import load_dataset

_WEB_DIR = Path(__file__).parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def _data_root() -> Path:
    return Path(os.environ.get("ANOMALY_LAB_DATA_DIR", str(CONFIG.data_dir)))


def _dataset_dir() -> Path:
    root = _data_root()
    synthetic = root / "synthetic"
    return synthetic if synthetic.exists() else root


def _series_map() -> dict:
    try:
        return {s.series_id: s for s in load_dataset(_dataset_dir())}
    except Exception:
        return {}


def create_app() -> FastAPI:
    app = FastAPI(title="anomaly-lab")
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

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
