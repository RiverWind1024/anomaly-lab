"""平台运行产生的检测记录清单：`GET /api/platform/detections`。

⚠️ 与 `/api/summary`（离线回测报告）不是一回事 ——
   这里回答「任务实际跑出了什么」，包括「跑了但没告警」的记录。
"""

import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _make_job(tmp_path, *, name="job", detector="iqr"):
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
        name=name,
        detector=detector,
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


def _write_series(tmp_path, values) -> None:
    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (ts TEXT, value REAL)")
    end = utcnow().replace(second=0, microsecond=0)
    n = len(values)
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [
            (to_iso(end - timedelta(minutes=5 * (n - 1 - i))), float(value))
            for i, value in enumerate(values)
        ],
    )
    conn.commit()
    conn.close()


def _client(store, tmp_path) -> TestClient:
    return TestClient(create_app(platform_store=store, platform_data_root=tmp_path))


def test_检测记录包含每次运行的每条序列(tmp_path):
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [10.0] * 60)
    execute_job(store, job_id, data_root=tmp_path)

    body = _client(store, tmp_path).get("/api/platform/detections").json()
    assert body["total"] == 1
    record = body["records"][0]
    # 任务 / 指标维度：列表上要能看出「是谁跑的」
    assert record["job_id"] == job_id
    assert record["job_name"] == "job"
    assert record["metric_name"] == "cpu"
    assert record["started_at"]
    # 检测结论
    assert record["detector"] == "iqr"
    assert record["n"] == 60
    assert record["n_alerts"] == 0
    # ⚠️ 常数序列 → 尺度不可判。这条必须能从列表直接看出来，
    #    否则用户会以为「没告警 = 正常」。
    assert record["status"] == "undetermined"
    assert record["has_decision"] is True


def test_没有告警的记录也会出现在清单里(tmp_path):
    """「跑了但什么都没报」本身是结论 —— 不能只留下告警记录。"""
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [10.0 + (i % 5) for i in range(60)])
    execute_job(store, job_id, data_root=tmp_path)

    client = _client(store, tmp_path)
    all_rows = client.get("/api/platform/detections").json()
    alert_rows = client.get("/api/platform/detections", params={"only_alerts": True}).json()
    assert all_rows["total"] == 1
    assert alert_rows["total"] == 0


def test_按任务筛选与分页(tmp_path):
    store, first = _make_job(tmp_path, name="job-a")
    second = store.add_job(
        metric_id=store.get_job(first).metric_id,
        name="job-b",
        detector="mad",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    ).id
    _write_series(tmp_path, [10.0 + (i % 7) for i in range(60)])
    execute_job(store, first, data_root=tmp_path)
    execute_job(store, second, data_root=tmp_path)

    client = _client(store, tmp_path)
    assert client.get("/api/platform/detections").json()["total"] == 2
    only_a = client.get("/api/platform/detections", params={"job_id": first}).json()
    assert only_a["total"] == 1
    assert only_a["records"][0]["job_name"] == "job-a"

    page = client.get("/api/platform/detections", params={"limit": 1, "offset": 1}).json()
    assert len(page["records"]) == 1
    assert page["total"] == 2
    # 新的在前：offset=0 是 job-b（后跑的那次）
    first_page = client.get("/api/platform/detections", params={"limit": 1}).json()
    assert first_page["records"][0]["job_name"] == "job-b"


def test_决策链损坏时不影响列表(tmp_path):
    """⚠️ 老数据 / 坏 JSON 只该丢掉决策链，不该让整页 500。"""
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [10.0 + (i % 7) for i in range(60)])
    execute_job(store, job_id, data_root=tmp_path)
    with store._conn() as conn:  # 故意写坏，模拟历史脏数据
        conn.execute("UPDATE run_series SET decision_json = 'not-json'")

    body = _client(store, tmp_path).get("/api/platform/detections").json()
    assert body["records"][0]["has_decision"] is False
    assert body["records"][0]["status"] == "ok"
