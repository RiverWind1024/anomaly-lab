import json
import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np

from anomaly_lab.platform.runner import execute_job, run_dir
from anomaly_lab.platform.store import PlatformStore


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
        freq="5min",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="seasonal",
        alert_threshold=1.0,
        critical_threshold=2.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job, start


def test_execute_job_writes_index_and_arrays(tmp_path):
    store, job, start = _seed(tmp_path)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    run = store.get_run(run_id)
    assert run.status == "success"
    assert run.n_series == 2
    assert run.n_alerts > 0
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    assert len(index["series"]) == 2
    entry = index["series"][0]
    payload = np.load(run_dir(tmp_path, run_id) / entry["file"])
    for key in ("timestamps", "values", "scores", "baseline", "lower", "upper", "severity"):
        assert key in payload
    assert payload["severity"].max() <= 2
    assert payload["values"].shape == payload["scores"].shape
    assert np.all(payload["lower"] <= payload["upper"])


def test_severity_levels_follow_thresholds(tmp_path):
    store, job, start = _seed(tmp_path)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    entry = next(item for item in index["series"] if item["group"] == "a")
    payload = np.load(run_dir(tmp_path, run_id) / entry["file"])
    severity = payload["severity"]
    scores = payload["scores"]
    alert = float(payload["alert_threshold"])
    critical = float(payload["critical_threshold"])
    assert np.all(severity[scores >= critical] == 2)
    assert np.all(severity[(scores >= alert) & (scores < critical)] == 1)
    assert np.all(severity[scores < alert] == 0)


def test_detect_points_limits_alerts_to_last_n(tmp_path):
    """`detect_points=3` 时只有最后 3 个点参与告警，更早的点只用于统计基线。

    种子数据在 i=30 有一个尖峰 —— 它落在历史段里，不该再产生告警；
    分数仍然照常算出（图表能看到历史曲线的偏离），只是 severity 为 0。
    """
    store, job, start = _seed(tmp_path)
    store.update_job_config(job.id, detect_points=3)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    entry = next(item for item in index["series"] if item["group"] == "a")
    payload = np.load(run_dir(tmp_path, run_id) / entry["file"])
    severity = payload["severity"]
    scores = payload["scores"]
    assert len(severity) == 60
    # 历史段：分数照常算，但不告警
    assert np.all(severity[:-3] == 0)
    assert scores[30] > 0
    # 告警计数只统计检测段
    assert entry["n_alerts"] == int((severity > 0).sum())
    assert entry["n_p0"] == int((severity == 2).sum())


def test_detect_points_zero_keeps_whole_window(tmp_path):
    """0 = 检测整个窗口（旧行为）—— 历史尖峰照常告警。"""
    store, job, start = _seed(tmp_path)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    entry = next(item for item in index["series"] if item["group"] == "a")
    payload = np.load(run_dir(tmp_path, run_id) / entry["file"])
    assert entry["n_alerts"] > 0
    assert np.any(payload["severity"][:-3] > 0)


def test_absolute_condition_raises_level_on_high_values(tmp_path):
    """绝对值条件作为后处理并行生效：值 > 40 的点直接抬到 P1 档。"""
    store, job, start = _seed(tmp_path)
    absolute_job = store.add_job(
        metric_id=job.metric_id,
        name="abs-job",
        detector="seasonal",
        alert_threshold=3.0,
        critical_threshold=3.0,
        window_points=60,
        interval_seconds=300,
        alert_rules=[
            {"multiplier": 3.0, "level": "P2"},
            {"op": ">", "value": 40, "level": "P1"},
        ],
    )
    run_id = execute_job(
        store,
        absolute_job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=300),
    )
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    entry = next(item for item in index["series"] if item["group"] == "a")
    payload = np.load(run_dir(tmp_path, run_id) / entry["file"])
    severity = payload["severity"]
    values = payload["values"]
    # 种子数据里只有一个点（i=30）值超过 40
    assert int((values > 40).sum()) == 1
    assert np.all(severity[values > 40] == 2)
    assert severity.max() == 2


def test_auto_detector_records_per_series_choice(tmp_path):
    """auto 模式下每条序列各自推断检测器，并把选择结果记录下来。"""
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(0)
    rows = []
    for i in range(240):
        ts = (start + timedelta(minutes=5 * i)).isoformat()
        rows.append((ts, "periodic", float(np.sin(2 * np.pi * i / 24))))
        rows.append((ts, "steady", float(rng.normal())))
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
        freq="5min",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="auto-job",
        detector="auto",
        alert_threshold=2.5,
        critical_threshold=3.75,
        window_points=240,
        interval_seconds=300,
    )
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        start=start,
        end=start + timedelta(minutes=240 * 5),
    )
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    chosen = {item["group"]: item["detector"] for item in index["series"]}
    assert chosen["periodic"] == "seasonal"
    assert chosen["steady"] in {"iqr", "mad", "zscore"}
    # 推断依据要落盘，便于用户核对与覆盖
    payload = np.load(run_dir(tmp_path, run_id) / index["series"][0]["file"])
    assert str(payload["requested_detector"]) == "auto"
    assert str(payload["metric_class"]) != ""


def test_execute_job_records_failure(tmp_path):
    store, job, start = _seed(tmp_path)
    (tmp_path / "platform" / "source.db").unlink()
    try:
        execute_job(
            store,
            job.id,
            data_root=tmp_path,
            start=start,
            end=start + timedelta(hours=1),
        )
    except FileNotFoundError:
        pass
    runs = store.list_runs(job.id)
    assert runs[0].status == "failed"
    assert "不存在" in runs[0].error


def test_execute_job_uses_window_points_when_no_explicit_range(tmp_path):
    store, job, start = _seed(tmp_path)
    run_id = execute_job(
        store,
        job.id,
        data_root=tmp_path,
        now=start + timedelta(minutes=60 * 5),
    )
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text(encoding="utf-8"))
    assert index["series"][0]["n"] == 60
