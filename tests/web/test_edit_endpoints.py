"""编辑：数据源与指标的字段更新。

「新增」有表单，「删除」有按钮，唯独中间改不了 ——
配错了只能删掉重建，之前跑出来的运行记录也一起没了。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(platform_data_root=tmp_path))


def _seed(client):
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    ).json()
    return source["id"], metric["id"]


# ---------- 数据源 ----------


def test_patch_source_updates_name(tmp_path):
    client = _client(tmp_path)
    source_id, _ = _seed(client)
    resp = client.patch(f"/api/platform/sources/{source_id}", json={"name": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


def test_patch_source_keeps_untouched_fields(tmp_path):
    """只传 name 时，path 与 kind 不能被清空。"""
    client = _client(tmp_path)
    source_id, _ = _seed(client)
    resp = client.patch(f"/api/platform/sources/{source_id}", json={"name": "renamed"})
    body = resp.json()
    assert body["path"] == "platform/source.db"
    assert body["kind"] == "sqlite"


def test_patch_source_rejects_duplicate_name(tmp_path):
    client = _client(tmp_path)
    first, _ = _seed(client)
    client.post("/api/platform/sources", json={"name": "other", "path": "p.db"})
    resp = client.patch(f"/api/platform/sources/{first}", json={"name": "other"})
    assert resp.status_code == 400
    assert "已存在" in resp.json()["detail"]


def test_patch_unknown_source_is_404(tmp_path):
    client = _client(tmp_path)
    resp = client.patch("/api/platform/sources/999", json={"name": "x"})
    assert resp.status_code == 404


# ---------- 检测任务 ----------


def _seed_job(client):
    source_id, metric_id = _seed(client)
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric_id, "name": "demo-job", "detector": "iqr"},
    ).json()
    return source_id, metric_id, job


def test_patch_job_updates_window_points(tmp_path):
    client = _client(tmp_path)
    _, _, job = _seed_job(client)
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"window_points": 120})
    assert resp.status_code == 200
    assert resp.json()["window_points"] == 120


def test_patch_job_keeps_untouched_fields(tmp_path):
    client = _client(tmp_path)
    _, _, job = _seed_job(client)
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"window_points": 120})
    body = resp.json()
    assert body["name"] == "demo-job"
    assert body["detector"] == "iqr"
    assert body["enabled"] is True


def test_patch_job_rejects_unknown_detector(tmp_path):
    client = _client(tmp_path)
    _, _, job = _seed_job(client)
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"detector": "不存在的算法"})
    assert resp.status_code == 400


def test_patch_job_rejects_invalid_window(tmp_path):
    client = _client(tmp_path)
    _, _, job = _seed_job(client)
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"window_points": 0})
    assert resp.status_code == 400


def test_patch_job_can_switch_metric(tmp_path):
    client = _client(tmp_path)
    _, metric_id, job = _seed_job(client)
    other = client.post(
        "/api/platform/metrics",
        json={
            "source_id": 1,
            "name": "other",
            "query": "SELECT ts, value FROM t WHERE $timefilter",
            "time_column": "ts",
            "value_column": "value",
        },
    ).json()
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"metric_id": other["id"]})
    assert resp.status_code == 200
    assert resp.json()["metric_id"] == other["id"]
    assert metric_id != other["id"]


def test_patch_job_threshold_change_syncs_alert_rules(tmp_path):
    """改了阈值，规则表要跟着重算 —— 否则倍数条件还是旧的，两边对不上。"""
    client = _client(tmp_path)
    _, _, job = _seed_job(client)
    before = job["alert_rules"]
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"alert_threshold": 5.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alert_threshold"] == 5.0
    assert body["alert_rules"] != before


def test_patch_job_other_field_keeps_alert_rules(tmp_path):
    """改别的字段**不能**动规则表 ——
    用户通过「应用建议」调好的规则会被冲掉。"""
    client = _client(tmp_path)
    _, _, job = _seed_job(client)
    resp = client.patch(f"/api/platform/jobs/{job['id']}", json={"window_points": 120})
    assert resp.json()["alert_rules"] == job["alert_rules"]


# ---------- 指标 ----------


def test_patch_metric_updates_query(tmp_path):
    client = _client(tmp_path)
    _, metric_id = _seed(client)
    resp = client.patch(
        f"/api/platform/metrics/{metric_id}",
        json={"query": "SELECT ts, value FROM metrics WHERE $timefilter"},
    )
    assert resp.status_code == 200
    assert "SELECT ts, value" in resp.json()["query"]


def test_patch_metric_keeps_untouched_fields(tmp_path):
    client = _client(tmp_path)
    _, metric_id = _seed(client)
    resp = client.patch(
        f"/api/platform/metrics/{metric_id}",
        json={"query": "SELECT ts, value FROM metrics WHERE $timefilter"},
    )
    body = resp.json()
    assert body["name"] == "demo"
    assert body["time_column"] == "ts"
    assert body["value_column"] == "value"
    assert body["group_column"] == "host"


def test_patch_metric_validates_column_name(tmp_path):
    """非法列名要在保存时就拦下 —— 等任务运行时才失败太晚。"""
    client = _client(tmp_path)
    _, metric_id = _seed(client)
    resp = client.patch(f"/api/platform/metrics/{metric_id}", json={"time_column": "ts; DROP"})
    assert resp.status_code == 400


def test_patch_metric_validates_freq(tmp_path):
    client = _client(tmp_path)
    _, metric_id = _seed(client)
    resp = client.patch(f"/api/platform/metrics/{metric_id}", json={"freq": "5光年"})
    assert resp.status_code == 400


def test_patch_metric_can_clear_group_column(tmp_path):
    """分组列要能清空 —— 「不按组拆」是一个真实需求。

    ⚠️ 用 `exclude_unset` 而不是 `exclude_none`：后者会把显式传的 null
    一起丢掉，group_column 就永远清不掉。
    """
    client = _client(tmp_path)
    _, metric_id = _seed(client)
    resp = client.patch(f"/api/platform/metrics/{metric_id}", json={"group_column": None})
    assert resp.status_code == 200
    assert resp.json()["group_column"] is None


def test_patch_unknown_metric_is_404(tmp_path):
    client = _client(tmp_path)
    resp = client.patch("/api/platform/metrics/999", json={"name": "x"})
    assert resp.status_code == 404
