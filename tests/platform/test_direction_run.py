"""告警方向端到端：配置变了，落库的告警区间与 n_alerts 都要跟着变。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.platform.alerts import apply_direction
from anomaly_lab.platform.runner import execute_job, run_dir
from anomaly_lab.platform.store import PlatformStore

#: 向下尖峰 / 向上尖峰在序列里的位置
DOWN_INDEX = 100
UP_INDEX = 150
N_POINTS = 240


def _seed(tmp_path):
    """一条「中间有一次向下尖峰 + 一次向上尖峰」的序列。"""
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, value REAL)")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(7)
    rows = []
    for i in range(N_POINTS):
        ts = (start + timedelta(minutes=5 * i)).isoformat()
        value = 50.0 + float(rng.normal(0, 0.2))
        if i == DOWN_INDEX:
            value = 20.0
        elif i == UP_INDEX:
            value = 80.0
        rows.append((ts, value))
    conn.executemany("INSERT INTO metrics VALUES (?, ?)", rows)
    conn.commit()
    conn.close()

    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="demo",
        query="SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column=None,
        time_format="iso_utc",
    )
    return store, metric, start


def _run_direction(store, metric, start, direction):
    job = store.add_job(
        metric_id=metric.id,
        name=f"job-{direction}",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=3.75,
        window_seconds=N_POINTS * 300,
        interval_seconds=300,
        alert_direction=direction,
    )
    run_id = execute_job(
        store,
        job.id,
        data_root=store.db_path.parent,
        start=start,
        end=start + timedelta(minutes=5 * N_POINTS),
    )
    index = json.loads(
        (run_dir(store.db_path.parent, run_id) / "index.json").read_text(encoding="utf-8")
    )
    entry = index["series"][0]
    payload = np.load(run_dir(store.db_path.parent, run_id) / entry["file"])
    timestamps = payload["timestamps"].astype("datetime64[ns]").astype("datetime64[s]")
    return (
        entry,
        payload,
        timestamps,
        store.alert_events_for_run(run_id),
    )


def test_above只报向上尖峰(tmp_path):
    store, metric, start = _seed(tmp_path)
    entry, payload, timestamps, events = _run_direction(
        store, metric, start, "above"
    )
    severity = payload["severity"]
    assert severity[UP_INDEX] > 0
    assert severity[DOWN_INDEX] == 0
    assert entry["n_alerts"] == 1
    assert [row["start_ts"] for row in events] == [str(timestamps[UP_INDEX])]
    assert entry["alert_direction"] == "above"
    assert entry["direction_applied"] is True


def test_below只报向下尖峰(tmp_path):
    store, metric, start = _seed(tmp_path)
    entry, payload, timestamps, events = _run_direction(
        store, metric, start, "below"
    )
    severity = payload["severity"]
    assert severity[DOWN_INDEX] > 0
    assert severity[UP_INDEX] == 0
    assert entry["n_alerts"] == 1
    assert [row["start_ts"] for row in events] == [str(timestamps[DOWN_INDEX])]
    assert entry["alert_direction"] == "below"
    assert entry["direction_applied"] is True


def test_both两个尖峰都报(tmp_path):
    store, metric, start = _seed(tmp_path)
    entry, payload, timestamps, events = _run_direction(store, metric, start, "both")
    severity = payload["severity"]
    assert severity[DOWN_INDEX] > 0
    assert severity[UP_INDEX] > 0
    assert entry["n_alerts"] == 2
    assert sorted(row["start_ts"] for row in events) == sorted(
        [str(timestamps[DOWN_INDEX]), str(timestamps[UP_INDEX])]
    )
    assert entry["alert_direction"] == "both"


def test_方向可以更新且非法值被拒绝(tmp_path):
    store, metric, _ = _seed(tmp_path)
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=3.75,
        window_seconds=N_POINTS * 300,
        interval_seconds=300,
    )
    assert job.alert_direction == "both"
    assert store.update_job_config(job.id, alert_direction="below").alert_direction == "below"
    try:
        store.update_job_config(job.id, alert_direction="up")
    except ValueError as exc:
        assert "告警方向" in str(exc)
    else:  # pragma: no cover - 走到这里说明校验没生效
        raise AssertionError("非法方向应当被拒绝")


def test_老库迁移补上alert_direction列(tmp_path):
    """真实旧 schema（有 alert_rules、无 alert_direction）→ 打开后补列且能读回。"""
    db = tmp_path / "platform.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          metric_id INTEGER NOT NULL,
          name TEXT NOT NULL UNIQUE,
          detector TEXT NOT NULL,
          alert_threshold REAL NOT NULL,
          critical_threshold REAL NOT NULL,
          window_points INTEGER NOT NULL,
          interval_seconds INTEGER NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          last_run_at TEXT,
          next_run_at TEXT,
          created_at TEXT NOT NULL,
          alert_rules TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute(
        "INSERT INTO jobs (metric_id, name, detector, alert_threshold,"
        " critical_threshold, window_points, interval_seconds, created_at, alert_rules)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "old-job",
            "iqr",
            2.5,
            3.75,
            240,
            300,
            "2026-01-01T00:00:00",
            '[{"multiplier": 2.5, "level": "P1"}]',
        ),
    )
    conn.commit()
    conn.close()

    PlatformStore(db)
    reopened = PlatformStore(db)

    conn = sqlite3.connect(db)
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(jobs)")}
    conn.close()
    assert "alert_direction" in columns
    # PRAGMA 行：(cid, name, type, notnull, dflt_value, pk)
    assert columns["alert_direction"][4] == "'both'"

    jobs = reopened.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].alert_direction == "both"


def test_both方向与关闭过滤完全一致():
    """⚠️ 默认方向必须是结构性 no-op —— 不是「过滤后碰巧相等」。"""
    severity = np.array([0, 1, 2, 3, 0, 2])
    values = np.array([10.0, 12.0, 8.0, 15.0, 10.0, 5.0])
    baseline = np.array([10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    out, applied = apply_direction(severity, values, baseline, "both")
    assert applied is True
    assert np.array_equal(out, severity)


def test_未知方向直接报错():
    with pytest.raises(ValueError, match="未知告警方向"):
        apply_direction(np.array([0, 1]), np.array([1.0, 2.0]), None, "up")
