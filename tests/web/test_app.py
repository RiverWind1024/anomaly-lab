"""根路径由前端 SPA 提供（旧 Jinja 页面已退役）。"""

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_index_serves_spa(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "根" in resp.text


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/api/health").json() == {"status": "ok"}
