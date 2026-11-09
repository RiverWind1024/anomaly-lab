"""Lab 实验记录 API：保存 / 列表 / 详情 / 一键建任务草稿。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, series TEXT, value REAL)")
    rows = []
    for i in range(400):
        ts = (BASE + timedelta(hours=i)).isoformat()
        rows.append((ts, "a", float(np.sin(2 * np.pi * i / 8))))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _client_and_store(tmp_path):
    db = tmp_path / "source.db"
    _db(db)
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db))
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="series",
    )
    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    return client, store, source, metric


def _payload(result: dict, **overrides):
    payload = {
        "kind": "metric",
        "metric_id": 1,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=400)).isoformat(),
        "sampling": {"window_points": 100, "stride_points": 100, "max_points": 400},
        "detectors": ["iqr"],
        "result": result,
    }
    payload.update(overrides)
    return payload


def _result() -> dict:
    return {
        "freq": "1h",
        "window_points": 100,
        "multipliers": ["1.5", "2.5"],
        "primary_multiplier": "2.5",
        "windows": [
            {
                "series_id": "m:a",
                "index": 0,
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-01-05T04:00:00+00:00",
                "n": 100,
                "expected": 100,
            }
        ],
        "results": [
            {
                "detector": "iqr",
                "per_window": [],
                "aggregate": {
                    "n_windows": 1,
                    "n_windows_skipped": 0,
                    "n_points": 100,
                    "n_alerts": 3,
                    "alert_ratio": 0.03,
                    "n_windows_with_alerts": 1,
                    "stability": 0.01,
                    "elapsed_ms": 0.4,
                    "sensitivity": {"1.5": 9, "2.5": 3},
                    "resolved_mix": {"iqr": 1},
                },
            }
        ],
        "warnings": [],
    }


def test_save_experiment_returns_id_and_persists(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/experiments", json=_payload(_result(), metric_id=metric.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]
    assert body["fingerprint"].startswith("sha256:")
    # 落在实验目录里，绝不碰 reports/
    assert (tmp_path / "lab" / "experiments" / f"{body['id']}.json").exists()
    assert not (tmp_path / "reports").exists()


def test_list_experiments_shows_saved_record(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)
    saved = client.post("/api/lab/experiments", json=_payload(_result(), metric_id=metric.id)).json()

    resp = client.get("/api/lab/experiments")

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == saved["id"]
    assert items[0]["summary"]["detectors"][0]["detector"] == "iqr"


def test_list_experiments_empty(tmp_path):
    client, _, _, _ = _client_and_store(tmp_path)

    resp = client.get("/api/lab/experiments")

    assert resp.status_code == 200
    assert resp.json() == []


def test_get_experiment_detail(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)
    saved = client.post("/api/lab/experiments", json=_payload(_result(), metric_id=metric.id)).json()

    resp = client.get(f"/api/lab/experiments/{saved['id']}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == saved["id"]
    assert body["result"]["results"][0]["detector"] == "iqr"
    # 记录里要能复现：spec + env 都在
    assert body["spec"]["metric_id"] == metric.id
    assert body["env"]["git_sha"] is None or isinstance(body["env"]["git_sha"], str)


def test_get_unknown_experiment_is_404(tmp_path):
    client, _, _, _ = _client_and_store(tmp_path)

    resp = client.get("/api/lab/experiments/nope")

    assert resp.status_code == 404


def test_job_draft_fills_form_fields(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)
    saved = client.post("/api/lab/experiments", json=_payload(_result(), metric_id=metric.id)).json()

    resp = client.post(f"/api/lab/experiments/{saved['id']}/job-draft")

    assert resp.status_code == 200
    draft = resp.json()
    assert draft["metric_id"] == metric.id
    assert draft["window_seconds"] == 100 * 3600
    assert draft["interval_seconds"] == 3600
    assert draft["detector"] == "iqr"
    assert draft["alert_rules"]
    assert draft["rationale"]


def test_job_draft_rejects_temporary_sql(tmp_path):
    client, _, source, _ = _client_and_store(tmp_path)
    payload = _payload(
        _result(),
        kind="sql",
        metric_id=None,
        source_id=source.id,
        sql="SELECT ts, value FROM metrics",
        time_column="ts",
        value_column="value",
        freq="1h",
    )
    saved = client.post("/api/lab/experiments", json=payload).json()

    resp = client.post(f"/api/lab/experiments/{saved['id']}/job-draft")

    assert resp.status_code == 400
    assert "临时 SQL" in resp.json()["detail"]


def test_job_draft_unknown_experiment_is_404(tmp_path):
    client, _, _, _ = _client_and_store(tmp_path)

    resp = client.post("/api/lab/experiments/nope/job-draft")

    assert resp.status_code == 404


def test_save_requires_result(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)
    payload = _payload(_result(), metric_id=metric.id)
    payload.pop("result")

    resp = client.post("/api/lab/experiments", json=payload)

    assert resp.status_code == 422
