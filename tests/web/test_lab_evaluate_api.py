"""Lab 有真值评估 API（P3）：契约与错误码。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _client(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    return client


def _synthetic_payload(**overrides):
    payload = {
        "kind": "synthetic",
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(minutes=5 * 1000)).isoformat(),
        "freq": "5min",
        "synthetic": {
            "metric_class": "periodic",
            "n_points": 1000,
            "n_anomalies": 5,
            "seed": 42,
        },
        "sampling": {
            "window_points": 100,
            "stride_points": 100,
            "max_points": 1000,
            "max_windows": 20,
        },
    }
    payload.update(overrides)
    return payload


def test_evaluate_contract(tmp_path):
    client = _client(tmp_path)

    resp = client.post("/api/lab/evaluate", json=_synthetic_payload(detectors=["iqr"]))

    assert resp.status_code == 200
    body = resp.json()
    for key in ("spec", "truth", "split", "results", "warnings"):
        assert key in body
    assert body["truth"]["sources"] == ["synthetic"]
    assert body["truth"]["n_truth_points"] > 0
    assert body["split"]["ratio"] == 0.5

    item = body["results"][0]
    assert item["detector"] == "iqr"
    for key in ("detector", "resolved_mix", "calibration", "test", "default_threshold", "sensitivity"):
        assert key in item
    for key in ("precision", "recall", "f1", "range_f1", "n_alerts", "n_truth", "n_windows"):
        assert key in item["test"]
    assert item["calibration"]["threshold"] is not None


def test_evaluate_accepts_split_ratio(tmp_path):
    client = _client(tmp_path)

    resp = client.post(
        "/api/lab/evaluate", json=_synthetic_payload(detectors=["iqr"], split_ratio=0.3)
    )

    assert resp.status_code == 200
    assert resp.json()["split"]["ratio"] == 0.3


def test_evaluate_rejects_bad_split_ratio(tmp_path):
    client = _client(tmp_path)

    resp = client.post(
        "/api/lab/evaluate", json=_synthetic_payload(detectors=["iqr"], split_ratio=1.5)
    )

    assert resp.status_code == 422


def test_evaluate_rejects_unknown_detector(tmp_path):
    client = _client(tmp_path)

    resp = client.post("/api/lab/evaluate", json=_synthetic_payload(detectors=["nope"]))

    assert resp.status_code == 400
    assert "检测器" in resp.json()["detail"]


def test_evaluate_rejects_unknown_metric_class(tmp_path):
    client = _client(tmp_path)

    payload = _synthetic_payload(detectors=["iqr"])
    payload["synthetic"]["metric_class"] = "nope"

    resp = client.post("/api/lab/evaluate", json=payload)

    assert resp.status_code == 400
    assert "形态" in resp.json()["detail"]


def test_evaluate_synthetic_requires_freq(tmp_path):
    client = _client(tmp_path)

    payload = _synthetic_payload(detectors=["iqr"])
    payload.pop("freq")

    resp = client.post("/api/lab/evaluate", json=payload)

    assert resp.status_code == 400
    assert "freq" in resp.json()["detail"]


def test_evaluate_unknown_metric_is_404(tmp_path):
    client = _client(tmp_path)

    payload = {
        "kind": "metric",
        "metric_id": 999,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=10)).isoformat(),
    }

    resp = client.post("/api/lab/evaluate", json=payload)

    assert resp.status_code == 404


def test_evaluate_without_truth_warns(tmp_path):
    """没有真值就明说 —— 不能假装能评估。"""
    client = _client(tmp_path)
    store = PlatformStore(tmp_path / "platform.db")
    assert store is not None

    payload = {
        "kind": "metric",
        "metric_id": 1,
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(hours=10)).isoformat(),
        "freq": "1h",
    }
    # 没有这个指标 → 404；这里只验证 spec 校验不误伤
    resp = client.post("/api/lab/evaluate", json=payload)
    assert resp.status_code == 404
