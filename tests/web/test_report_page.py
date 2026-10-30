"""报告页由前端 SPA 提供；数据仍来自 /api/summary。"""

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_report_route_serves_spa(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/report")
    assert resp.status_code == 200
    assert "根" in resp.text


def test_api_summary_returns_rows():
    client = TestClient(create_app())
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    assert "rows" in resp.json()
