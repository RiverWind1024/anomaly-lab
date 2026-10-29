"""生成一个可直接运行的 demo：SQLite 源库 + 指标 + 检测任务。

时间戳平移到「当前时刻往前」，这样调度器立刻就能取到窗口内的数据。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import freq_delta, to_iso, utcnow

SOURCE_NAME = "demo-sqlite"
METRIC_NAME = "demo-metric"
JOB_NAME = "demo-job"
QUERY = "SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts"
FREQ = "5min"
N_POINTS = 500
ALERT_THRESHOLD = 2.5
CRITICAL_THRESHOLD = 4.0
WINDOW_POINTS = 500
INTERVAL_SECONDS = 300


def _build_source_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS metrics (ts TEXT, series TEXT, value REAL)")
    existing = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
    if existing:
        conn.close()
        return

    end = utcnow().replace(second=0, microsecond=0)
    step = freq_delta(FREQ)
    rows: list[tuple[str, str, float]] = []
    for name, metric_class, seed in (
        ("web-api", "periodic", 101),
        ("web-worker", "stationary", 102),
    ):
        series = generate_series(metric_class, n=N_POINTS, seed=seed, freq=FREQ)
        for index, value in enumerate(series.values):
            timestamp = to_iso(end - step * (N_POINTS - 1 - index))
            rows.append((timestamp, name, float(value)))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def seed_demo(data_root: Path) -> dict:
    """幂等地写入 demo 数据源、指标与检测任务，返回它们的 ID。"""
    data_root = Path(data_root)
    store = PlatformStore(data_root / "platform.db")
    source_path = data_root / "platform" / "source.db"
    _build_source_db(source_path)

    source = store.find_source_by_name(SOURCE_NAME)
    if source is None:
        source = store.add_source(SOURCE_NAME, "platform/source.db")

    metric = store.find_metric_by_name(source.id, METRIC_NAME)
    if metric is None:
        metric = store.add_metric(
            source_id=source.id,
            name=METRIC_NAME,
            query=QUERY,
            time_column="ts",
            value_column="value",
            group_column="series",
            time_format="iso",
            freq=FREQ,
        )

    job = store.find_job_by_name(JOB_NAME)
    if job is None:
        job = store.add_job(
            metric_id=metric.id,
            name=JOB_NAME,
            detector="seasonal",
            alert_threshold=ALERT_THRESHOLD,
            critical_threshold=CRITICAL_THRESHOLD,
            window_points=WINDOW_POINTS,
            interval_seconds=INTERVAL_SECONDS,
        )

    return {
        "source_id": source.id,
        "metric_id": metric.id,
        "job_id": job.id,
        "source_path": str(source_path),
        "n_points": int(N_POINTS * 2),
    }
