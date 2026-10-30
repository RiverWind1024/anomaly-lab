"""告警中心端点：跨任务汇总 + 筛选 + skipped 诚实报告。"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(platform_data_root=tmp_path))


def _client_with_data(tmp_path):
    """造一个带异常点的数据源（跟 tests/web/test_platform.py 同一套路）。"""
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


def _seed_source_metric_job(client) -> int:
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    ).json()
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric["id"],
            "name": "demo-job",
            "detector": "iqr",
            "alert_rules": [{"multiplier": 2.5, "level": "P1"}],
        },
    ).json()
    return job["id"]


def test_alerts_endpoint_returns_empty_list_when_no_job(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/platform/alerts").json()
    assert body["events"] == []
    assert body["jobs"] == []


def test_job_without_run_is_reported_as_skipped(tmp_path):
    """⚠️ 没跑过的任务不能静默消失 —— 必须进 skipped 并说明原因。"""
    client = _client(tmp_path)
    _seed_source_metric_job(client)
    body = client.get("/api/platform/alerts").json()
    assert body["events"] == []
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["name"] == "demo-job"
    assert "运行记录" in body["skipped"][0]["reason"]


def test_alerts_contract_fields(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/platform/alerts").json()
    for key in ("events", "levels", "jobs", "skipped"):
        assert key in body


def _run_job(client) -> int:
    """建源 → 指标 → 任务 → 立即运行，返回 job_id。"""
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
            "freq": "5min",
        },
    ).json()
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric["id"],
            "name": "demo-job",
            "detector": "iqr",
            "window_points": 61,
            "alert_rules": [{"multiplier": 2.5, "level": "P1"}],
        },
    ).json()
    response = client.post(f"/api/platform/jobs/{job['id']}/run")
    assert response.status_code == 200, response.text
    return job["id"]


def test_alerts_reports_events_after_a_real_run(tmp_path):
    """端到端：跑一次任务 → 端点能给出告警事件。"""
    client, _store = _client_with_data(tmp_path)
    job_id = _run_job(client)
    body = client.get("/api/platform/alerts").json()
    assert body["events"], body
    event = body["events"][0]
    assert event["job_id"] == job_id
    assert event["job_name"] == "demo-job"
    assert event["series_id"]
    assert event["level_index"] >= 1
    assert event["level"] == "P1"
    assert event["n_points"] >= 1
    assert event["start_ts"] <= event["end_ts"]
    # 跑过之后就不该再进 skipped
    assert body["skipped"] == []


def test_alerts_filters_by_job_and_level(tmp_path):
    client, _store = _client_with_data(tmp_path)
    job_id = _run_job(client)
    body = client.get(f"/api/platform/alerts?job_id={job_id}").json()
    assert body["events"]
    assert all(item["job_id"] == job_id for item in body["events"])

    body = client.get("/api/platform/alerts?job_id=99999").json()
    assert body["events"] == []

    body = client.get("/api/platform/alerts?level=P1").json()
    assert body["events"]
    assert all(item["level"] == "P1" for item in body["events"])

    body = client.get("/api/platform/alerts?level=P0").json()
    assert body["events"] == []


def test_alerts_filters_by_series_and_time_range(tmp_path):
    client, _store = _client_with_data(tmp_path)
    _run_job(client)
    body = client.get("/api/platform/alerts").json()
    series_id = body["events"][0]["series_id"]

    filtered = client.get(f"/api/platform/alerts?series_id={series_id}").json()
    assert filtered["events"]
    assert all(item["series_id"] == series_id for item in filtered["events"])

    # 时间范围之外 → 空
    assert client.get("/api/platform/alerts?since=2099-01-01").json()["events"] == []
    assert client.get("/api/platform/alerts?until=1970-01-01").json()["events"] == []


def test_alerts_levels_are_derived_from_actual_data(tmp_path):
    """档位下拉的候选值来自实际数据，不是硬编码。"""
    client, _store = _client_with_data(tmp_path)
    _run_job(client)
    body = client.get("/api/platform/alerts").json()
    assert body["levels"] == ["P1"]
    assert body["jobs"] == [{"id": body["jobs"][0]["id"], "name": "demo-job"}]
