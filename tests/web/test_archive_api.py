import json
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


def _run_once(client: TestClient) -> tuple[int, int]:
    """建好源 / 指标 / 任务并跑一次，返回 (job_id, run_id)。"""
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
            "name": "job",
            "detector": "seasonal",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
            "window_seconds": 60 * 300,
            "interval_seconds": 300,
        },
    ).json()
    run_id = client.post(f"/api/platform/jobs/{job['id']}/run").json()["run_id"]
    return job["id"], run_id


def _first_record(client: TestClient) -> dict:
    rows = client.get("/api/platform/detections?limit=1").json()["records"]
    assert rows
    return rows[0]


def test_delete_detection_record(tmp_path):
    client, store = _client(tmp_path)
    job_id, run_id = _run_once(client)
    record = _first_record(client)

    before = store.get_run(run_id)
    assert before.n_series >= 1
    assert before.n_alerts >= 1

    response = client.delete(
        f"/api/platform/detections/{record['run_id']}/{record['series_id']}"
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 1

    listing = client.get("/api/platform/detections?limit=20").json()
    assert listing["total"] == 0
    # 运行汇总要跟着重算，不能留下「已删记录」的告警点数
    after = store.get_run(run_id)
    assert after.n_series == 0
    assert after.n_alerts == 0
    # index.json 也要剔除 —— 否则预览页仍会列出已删记录
    index = json.loads(
        (tmp_path / "cache" / "platform" / "runs" / str(run_id) / "index.json").read_text(
            encoding="utf-8"
        )
    )
    assert index["series"] == []
    # 再删一次 → 404
    again = client.delete(
        f"/api/platform/detections/{record['run_id']}/{record['series_id']}"
    )
    assert again.status_code == 404
    # 任务本身不受影响
    assert client.get(f"/api/platform/jobs/{job_id}/runs").status_code == 200


def test_archive_flow_copies_record_and_survives_source_delete(tmp_path):
    client, _store = _client(tmp_path)
    _job_id, run_id = _run_once(client)
    record = _first_record(client)

    created = client.post(
        "/api/platform/archives", json={"name": "复盘", "description": "看误报"}
    )
    assert created.status_code == 200
    set_id = created.json()["id"]

    archived = client.post(
        f"/api/platform/archives/{set_id}/records",
        json={
            "run_id": record["run_id"],
            "series_id": record["series_id"],
            "description": "这波误报值得复盘",
        },
    )
    assert archived.status_code == 200
    archived_body = archived.json()
    assert archived_body["series_id"] == record["series_id"]
    assert archived_body["description"] == "这波误报值得复盘"
    assert archived_body["file"].startswith("archives/")

    detail = client.get("/api/platform/archives")
    assert detail.json()["sets"][0]["n_records"] == 1
    records = client.get(f"/api/platform/archives/{set_id}").json()["records"]
    assert len(records) == 1
    assert records[0]["description"] == "这波误报值得复盘"

    # 归档副本可独立查看（结构 = 平台运行详情）
    copy = client.get(f"/api/platform/archive-records/{archived_body['id']}")
    assert copy.status_code == 200
    body = copy.json()
    assert body["series_id"] == record["series_id"]
    assert len(body["values"]) > 0
    assert body["run_id"] == run_id

    # 原检测记录删掉后，归档仍可看
    assert (
        client.delete(
            f"/api/platform/detections/{record['run_id']}/{record['series_id']}"
        ).status_code
        == 200
    )
    assert client.get(f"/api/platform/archive-records/{archived_body['id']}").status_code == 200

    # 移出归档 → 副本文件被清理
    removed = client.delete(f"/api/platform/archives/{set_id}/records/{archived_body['id']}")
    assert removed.status_code == 200
    assert client.get(f"/api/platform/archive-records/{archived_body['id']}").status_code == 404


def test_archive_rejects_duplicate_and_missing_record(tmp_path):
    client, _store = _client(tmp_path)
    _job_id, _run_id = _run_once(client)
    record = _first_record(client)
    set_id = client.post("/api/platform/archives", json={"name": "复盘"}).json()["id"]

    payload = {"run_id": record["run_id"], "series_id": record["series_id"]}
    assert client.post(f"/api/platform/archives/{set_id}/records", json=payload).status_code == 200
    duplicate = client.post(f"/api/platform/archives/{set_id}/records", json=payload)
    assert duplicate.status_code == 400

    missing = client.post(
        f"/api/platform/archives/{set_id}/records",
        json={"run_id": 9999, "series_id": "nope"},
    )
    assert missing.status_code == 404


def test_delete_archive_set_removes_records(tmp_path):
    client, _store = _client(tmp_path)
    _job_id, _run_id = _run_once(client)
    record = _first_record(client)
    set_id = client.post("/api/platform/archives", json={"name": "复盘"}).json()["id"]
    client.post(
        f"/api/platform/archives/{set_id}/records",
        json={"run_id": record["run_id"], "series_id": record["series_id"]},
    )

    assert client.delete(f"/api/platform/archives/{set_id}").status_code == 200
    assert client.get("/api/platform/archives").json()["sets"] == []
    assert client.get(f"/api/platform/archives/{set_id}").status_code == 404
