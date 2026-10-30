"""概览端点：一次请求拿全整个系统的运行情况。

概览页要展示数据源 / 指标 / 任务 / 告警 / 运行 / 反馈的统计。
如果让前端自己去拼，就得发 N 个请求（每个任务一次 runs、一次 feedback）——
概览页是登录后第一屏，不该这么浪费。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(platform_data_root=tmp_path))


def test_overview_contract(tmp_path):
    """概览的结构要固定 —— 前端按它渲染。"""
    client = _client(tmp_path)
    body = client.get("/api/platform/overview").json()
    for key in ("counts", "runs", "alerts", "feedback", "jobs"):
        assert key in body
    assert set(body["counts"]) == {"sources", "metrics", "jobs", "enabled_jobs"}
    assert set(body["runs"]) >= {"total", "success", "failed"}
    assert set(body["alerts"]) >= {"total", "by_level", "by_job", "top_series"}
    assert set(body["feedback"]) >= {"total", "by_kind"}


def test_overview_counts_objects(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/platform/overview").json()
    assert body["counts"] == {"sources": 0, "metrics": 0, "jobs": 0, "enabled_jobs": 0}
    assert body["alerts"]["total"] == 0
    assert body["jobs"] == []


def test_overview_counts_after_seeding(tmp_path):
    client = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "demo",
            "query": "SELECT ts, value FROM t WHERE $timefilter",
            "time_column": "ts",
            "value_column": "value",
        },
    ).json()
    client.post(
        "/api/platform/jobs",
        json={"metric_id": metric["id"], "name": "demo-job", "detector": "iqr"},
    )
    body = client.get("/api/platform/overview").json()
    assert body["counts"]["sources"] == 1
    assert body["counts"]["metrics"] == 1
    assert body["counts"]["jobs"] == 1
    assert body["counts"]["enabled_jobs"] == 1
    # 任务条目要带名字与启用状态
    assert body["jobs"][0]["name"] == "demo-job"
    assert body["jobs"][0]["enabled"] is True
    # 没跑过 → last_run 为空
    assert body["jobs"][0]["last_run"] is None


def test_overview_after_a_real_run(tmp_path):
    """端到端：跑一次任务 → 概览里能看到运行与告警统计。"""
    from tests.web.test_alerts_endpoint import _client_with_data, _run_job

    client, _store = _client_with_data(tmp_path)
    _run_job(client)

    body = client.get("/api/platform/overview").json()
    assert body["runs"]["total"] == 1
    assert body["runs"]["success"] == 1
    assert body["alerts"]["total"] >= 1
    # 按等级分组
    assert body["alerts"]["by_level"][0]["count"] >= 1
    # 按任务分组（带任务名）
    assert body["alerts"]["by_job"][0]["job_name"] == "demo-job"
    # 告警最多的序列
    assert body["alerts"]["top_series"][0]["series_id"]
    # 最近一次运行
    last = body["jobs"][0]["last_run"]
    assert last is not None
    assert last["status"] == "success"
    assert last["n_series"] >= 1
