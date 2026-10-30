"""业务态（不是错误）的 404 必须带 `X-Anomaly-Biz-State` 响应头。

前端靠这个头区分「空 / 数据不足」与「真错误」——
没有头的 404 一律当错误处理（红框），会把业务态显示成故障。
"""

from fastapi.testclient import TestClient

import anomaly_lab.web.app as webapp
from anomaly_lab.web.app import create_app


def test_preview_no_run_has_biz_state_header(store_with_job):
    """任务存在但没有运行记录 → 业务态 `no_run`。"""
    job_id = store_with_job.list_jobs()[0].id
    client = TestClient(create_app(platform_store=store_with_job))
    resp = client.get(f"/api/platform/jobs/{job_id}/preview")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") == "no_run"


def test_preview_unknown_job_is_a_real_error_without_biz_state(store_with_job):
    """任务不存在 → 真错误，不该带业务态头。"""
    client = TestClient(create_app(platform_store=store_with_job))
    resp = client.get("/api/platform/jobs/999999/preview")
    assert resp.status_code == 404
    # 「任务不存在: 999999」是参数错误，不该带业务态头
    assert resp.headers.get("X-Anomaly-Biz-State") is None


def test_badcases_unknown_series_is_a_real_error_without_biz_state():
    """序列不在数据集里 → 真错误，不该带业务态头。"""
    client = TestClient(create_app())
    resp = client.get("/api/badcases?series_id=根本不存在的序列")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") is None


def test_badcases_existing_series_without_results_has_biz_state_header(
    monkeypatch, tmp_path
):
    """序列存在但没有检测结果 → 业务态 `no_result`，不是错误。

    用 monkeypatch 把「序列表」与「检测结果目录」都指到可控的地方，
    这样这个分支**不依赖本机缓存状态**（实测数据集 120 条序列全都有
    iqr 检测结果，直接用真实缓存测不到这个分支）。
    """
    monkeypatch.setattr(webapp, "_series_map", lambda: {"demo-series": object()})
    monkeypatch.setattr(webapp, "_detections_root", lambda: tmp_path)
    client = TestClient(create_app())
    resp = client.get("/api/badcases?series_id=demo-series")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") == "no_result"


def test_series_values_unknown_series_is_a_real_error():
    """「序列不存在」是真错误，不该带业务态头。"""
    client = TestClient(create_app())
    resp = client.get("/api/series/根本不存在的序列/values")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") is None


def test_healthy_endpoints_have_no_biz_state_header():
    """正常响应不该带业务态头。"""
    client = TestClient(create_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Anomaly-Biz-State") is None
