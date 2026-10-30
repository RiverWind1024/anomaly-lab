import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _client(tmp_path, frontend_dist=None):
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = utcnow() - timedelta(minutes=5 * 61)
    for i in range(61):
        ts = to_iso(start + timedelta(minutes=5 * i))
        conn.execute(
            "INSERT INTO metrics VALUES (?, ?, ?)",
            (ts, "a", float(i % 10) + (40.0 if i == 30 else 0.0)),
        )
    conn.commit()
    conn.close()
    store = PlatformStore(tmp_path / "platform.db")
    app = create_app(
        platform_store=store,
        platform_data_root=tmp_path,
        frontend_dist=frontend_dist,
    )
    return TestClient(app), store


def test_create_source_metric_job_run_and_preview(tmp_path):
    client, _store = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    assert source.status_code == 200
    source_id = source.json()["id"]

    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source_id,
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
            "freq": "5min",
        },
    )
    assert metric.status_code == 200

    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "seasonal",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
            "window_points": 60,
            "interval_seconds": 300,
        },
    )
    assert job.status_code == 200
    job_id = job.json()["id"]

    run = client.post(f"/api/platform/jobs/{job_id}/run")
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    preview = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}")
    assert preview.status_code == 200
    body = preview.json()
    assert body["series_id"] == "demo:a"
    # 窗口是 [now - 60 点, now)，边界点是否命中取决于秒级对齐
    assert 59 <= len(body["values"]) <= 60
    assert len(body["baseline"]) == len(body["values"])
    assert set(body["severity"]) <= {0, 1, 2}
    assert body["alert_threshold"] == 1.0


def test_platform_page_and_catalog(tmp_path, make_dist):
    client, _ = _client(tmp_path, frontend_dist=make_dist())
    # 旧 Jinja 页面已退役，/platform 由 SPA 提供（深链接不 404）
    page = client.get("/platform")
    assert page.status_code == 200
    assert "根" in page.text
    catalog = client.get("/api/platform/catalog").json()
    assert "seasonal" in [item["name"] for item in catalog["detectors"]]
    assert catalog["sources"] == []


def test_invalid_query_returns_400(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    response = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "bad",
            "query": "DELETE FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "value_column": "value",
        },
    )
    assert response.status_code == 400
    assert "SELECT" in response.json()["detail"]


def test_job_defaults_thresholds_from_detector(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric.json()["id"], "name": "job", "detector": "seasonal"},
    )
    assert job.status_code == 200
    payload = job.json()
    assert payload["alert_threshold"] == 2.5
    assert payload["critical_threshold"] == 3.75


def test_job_defaults_to_auto_detector(tmp_path):
    """默认算法是「自动推荐」；预览会给出推断出的形态与实际使用的检测器。"""
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric.json()["id"], "name": "auto-job"},
    )
    assert job.status_code == 200
    assert job.json()["detector"] == "auto"

    job_id = job.json()["id"]
    run_id = client.post(f"/api/platform/jobs/{job_id}/run").json()["run_id"]
    preview = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}").json()
    assert preview["requested_detector"] == "auto"
    # 实际用的检测器必须是平台支持的算法之一
    assert preview["detector"] in {
        "iqr",
        "mad",
        "zscore",
        "seasonal",
        "stl_residual",
        "deseasonalized_iqr",
    }
    assert preview["detector_rationale"]


def test_compare_endpoint_returns_multiple_detectors(tmp_path):
    """多算法对比：同一条序列用各算法各跑一遍，并给出 auto 推荐。"""
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "cmp-job",
            "detector": "auto",
            "alert_rules": [{"multiplier": 1.0, "level": "P2"}],
        },
    )
    job_id = job.json()["id"]
    response = client.get(
        f"/api/platform/jobs/{job_id}/compare?detectors=iqr,mad,seasonal"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["series_id"] == "demo:a"
    names = [item["name"] for item in payload["detectors"]]
    assert names == ["iqr", "mad", "seasonal"]
    for item in payload["detectors"]:
        assert len(item["scores"]) == len(payload["values"])
        assert len(item["severity"]) == len(payload["values"])
        assert item["default_threshold"] > 0
    # auto 推荐要一并给出，方便对照
    assert payload["auto_detector"] in names or payload["auto_detector"]
    assert payload["recommendation"]["detectors"]


def test_compare_endpoint_rejects_unknown_series(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric.json()["id"], "name": "cmp-job", "detector": "auto"},
    )
    response = client.get(
        f"/api/platform/jobs/{job.json()['id']}/compare?series_id=not-exist"
    )
    assert response.status_code == 404


