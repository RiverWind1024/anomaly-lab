"""SQLite exporter：增量累加、维度裁剪、保留期。"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from anomaly_lab.observability import Observability


@pytest.fixture
def obs(tmp_path):
    # ⚠️ 导出间隔设得很大 —— 测试手动 flush，不让后台线程抢跑。
    instance = Observability(data_root=tmp_path, export_interval_seconds=3600)
    yield instance
    instance.shutdown()


def _timeline_sum(obs: Observability, metric: str) -> float:
    rows = obs.store().timeline_rows("2000-01-01T00:00")
    return sum(float(row["value"] or 0) for row in rows if row["metric"] == metric)


def test_同一分钟的多次导出会累加(obs):
    """`force_flush` 可能在同一个分钟里被调多次，后一次不能覆盖前一次。"""
    obs.inc("http.requests", 2, method="GET", route="/a", status="200")
    obs.force_flush()
    obs.inc("http.requests", 3, method="GET", route="/a", status="200")
    obs.force_flush()

    assert _timeline_sum(obs, "http.requests") == 5


def test_时间线只存聚合量_不按路由拆(obs):
    """路由维度只进 totals，不进每分钟历史 —— 否则 30 天会被组合撑爆。"""
    obs.inc("http.requests", 1, method="GET", route="/a", status="200")
    obs.inc("http.requests", 1, method="GET", route="/b", status="200")
    obs.force_flush()

    rows = [
        row for row in obs.store().timeline_rows("2000-01-01T00:00")
        if row["metric"] == "http.requests"
    ]
    assert len(rows) == 1
    assert rows[0]["labels"] == ""
    assert rows[0]["value"] == 2


def test_totals_保留路由与状态维度(obs):
    obs.inc("http.requests", 4, method="GET", route="/a", status="200")
    obs.force_flush()

    totals = [row for row in obs.store().total_rows() if row["metric"] == "http.requests"]
    assert len(totals) == 1
    assert '"route": "/a"' in totals[0]["labels"]
    assert '"status": "200"' in totals[0]["labels"]


def test_直方图按分钟合并(obs):
    obs.observe_ms("http.request_ms", 5.0, method="GET", route="/a")
    obs.observe_ms("http.request_ms", 15.0, method="GET", route="/a")
    obs.force_flush()

    rows = [
        row for row in obs.store().timeline_rows("2000-01-01T00:00")
        if row["metric"] == "http.request_ms"
    ]
    assert len(rows) == 1
    assert rows[0]["count"] == 2
    assert rows[0]["sum"] == 20.0


def test_gauge_覆盖而不是累加(obs):
    obs.gauge("scheduler.due_jobs", 3)
    obs.force_flush()
    obs.gauge("scheduler.due_jobs", 0)
    obs.force_flush()

    totals = [row for row in obs.store().total_rows() if row["metric"] == "scheduler.due_jobs"]
    assert totals[-1]["value"] == 0


def test_超过保留期的样本会被清理(obs, tmp_path):
    old = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M")
    conn = sqlite3.connect(tmp_path / "metrics.db")
    conn.execute(
        "INSERT INTO metric_samples (minute, metric, labels, kind, value)"
        " VALUES (?, 'http.requests', '', 'sum', 9)",
        (old,),
    )
    conn.commit()
    conn.close()

    obs.inc("http.requests", 1)
    obs.force_flush()

    minutes = {row["minute"] for row in obs.store().timeline_rows("2000-01-01T00:00")}
    assert old not in minutes
