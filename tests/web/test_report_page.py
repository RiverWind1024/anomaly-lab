from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_report_page_loads():
    client = TestClient(create_app())
    assert client.get("/report").status_code == 200


def test_api_summary_returns_rows():
    client = TestClient(create_app())
    r = client.get("/api/summary")
    assert r.status_code == 200
    assert "rows" in r.json()
