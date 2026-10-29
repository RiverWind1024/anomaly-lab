import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _client(tmp_path):
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = utcnow() - timedelta(minutes=5 * 61)
    for i in range(61):
        ts = to_iso(start + timedelta(minutes=5 * i))
        conn.execute(
            "INSERT INTO metrics VALUES (?, ?, ?)",
            (ts, "a", float(i % 10) + (40.0 if i == 30 else 0.0)),
        )
    conn.commit()
    conn.close()
    store = PlatformStore(tmp_path / "platform.db")
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    return TestClient(app), store


def test_create_source_metric_job_run_and_preview(tmp_path):
    client, _store = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    assert source.status_code == 200
    source_id = source.json()["id"]

    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source_id,
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
            "freq": "5min",
        },
    )
    assert metric.status_code == 200

    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "seasonal",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
            "window_points": 60,
            "interval_seconds": 300,
        },
    )
    assert job.status_code == 200
    job_id = job.json()["id"]

    run = client.post(f"/api/platform/jobs/{job_id}/run")
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    preview = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}")
    assert preview.status_code == 200
    body = preview.json()
    assert body["series_id"] == "demo:a"
    # 窗口是 [now - 60 点, now)，边界点是否命中取决于秒级对齐
    assert 59 <= len(body["values"]) <= 60
    assert len(body["baseline"]) == len(body["values"])
    assert set(body["severity"]) <= {0, 1, 2}
    assert body["alert_threshold"] == 1.0


def test_platform_page_and_catalog(tmp_path):
    client, _ = _client(tmp_path)
    page = client.get("/platform")
    assert page.status_code == 200
    assert "定时检测" in page.text
    catalog = client.get("/api/platform/catalog").json()
    assert "seasonal" in [item["name"] for item in catalog["detectors"]]
    assert catalog["sources"] == []


def test_invalid_query_returns_400(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    response = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "bad",
            "query": "DELETE FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "value_column": "value",
        },
    )
    assert response.status_code == 400
    assert "SELECT" in response.json()["detail"]


def test_job_defaults_thresholds_from_detector(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric.json()["id"], "name": "job", "detector": "seasonal"},
    )
    assert job.status_code == 200
    payload = job.json()
    assert payload["alert_threshold"] == 2.5
    assert payload["critical_threshold"] == 3.75


def test_runs_endpoint_lists_history(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "seasonal",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
        },
    )
    job_id = job.json()["id"]
    client.post(f"/api/platform/jobs/{job_id}/run")
    runs = client.get(f"/api/platform/jobs/{job_id}/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "success"


def test_preview_downsamples_long_series(tmp_path, monkeypatch):
    """点数过多时预览要抽样，避免一次返回上兆的 JSON。"""
    from anomaly_lab.web import platform_routes

    monkeypatch.setattr(platform_routes, "MAX_PREVIEW_POINTS", 20)
    client, _store = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "iqr",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
            "window_points": 60,
            "interval_seconds": 300,
        },
    )
    job_id = job.json()["id"]
    run_id = client.post(f"/api/platform/jobs/{job_id}/run").json()["run_id"]
    body = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}").json()
    assert body["sampled"] is True
    assert len(body["values"]) <= 20
    assert body["original_n"] > 20
    assert len(body["values"]) == len(body["scores"]) == len(body["severity"])
