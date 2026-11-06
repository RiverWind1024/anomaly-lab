"""尺度来源与「无法判定」必须一路传到 API。"""

import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _make_job(tmp_path):
    """⚠️ tests/ 不是 package，不能跨文件 import helper —— 就地复制建库代码。"""
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="cpu",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


def _write_constant_series(tmp_path) -> None:
    """60 个完全相同的点 —— 尺度必然是 0，结果确定是「无法判定」。"""
    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (ts TEXT, value REAL)")
    end = utcnow().replace(second=0, microsecond=0)
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [(to_iso(end - timedelta(minutes=5 * (59 - i))), 7.0) for i in range(60)],
    )
    conn.commit()
    conn.close()


def test_预览返回尺度来源(tmp_path):
    store, job_id = _make_job(tmp_path)
    _write_constant_series(tmp_path)
    execute_job(store, job_id, data_root=tmp_path)

    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    body = client.get(f"/api/platform/jobs/{job_id}/preview").json()
    # ⚠️ 这个 fixture 是 60 个完全相同的点 —— 结果**确定**是不可判，
    #    不能用 `in {...}` 这种宽松断言，否则接口兜底默认值也能通过。
    assert body["scale_source"] == "none"
    assert body["status"] == "undetermined"
