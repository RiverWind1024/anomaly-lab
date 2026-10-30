"""API 契约守卫：前端 types.ts 是手写的，后端字段变了这里要红。

决策 D6 选了手写类型（可读、后端微调时不会红一片），代价就是要防漂移。
这里只断言**关键字段存在**，不锁死值的类型细节 —— 太严会变成改一次文案就红。

⚠️ 各断言都有「数据为空就跳过」的兜底：
CI 上没有 data/platform.db 与 reports/latest，空表是正常状态。
"""

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_catalog_contract():
    client = TestClient(create_app())
    body = client.get("/api/platform/catalog").json()
    for key in ("sources", "metrics", "jobs", "detectors"):
        assert key in body
    # ⚠️ detectors **没有 id** —— 它是按 name 索引的字典，不是表记录
    assert body["detectors"], "检测器清单不该是空的"
    for key in ("name", "default_threshold", "score_type", "label"):
        assert key in body["detectors"][0]
    if body["sources"]:
        for key in ("id", "name", "kind", "path", "created_at"):
            assert key in body["sources"][0]
    if body["jobs"]:
        for key in (
            "id",
            "metric_id",
            "name",
            "detector",
            "window_points",
            "interval_seconds",
            "enabled",
            "alert_rules",
        ):
            assert key in body["jobs"][0]


def test_series_contract():
    client = TestClient(create_app())
    body = client.get("/api/series").json()
    if not body:
        return  # 没有数据集时跳过
    for key in ("series_id", "metric_class", "n", "n_anomalies"):
        assert key in body[0]


def test_summary_contract():
    client = TestClient(create_app())
    body = client.get("/api/summary").json()
    assert "rows" in body
    assert "summary" in body
    if body["rows"]:
        for key in (
            "series_id",
            "metric_class",
            "detector",
            "score_type",
            "threshold",
            "precision",
            "recall",
            "f1",
            "range_f1",
            "n_truth",
            "n_pred",
            "elapsed_ms",
        ):
            assert key in body["rows"][0]


def test_series_values_contract():
    client = TestClient(create_app())
    series = client.get("/api/series").json()
    if not series:
        return
    body = client.get(f"/api/series/{series[0]['series_id']}/values").json()
    for key in ("series_id", "timestamps", "values", "labels"):
        assert key in body


def test_annotate_contract():
    client = TestClient(create_app())
    body = client.get("/api/annotate/任意序列").json()
    assert "series_id" in body
    assert "intervals" in body
    if body["intervals"]:
        for key in ("series_id", "start", "end", "type", "created_at"):
            assert key in body["intervals"][0]
