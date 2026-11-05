"""Lab 单窗口时序数据 API：契约与错误码。"""

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
        freq="1h",
    )
    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    return client, store, source, metric


def _payload(metric_id: int, **overrides):
    payload = {
        "kind": "metric",
        "metric_id": metric_id,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=400)).isoformat(),
        "sampling": {"window_points": 100, "stride_points": 100, "max_points": 400},
        "series_id": "m:a",
        "window_index": 0,
    }
    payload.update(overrides)
    return payload


def test_window_contract(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/window", json=_payload(metric.id))

    assert resp.status_code == 200
    body = resp.json()
    for key in ("series_id", "window_index", "start", "end", "freq", "n", "timestamps", "values"):
        assert key in body
    assert len(body["timestamps"]) == len(body["values"]) == body["n"]
    detector = body["detectors"][0]
    for key in ("detector", "resolved", "scores", "severity", "baseline", "n_alerts"):
        assert key in detector
    assert len(detector["scores"]) == body["n"]


def test_window_accepts_detector_list(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/window", json=_payload(metric.id, detectors=["iqr", "zscore"]))

    assert resp.status_code == 200
    assert [item["detector"] for item in resp.json()["detectors"]] == ["iqr", "zscore"]


def test_window_unknown_series_is_404(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/window", json=_payload(metric.id, series_id="m:nope"))

    assert resp.status_code == 404


def test_window_unknown_index_is_404(tmp_path):
    client, _, _, metric = _client_and_store(tmp_path)

    resp = client.post("/api/lab/window", json=_payload(metric.id, window_index=99))

    assert resp.status_code == 404


def test_window_unknown_metric_is_404(tmp_path):
    client, _, _, _ = _client_and_store(tmp_path)

    resp = client.post("/api/lab/window", json=_payload(999))

    assert resp.status_code == 404
