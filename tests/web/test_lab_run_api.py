"""Lab 多算法实验 API：契约与错误码。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _db(path, *, n: int = 600) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, series TEXT, value REAL)")
    rows = []
    for i in range(n):
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


def _payload(metric_id: int, **overrides):
    payload = {
        "kind": "metric",
        "metric_id": metric_id,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=600)).isoformat(),
        "sampling": {
            "window_points": 100,
            "stride_points": 100,
            "max_points": 600,
            "max_windows": 10,
        },
    }
    payload.update(overrides)
    return payload


def test_run_contract(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/run", json=_payload(metric.id, detectors=["auto", "iqr"]))

    assert resp.status_code == 200
    body = resp.json()
    for key in ("spec", "freq", "window_points", "multipliers", "windows", "results", "warnings"):
        assert key in body
    assert [item["detector"] for item in body["results"]] == ["auto", "iqr"]
    run = body["results"][0]
    for key in ("detector", "per_window", "aggregate"):
        assert key in run
    for key in (
        "n_windows",
        "n_points",
        "n_alerts",
        "alert_ratio",
        "stability",
        "elapsed_ms",
        "sensitivity",
    ):
        assert key in run["aggregate"]
    window = run["per_window"][0]
    for key in ("series_id", "window_index", "detector", "n_alerts", "alert_ratio", "sensitivity"):
        assert key in window


def test_run_defaults_to_auto_plus_candidates(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/run", json=_payload(metric.id))

    assert resp.status_code == 200
    names = [item["detector"] for item in resp.json()["results"]]
    assert names[0] == "auto"
    assert len(names) > 1


def test_run_rejects_unknown_detector(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/run", json=_payload(metric.id, detectors=["nope"]))

    assert resp.status_code == 400
    assert "检测器" in resp.json()["detail"]


def test_run_unknown_metric_is_404(tmp_path):
    client, _, _, _ = _client_and_store(tmp_path)

    resp = client.post("/api/lab/run", json=_payload(999))

    assert resp.status_code == 404


def test_run_accepts_custom_multipliers(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post(
        "/api/lab/run", json=_payload(metric.id, detectors=["iqr"], multipliers=[1.5, 4.0])
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["multipliers"] == ["1.5", "4.0"]
    assert set(body["results"][0]["aggregate"]["sensitivity"]) == {"1.5", "4.0"}