def test_feedback_loop_suggests_and_applies_multiplier(tmp_path):
    """闭环：提交反馈 → 拿到倍数建议 → 应用建议改写规则表。"""
    client, _store = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "iqr",
            "alert_rules": [{"multiplier": 1.0, "level": "P1"}],
        },
    )
    job_id = job.json()["id"]
    assert job.json()["alert_threshold"] == 1.0
    client.post(f"/api/platform/jobs/{job_id}/run")

    # 没有反馈时不给建议
    empty = client.get(f"/api/platform/jobs/{job_id}/feedback/suggestion").json()
    assert empty["suggested_multiplier"] == empty["current_multiplier"] == 1.0
    assert empty["best"] is None

    # 标一段误报：覆盖序列尾部（那里有个 40 的尖峰）
    start = utcnow() - timedelta(minutes=30)
    feedback = client.post(
        "/api/platform/feedback",
        json={
            "job_id": job_id,
            "series_id": "demo:a",
            "start_ts": to_iso(start),
            "end_ts": to_iso(utcnow()),
            "kind": "false_alarm",
            "note": "业务上正常",
        },
    )
    assert feedback.status_code == 200

    listed = client.get(f"/api/platform/jobs/{job_id}/feedback").json()
    assert len(listed["feedback"]) == 1
    assert listed["feedback"][0]["kind"] == "false_alarm"

    suggestion = client.get(f"/api/platform/jobs/{job_id}/feedback/suggestion").json()
    assert suggestion["suggested_multiplier"] >= suggestion["current_multiplier"]
    assert suggestion["best"] is not None
    assert suggestion["reason"]
    # 建议也要带上参与比较的算法集合，方便前端展示
    assert suggestion["candidates"]

    applied = client.post(
        f"/api/platform/jobs/{job_id}/apply-suggestion",
        json={
            "multiplier": suggestion["suggested_multiplier"],
            "detector": suggestion["suggested_detector"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["alert_threshold"] == pytest.approx(
        suggestion["suggested_multiplier"], rel=1e-3
    )
    assert applied.json()["detector"] == suggestion["suggested_detector"]


def test_suggestion_keeps_auto_when_the_algorithm_is_fine(tmp_path):
    """auto 模式下，算法没问题就别动它——只调倍数。

    auto 是「每条序列各挑一个算法」的混合表现，不是单个算法；
    所以它也要参与评估，但建议里不能写成「从 auto 换成 X」。
    """
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "auto-job",
            "detector": "auto",
            "alert_rules": [{"multiplier": 1.0, "level": "P2"}],
        },
    )
    job_id = job.json()["id"]
    client.post(
        "/api/platform/feedback",
        json={
            "job_id": job_id,
            "series_id": "demo:a",
            "start_ts": to_iso(utcnow() - timedelta(minutes=30)),
            "end_ts": to_iso(utcnow()),
            "kind": "false_alarm",
        },
    )
    suggestion = client.get(f"/api/platform/jobs/{job_id}/feedback/suggestion").json()
    # auto 必须参与比较
    assert "auto" in suggestion["evaluated_detectors"]
    assert suggestion["current_detector"] == "auto"
    # 没有充分理由换算法时保持 auto
    assert suggestion["detector_changed"] is False
    assert suggestion["suggested_detector"] == "auto"
    assert suggestion["suggested_multiplier"] >= suggestion["current_multiplier"]


def test_patch_job_detector(tmp_path):
    """多算法对比后可以把任务固定成用户选定的算法。"""
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric.json()["id"], "name": "job", "detector": "auto"},
    )
    job_id = job.json()["id"]
    updated = client.patch(f"/api/platform/jobs/{job_id}", json={"detector": "seasonal"})
    assert updated.status_code == 200
    assert updated.json()["detector"] == "seasonal"

    bad = client.patch(f"/api/platform/jobs/{job_id}", json={"detector": "nonexistent"})
    assert bad.status_code == 400


def test_feedback_rejects_invalid_range(tmp_path):
    client, _ = _client(tmp_path)
    response = client.post(
        "/api/platform/feedback",
        json={
            "job_id": 1,
            "series_id": "demo:a",
            "start_ts": to_iso(utcnow()),
            "end_ts": to_iso(utcnow() - timedelta(hours=1)),
            "kind": "missed",
        },
    )
    assert response.status_code == 400
    assert "结束时间" in response.json()["detail"]


