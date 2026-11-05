import json
from pathlib import Path

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_save_annotation_writes_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    r = client.post(
        "/api/annotate/s1",
        json={
            "intervals": [
                {
                    "start": "2026-01-01T10:00:00",
                    "end": "2026-01-01T12:00:00",
                    "type": "spike",
                }
            ]
        },
    )
    assert r.status_code == 200
    files = list(tmp_path.rglob("s1.jsonl"))
    assert files
    rec = json.loads(files[0].read_text().splitlines()[0])
    # ⚠️ 存的是**时间戳** —— 序列滚动后下标会指向别的时刻。
    assert rec["start"] == "2026-01-01T10:00:00"
    assert rec["end"] == "2026-01-01T12:00:00"
    assert rec["type"] == "spike"


def test_list_annotations(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.post(
        "/api/annotate/s2",
        json={
            "intervals": [
                {
                    "start": "2026-01-01T01:00:00",
                    "end": "2026-01-01T02:00:00",
                    "type": "drift",
                }
            ]
        },
    )
    r = client.get("/api/annotate/s2")
    assert r.status_code == 200
    assert len(r.json()["intervals"]) == 1


def test_annotation_rejects_numeric_bounds(tmp_path: Path, monkeypatch):
    """⚠️ 下标不是合法边界 —— 静默接受会让标注错位却看不出来。"""
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    r = client.post(
        "/api/annotate/s3",
        json={"intervals": [{"start": 1, "end": 2, "type": "spike"}]},
    )
    assert r.status_code == 422


def test_annotation_keeps_sampling_rate(tmp_path: Path, monkeypatch):
    """⚠️ **采样率跟着标注一起存** —— 反算总体量时按它做权重。

    采样率后来变了，老标注仍按它当初的权重算 ——
    它是从那个样本框里抽出来的，代表的框没变。
    """
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    r = client.post(
        "/api/annotate/s4?run_id=7",
        json={
            "intervals": [
                {
                    "start": "2026-01-01T10:00:00",
                    "end": "2026-01-01T12:00:00",
                    "type": "spike",
                    "rate": 0.2,
                    "layer_size": 40,
                }
            ]
        },
    )
    assert r.status_code == 200
    files = list(tmp_path.rglob("s4.jsonl"))
    assert files
    rec = json.loads(files[0].read_text().splitlines()[0])
    assert rec["run_id"] == 7
    assert rec["rate"] == 0.2
    assert rec["layer_size"] == 40
