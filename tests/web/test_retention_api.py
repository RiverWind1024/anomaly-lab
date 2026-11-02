"""`/api/platform/storage` 与 `/api/platform/prune`：让「自动清理」可见。"""

from datetime import timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _client(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    store.add_job(
        metric_id=metric.id,
        name="j",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=60,
    )
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    return TestClient(app), store


def _add_run(store: PlatformStore, job_id: int, *, age_hours: float) -> int:
    run = store.create_run(job_id)
    store.finish_run(run.id, "success", n_series=1, n_alerts=0)
    with store._conn() as conn:
        conn.execute(
            "UPDATE runs SET started_at = ? WHERE id = ?",
            (to_iso(utcnow() - timedelta(hours=age_hours)), run.id),
        )
    return run.id


def test_storage_reports_policy_and_usage(tmp_path):
    client, store = _client(tmp_path)
    job_id = store.list_jobs()[0].id
    _add_run(store, job_id, age_hours=1)

    resp = client.get("/api/platform/storage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy"]["max_runs_per_job"] == 100
    assert body["policy"]["max_age_hours"] == 24
    assert body["runs"]["kept"] == 1
    assert body["database"]["bytes"] > 0
    assert body["last_pruned_at"] is None


def test_prune_deletes_expired_runs(tmp_path, monkeypatch):
    """⚠️ 超窗的运行被清掉 —— 这是「所有不断产生的数据会自动清理」的落点。"""
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_HOURS", "24")
    client, store = _client(tmp_path)
    job_id = store.list_jobs()[0].id
    old = _add_run(store, job_id, age_hours=48)
    _add_run(store, job_id, age_hours=1)

    resp = client.post("/api/platform/prune")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_runs"] == 1
    assert body["kept_runs"] == 1
    assert old not in {run.id for run in store.all_runs()}
    # 响应里带最新的占用 —— 前端不用再发一次请求
    assert body["storage"]["runs"]["kept"] == 1


def test_prune_records_last_pruned_at(tmp_path):
    client, store = _client(tmp_path)
    job_id = store.list_jobs()[0].id
    _add_run(store, job_id, age_hours=1)

    client.post("/api/platform/prune")
    body = client.get("/api/platform/storage").json()
    assert body["last_pruned_at"] is not None
