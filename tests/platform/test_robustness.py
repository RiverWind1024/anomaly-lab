"""平台切片的健壮性回归：连接泄漏、WAL、run 归属、并发去重、配置校验、错误透传。"""

import gc
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.scheduler import Scheduler
from anomaly_lab.platform.sqlite_source import load_series
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app

QUERY = "SELECT ts, g, v FROM m WHERE $timefilter ORDER BY ts"


def _source_db(root: Path, n: int = 60, name: str = "src.db") -> Path:
    db = root / name
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE m (ts TEXT, g TEXT, v REAL)")
    now = datetime.now(UTC).replace(microsecond=0)
    conn.executemany(
        "INSERT INTO m VALUES (?, ?, ?)",
        [
            ((now - timedelta(minutes=n - i)).isoformat(), "a", float(i % 10))
            for i in range(n)
        ],
    )
    conn.commit()
    conn.close()
    return db


def _metric() -> Metric:
    return Metric(
        id=1,
        source_id=1,
        name="d",
        query=QUERY,
        time_column="ts",
        value_column="v",
        group_column="g",
        time_format="iso_utc",
        freq="1min",
        created_at="",
    )


def _store_with_job(root: Path, db: Path, name: str = "job"):
    store = PlatformStore(root / "platform.db")
    source = store.add_source(f"src-{name}", str(db))
    metric = store.add_metric(
        source_id=source.id,
        name=f"m-{name}",
        query=QUERY,
        time_column="ts",
        value_column="v",
        group_column="g",
        time_format="iso_utc",
        freq="1min",
    )
    job = store.add_job(
        metric_id=metric.id,
        name=name,
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=60,
    )
    return store, job


# ---------- #4 只读取数不能泄漏连接 ----------


def _live_connections() -> int:
    import gc

    return sum(1 for obj in gc.get_objects() if isinstance(obj, sqlite3.Connection))


def test_repeated_loading_does_not_leak_sqlite_connections(tmp_path):
    db = _source_db(tmp_path)
    metric = _metric()
    now = datetime.now(UTC)
    load_series(metric, db, now - timedelta(hours=1), now + timedelta(hours=1))
    gc.collect()
    before = _live_connections()
    for _ in range(20):
        load_series(metric, db, now - timedelta(hours=1), now + timedelta(hours=1))
    gc.collect()
    after = _live_connections()
    assert after - before <= 1, f"存活连接从 {before} 涨到 {after}，疑似连接泄漏"


# ---------- #5 SQLite 应该开 WAL ----------


def test_store_enables_wal_mode(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    conn = sqlite3.connect(store.db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


# ---------- #8 配置期就要拦住非法频率 ----------


def test_add_metric_rejects_invalid_frequency(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", "a.db")
    with pytest.raises(ValueError, match="频率"):
        store.add_metric(
            source_id=source.id,
            name="m",
            query=QUERY,
            time_column="ts",
            value_column="v",
            group_column="g",
            time_format="iso_utc",
            freq="每周",
        )


# ---------- #6 preview 不能拿别的 job 的 run ----------


def test_preview_rejects_run_from_another_job(tmp_path):
    db = _source_db(tmp_path)
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db))
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query=QUERY,
        time_column="ts",
        value_column="v",
        group_column="g",
        time_format="iso_utc",
        freq="1min",
    )
    job_a = store.add_job(
        metric_id=metric.id, name="A", detector="iqr", alert_threshold=2.5,
        critical_threshold=4.0, window_points=60, interval_seconds=60,
    )
    job_b = store.add_job(
        metric_id=metric.id, name="B", detector="iqr", alert_threshold=2.5,
        critical_threshold=4.0, window_points=60, interval_seconds=60,
    )
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    client = TestClient(app)
    run_a = client.post(f"/api/platform/jobs/{job_a.id}/run").json()["run_id"]
    run_b = client.post(f"/api/platform/jobs/{job_b.id}/run").json()["run_id"]
    assert run_a != run_b
    response = client.get(f"/api/platform/jobs/{job_a.id}/preview?run_id={run_b}")
    assert response.status_code == 404
    assert "run_id" in response.json()["detail"]


# ---------- #7 同一 job 不应并发跑两次 ----------


def test_concurrent_manual_run_and_schedule_share_one_run(tmp_path, monkeypatch):
    db = _source_db(tmp_path)
    store, job = _store_with_job(tmp_path, db)

    started = threading.Event()
    release = threading.Event()
    # ⚠️ runner 里的 load_series 签名变了（多了 store）——
    #    monkeypatch 的目标必须是 runner 那个，不是 sqlite_source 的薄壳
    from anomaly_lab.platform import runner as runner_module

    real_load = runner_module.load_series

    def slow_load(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return real_load(*args, **kwargs)

    monkeypatch.setattr("anomaly_lab.platform.runner.load_series", slow_load)

    manual_result = {}

    def manual():
        manual_result["run_id"] = execute_job(store, job.id, data_root=tmp_path)

    thread = threading.Thread(target=manual)
    thread.start()
    assert started.wait(timeout=5)

    scheduler = Scheduler(store, tmp_path, runner=execute_job)
    scheduled = scheduler.tick(now=datetime.now(UTC))
    release.set()
    thread.join(timeout=10)

    assert scheduled == [manual_result["run_id"]]
    assert len(store.list_runs(job.id)) == 1


# ---------- #9 非预期异常也要把原因透给调用方 ----------


def test_run_endpoint_reports_unexpected_error(tmp_path, monkeypatch):
    db = _source_db(tmp_path)
    store, job = _store_with_job(tmp_path, db)

    def boom(*args, **kwargs):
        raise RuntimeError("检测器内部炸了")

    monkeypatch.setattr("anomaly_lab.platform.runner.execute_job", boom)
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    client = TestClient(app)
    response = client.post(f"/api/platform/jobs/{job.id}/run")
    assert response.status_code == 400
    assert "检测器内部炸了" in response.json()["detail"]


def test_failed_run_reason_is_visible_in_runs_api(tmp_path):
    db = _source_db(tmp_path)
    store, job = _store_with_job(tmp_path, db)
    (tmp_path / "src.db").unlink()
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    client = TestClient(app)
    client.post(f"/api/platform/jobs/{job.id}/run")
    runs = client.get(f"/api/platform/jobs/{job.id}/runs").json()["runs"]
    assert runs[0]["status"] == "failed"
    assert runs[0]["error"]
