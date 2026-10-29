"""数据不足时必须显式暴露，不能当成「一切正常」。"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from anomaly_lab.platform.runner import execute_job, run_dir
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app

QUERY = "SELECT ts, g, v FROM m WHERE $timefilter ORDER BY ts"


def _store_and_client(tmp_path: Path, rows):
    db = tmp_path / "src.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE m (ts TEXT, g TEXT, v REAL)")
    conn.executemany("INSERT INTO m VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
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
        missing_policy="drop",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=60,
    )
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    return store, job, TestClient(app)


def _rows(values):
    now = datetime.now(UTC).replace(microsecond=0)
    return [
        ((now - timedelta(minutes=60 - i)).isoformat(), "a", value)
        for i, value in enumerate(values)
    ]


def test_all_missing_series_is_marked_insufficient_not_normal(tmp_path):
    store, job, client = _store_and_client(tmp_path, _rows([None] * 60))
    run_id = execute_job(store, job.id, data_root=tmp_path)
    run = store.get_run(run_id)
    assert run.status == "insufficient_data"
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    entry = index["series"][0]
    assert entry["sufficient"] is False
    assert entry["n_alerts"] == 0
    assert entry["n_missing"] == 59

    preview = client.get(f"/api/platform/jobs/{job.id}/preview?run_id={run_id}")
    assert preview.status_code == 200
    body = preview.json()
    assert body["sufficient"] is False
    assert body["insufficient_reason"]
    assert body["values"] == []


def test_missing_points_are_reported_but_detection_still_runs(tmp_path):
    values = [float(i) for i in range(60)]
    values[10] = None
    store, job, client = _store_and_client(tmp_path, _rows(values))
    run_id = execute_job(store, job.id, data_root=tmp_path)
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    entry = index["series"][0]
    assert entry["sufficient"] is True
    assert entry["n_missing"] == 1
    assert entry["n_valid"] == 58
    body = client.get(f"/api/platform/jobs/{job.id}/preview?run_id={run_id}").json()
    assert body["sufficient"] is True
    assert len(body["values"]) == 58
    assert body["n_missing"] == 1
