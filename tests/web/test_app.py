from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_index_page_loads():
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "anomaly-lab" in r.text


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/api/health").json() == {"status": "ok"}