def test_runs_endpoint_lists_history(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "seasonal",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
        },
    )
    job_id = job.json()["id"]
    client.post(f"/api/platform/jobs/{job_id}/run")
    runs = client.get(f"/api/platform/jobs/{job_id}/runs").json()["runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "success"


def test_preview_downsamples_long_series(tmp_path, monkeypatch):
    """点数过多时预览要抽样，避免一次返回上兆的 JSON。"""
    from anomaly_lab.web import platform_routes

    monkeypatch.setattr(platform_routes, "MAX_PREVIEW_POINTS", 20)
    client, _store = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "iqr",
            "alert_threshold": 1.0,
            "critical_threshold": 2.0,
            "window_points": 60,
            "interval_seconds": 300,
        },
    )
    job_id = job.json()["id"]
    run_id = client.post(f"/api/platform/jobs/{job_id}/run").json()["run_id"]
    body = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}").json()
    assert body["sampled"] is True
    assert len(body["values"]) <= 20
    assert body["original_n"] > 20
    assert len(body["values"]) == len(body["scores"]) == len(body["severity"])


def test_job_with_custom_alert_rules(tmp_path):
    """任务可以配「倍数 → 等级」规则表，判定以异常分数为准。"""
    client, _store = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "job",
            "detector": "seasonal",
            "alert_rules": [{"multiplier": 1.0, "level": "P2"}, {"multiplier": 3.0, "level": "P1"}],
        },
    )
    assert job.status_code == 200
    payload = job.json()
    assert payload["alert_rules"] == [
        {"multiplier": 1.0, "level": "P2"},
        {"multiplier": 3.0, "level": "P1"},
    ]
    assert payload["alert_threshold"] == 1.0
    assert payload["critical_threshold"] == 3.0

    job_id = payload["id"]
    run_id = client.post(f"/api/platform/jobs/{job_id}/run").json()["run_id"]
    preview = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}").json()
    assert preview["levels"] == ["正常", "P2", "P1"]
    assert preview["alert_rules"] == payload["alert_rules"]
    assert set(preview["severity"]) <= {0, 1, 2}


def test_job_rejects_invalid_alert_rules(tmp_path):
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    response = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "bad-job",
            "detector": "seasonal",
            "alert_rules": [{"multiplier": 0, "level": "P1"}],
        },
    )
    assert response.status_code == 400
    assert "multiplier" in response.json()["detail"]


def test_job_with_absolute_alert_rule(tmp_path):
    """绝对值条件与倍数条件并行存在，规则原样往返。"""
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    rules = [
        {"multiplier": 1.0, "level": "P2"},
        {"op": ">", "value": 50, "level": "P1"},
    ]
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "absolute-job",
            "detector": "seasonal",
            "alert_rules": rules,
        },
    )
    assert job.status_code == 200
    payload = job.json()
    assert payload["alert_rules"] == rules
    # 阈值由规则推导：最低档/最高档的倍数（这里只有一条倍数规则）
    assert payload["alert_threshold"] == 1.0
    assert payload["critical_threshold"] == 1.0

    job_id = payload["id"]
    run_id = client.post(f"/api/platform/jobs/{job_id}/run").json()["run_id"]
    preview = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}").json()
    assert preview["levels"] == ["正常", "P2", "P1"]
    assert preview["alert_rules"] == rules


def test_job_rejects_absolute_only_alert_rules(tmp_path):
    """纯绝对值规则无法定出上下界宽度，配置期就要拦下来。"""
    client, _ = _client(tmp_path)
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    )
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source.json()["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    )
    response = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric.json()["id"],
            "name": "absolute-only-job",
            "detector": "seasonal",
            "alert_rules": [{"op": ">", "value": 50, "level": "P1"}],
        },
    )
    # ⚠️ 2026-10-30 起不再拒绝纯绝对值规则：
    #    没有倍数条件就没有「上下界宽度」，此时用**检测器自己的惯用阈值**
    #    （seasonal 默认 2.5）画带；分级仍由规则表决定，绝对值条件照常生效。
    #    动机：Chronos 的分数是 0~1 的相对越界程度，`>=0.5, P1` 才是自然写法。
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["alert_threshold"] == 2.5
    assert body["alert_rules"] == [{"op": ">", "value": 50.0, "level": "P1"}]
