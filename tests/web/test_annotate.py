import json
from pathlib import Path

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_save_annotation_writes_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    r = client.post(
        "/api/annotate/s1",
        json={"intervals": [{"start": 10, "end": 12, "type": "spike"}]},
    )
    assert r.status_code == 200
    files = list(tmp_path.rglob("s1.jsonl"))
    assert files
    rec = json.loads(files[0].read_text().splitlines()[0])
    assert rec["start"] == 10 and rec["end"] == 12


def test_list_annotations(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.post(
        "/api/annotate/s2",
        json={"intervals": [{"start": 1, "end": 2, "type": "drift"}]},
    )
    r = client.get("/api/annotate/s2")
    assert r.status_code == 200
    assert len(r.json()["intervals"]) == 1
