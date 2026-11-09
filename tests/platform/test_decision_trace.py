import json
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.decisions import DecisionTrace
from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app


def test_决策链只保留非空段():
    trace = DecisionTrace(
        classify={"metric_class": "sparse_event", "confidence": 0.9},
        select={"detector": "event_count", "requested": "auto"},
    )
    data = trace.to_dict()
    assert set(data) == {"classify", "select"}
    assert data["select"]["detector"] == "event_count"


def test_运行结果落库后能读回决策链(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id, name="cpu",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts", value_column="value",
    )
    job = store.add_job(
        metric_id=metric.id, name="job", detector="iqr",
        alert_threshold=2.5, critical_threshold=4.0,
        window_seconds=60 * 300, interval_seconds=300,
    )
    # ⚠️ run_series 有外键，必须先有 runs 行
    run = store.create_run(job.id)
    store.finish_run(run.id, "success", n_series=1, n_alerts=0)
    store.record_run_series(
        run.id,
        # ⚠️ file 不能为空 —— detection_records() 的 SQL 带 `WHERE rs.file <> ''`
        [{"series_id": "s", "file": "x.npz",
          "decision": {"select": {"detector": "iqr"}}}],
    )

    rows = store.detection_records()
    assert json.loads(rows[0]["decision_json"])["select"]["detector"] == "iqr"


def _seed(tmp_path):
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(60):
        ts = (start + timedelta(minutes=5 * i)).isoformat()
        rows.append((ts, "a", float(i % 10) + (50.0 if i == 30 else 0.0)))
        rows.append((ts, "b", float(i % 5)))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="demo",
        query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="host",
        time_format="iso_utc",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="seasonal",
        alert_threshold=1.0,
        critical_threshold=2.0,
        window_seconds=60 * 300,
        interval_seconds=300,
    )
    return store, job, start


def test_真实运行落库的决策链有六段(tmp_path):
    store, job, start = _seed(tmp_path)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    rows = store.detection_records(job_id=job.id)
    assert len(rows) == 2
    for row in rows:
        decision = json.loads(row["decision_json"])
        assert set(decision) == {
            "quality",
            "capability",
            "classify",
            "select",
            "threshold",
            "detect",
        }
        assert decision["quality"]["n"] > 0
        assert decision["select"]["requested"] == "seasonal"
        assert decision["detect"]["n_alerts"] >= 0
    assert store.get_run(run_id).status == "success"


def test_预览接口返回的决策链是对象(tmp_path):
    store, job, start = _seed(tmp_path)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    body = client.get(
        f"/api/platform/jobs/{job.id}/preview?run_id={run_id}"
    ).json()
    assert isinstance(body["decision"], dict)
    assert set(body["decision"]) == {
        "quality",
        "capability",
        "classify",
        "select",
        "threshold",
        "detect",
    }
