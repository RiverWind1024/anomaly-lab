"""删除：级联清理与 run 目录文件清理。"""

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
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric["id"], "name": "demo-job", "detector": "iqr"},
    ).json()
    return source["id"], metric["id"], job["id"]


def test_delete_source_cascades_to_metrics_and_jobs(tmp_path):
    client = _client(tmp_path)
    source_id, _metric_id, _job_id = _seed(client)
    response = client.delete(f"/api/platform/sources/{source_id}")
    assert response.status_code == 200
    catalog = client.get("/api/platform/catalog").json()
    assert catalog["sources"] == []
    assert catalog["metrics"] == []
    assert catalog["jobs"] == []


def test_delete_metric_cascades_to_jobs(tmp_path):
    client = _client(tmp_path)
    _, metric_id, _job_id = _seed(client)
    response = client.delete(f"/api/platform/metrics/{metric_id}")
    assert response.status_code == 200
    catalog = client.get("/api/platform/catalog").json()
    assert catalog["metrics"] == []
    assert catalog["jobs"] == []


def test_delete_job_removes_only_that_job(tmp_path):
    client = _client(tmp_path)
    _, _, job_id = _seed(client)
    response = client.delete(f"/api/platform/jobs/{job_id}")
    assert response.status_code == 200
    catalog = client.get("/api/platform/catalog").json()
    assert catalog["jobs"] == []
    assert len(catalog["metrics"]) == 1


def test_delete_missing_object_returns_404(tmp_path):
    client = _client(tmp_path)
    for path in (
        "/api/platform/sources/999",
        "/api/platform/metrics/999",
        "/api/platform/jobs/999",
    ):
        response = client.delete(path)
        assert response.status_code == 404, path


def test_delete_response_reports_cascade_counts(tmp_path):
    client = _client(tmp_path)
    source_id, _, _job_id = _seed(client)
    body = client.delete(f"/api/platform/sources/{source_id}").json()
    assert body["deleted"]["sources"] == 1
    assert body["deleted"]["metrics"] == 1
    assert body["deleted"]["jobs"] == 1


def test_delete_response_does_not_leak_internal_run_ids(tmp_path):
    """`run_ids` 是内部用的（路由层据此删目录），不能出现在响应里。"""
    client = _client(tmp_path)
    source_id, _, _job_id = _seed(client)
    body = client.delete(f"/api/platform/sources/{source_id}").json()
    assert "run_ids" not in body["deleted"]
