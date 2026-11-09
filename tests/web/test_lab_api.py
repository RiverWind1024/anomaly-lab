"""Lab 预检 API：契约与错误码。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _db(path, *, n: int = 200) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
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
        query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="host",
    )
    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    return client, store, source, metric


def _payload(metric_id: int, **overrides):
    payload = {
        "kind": "metric",
        "metric_id": metric_id,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=200)).isoformat(),
        "sampling": {
            "window_points": 50,
            "stride_points": 50,
            "max_points": 200,
            "max_windows": 10,
        },
    }
    payload.update(overrides)
    return payload


def test_inspect_contract(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/inspect", json=_payload(metric.id))

    assert resp.status_code == 200
    body = resp.json()
    for key in ("spec", "freq", "window_points", "sampling", "period_capability", "series", "warnings"):
        assert key in body
    assert body["freq"] == "1h"
    assert body["window_points"] == 50
    series = body["series"][0]
    for key in ("series_id", "group", "n", "windows", "shape"):
        assert key in series
    window = series["windows"][0]
    for key in (
        "index",
        "start",
        "end",
        "n",
        "expected",
        "missing_ratio",
        "zero_ratio",
        "duplicate_timestamps",
        "on_grid_ratio",
        "sufficient",
        "classification",
        "classification_reason",
    ):
        assert key in window
    assert window["classification"]["metric_class"] == "periodic"
    assert window["classification"]["candidates"]


def test_inspect_sql_kind(tmp_path):
    client, _, source, _ = _client_and_store(tmp_path)
    payload = {
        "kind": "sql",
        "source_id": source.id,
        "sql": "SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
        "time_column": "ts",
        "value_column": "value",
        "freq": "1h",
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=200)).isoformat(),
        "sampling": {"window_points": 50, "stride_points": 50, "max_points": 200},
    }

    resp = client.post("/api/lab/inspect", json=payload)

    assert resp.status_code == 200
    assert [s["series_id"] for s in resp.json()["series"]] == ["lab"]


def test_inspect_unknown_metric_is_404(tmp_path):
    client, _, _, _ = _client_and_store(tmp_path)

    resp = client.post("/api/lab/inspect", json=_payload(999))

    assert resp.status_code == 404


def test_inspect_invalid_range_is_400(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)
    payload = _payload(metric.id, end=BASE.isoformat())

    resp = client.post("/api/lab/inspect", json=payload)

    assert resp.status_code == 400


def test_inspect_sql_missing_fields_is_400(tmp_path):
    client, _, source, _ = _client_and_store(tmp_path)
    payload = {
        "kind": "sql",
        "source_id": source.id,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=10)).isoformat(),
    }

    resp = client.post("/api/lab/inspect", json=payload)

    assert resp.status_code == 400
