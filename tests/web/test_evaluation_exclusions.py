"""评估记录可以排除与恢复。

评估报告的每一行 = 一次检测记录（某条序列上的某个算法的结果）。
用户想删掉其中一条 —— 但 report.json 是 `make evaluate` 的产物，
重跑会整个覆盖掉，所以排除项要单独存盘。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from anomaly_lab.config import CONFIG
from anomaly_lab.web.app import create_app


def _write_report(reports_dir: Path) -> None:
    latest = reports_dir / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "2026-10-30T00:00:00+00:00",
        "title": "回测",
        "summary": {"overall": {"n_series": 2, "f1": 0.5}},
        "rows": [
            {
                "series_id": "s-1",
                "metric_class": "periodic",
                "detector": "iqr",
                "score_type": "zscore",
                "threshold": 2.5,
                "precision": 1.0,
                "recall": 0.5,
                "f1": 0.667,
                "range_f1": 0.5,
                "n_truth": 2,
                "n_pred": 1,
                "elapsed_ms": 0.1,
                "start_ts": "2026-01-01T00:00:00",
                "end_ts": "2026-01-02T00:00:00",
                "source": "synthetic",
            },
            {
                "series_id": "s-2",
                "metric_class": "trending",
                "detector": "mad",
                "score_type": "zscore",
                "threshold": 3.0,
                "precision": 0.8,
                "recall": 0.4,
                "f1": 0.53,
                "range_f1": 0.4,
                "n_truth": 5,
                "n_pred": 3,
                "elapsed_ms": 0.2,
                "start_ts": "2026-01-03T00:00:00",
                "end_ts": "2026-01-04T00:00:00",
                "source": "synthetic",
            },
        ],
    }
    (latest / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    reports_dir = tmp_path / "reports"
    _write_report(reports_dir)
    monkeypatch.setattr(CONFIG, "reports_dir", reports_dir)
    return TestClient(create_app(platform_data_root=tmp_path / "data"))


def test_summary_lists_all_rows_initially(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    body = client.get("/api/summary").json()
    assert len(body["rows"]) == 2
    assert body["excluded"] == []


def test_excluded_row_disappears_from_summary(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/api/evaluation/exclusions", json={"series_id": "s-1", "detector": "iqr"}
    )
    assert resp.status_code == 200

    body = client.get("/api/summary").json()
    assert [row["series_id"] for row in body["rows"]] == ["s-2"]
    # 清单要一起给前端 —— 用户得知道自己排除了什么
    assert len(body["excluded"]) == 1
    assert body["excluded"][0]["series_id"] == "s-1"


def test_exclusion_only_hides_that_detector(tmp_path, monkeypatch):
    """同一序列的不同算法是不同记录 —— 排 iqr 不该把 mad 也排掉。"""
    client = _client(tmp_path, monkeypatch)
    client.post("/api/evaluation/exclusions", json={"series_id": "s-1", "detector": "iqr"})
    body = client.get("/api/summary").json()
    assert [row["series_id"] for row in body["rows"]] == ["s-2"]


def test_restored_row_comes_back(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/evaluation/exclusions", json={"series_id": "s-1", "detector": "iqr"})
    resp = client.request(
        "DELETE", "/api/evaluation/exclusions/s-1/iqr"
    )
    assert resp.status_code == 200
    body = client.get("/api/summary").json()
    assert len(body["rows"]) == 2
    assert body["excluded"] == []


def test_restoring_unknown_exclusion_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.request("DELETE", "/api/evaluation/exclusions/s-9/iqr")
    assert resp.status_code == 404


def test_exclusions_survive_a_new_process(tmp_path, monkeypatch):
    """排除清单要落盘 —— 重启服务后仍然生效。"""
    client = _client(tmp_path, monkeypatch)
    client.post("/api/evaluation/exclusions", json={"series_id": "s-1", "detector": "iqr"})

    client2 = _client(tmp_path, monkeypatch)
    body = client2.get("/api/summary").json()
    assert len(body["rows"]) == 1
