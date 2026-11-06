"""服务监控 API：从 SQLite 读指标并组装页面数据。"""

from fastapi.testclient import TestClient

from anomaly_lab.observability import get_observability, reset_observability
from anomaly_lab.web.app import create_app


def _client(tmp_path) -> TestClient:
    # ⚠️ 先清掉单例，否则会拿到上一个测试的数据库路径。
    reset_observability()
    return TestClient(create_app(platform_data_root=tmp_path))


def test_监控端点返回状态与结构(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/platform/observability").json()

    assert body["service"]["service_name"] == "anomaly-lab"
    assert body["service"]["uptime_seconds"] >= 0
    assert body["service"]["retention_days"] == 30
    assert body["interval_seconds"] >= 1
    assert isinstance(body["timeline"], list)
    assert body["detectors"] == []
    assert body["scheduler"]["alive"] is False


def test_请求会被中间件计数并归到路由模板(tmp_path):
    with _client(tmp_path) as client:
        client.get("/api/platform/observability")
        # 中间件在请求结束时记账，所以要 flush 后再查
        get_observability().force_flush()
        body = client.get("/api/platform/observability").json()

    routes = {(row["method"], row["route"]): row for row in body["http"]["routes"]}
    assert ("GET", "/api/platform/observability") in routes
    assert routes[("GET", "/api/platform/observability")]["count"] >= 1


def test_未匹配的路径不会被当成标签(tmp_path):
    with _client(tmp_path) as client:
        client.get("/api/does-not-exist")
        get_observability().force_flush()
        body = client.get("/api/platform/observability").json()

    paths = [row["route"] for row in body["http"]["routes"]]
    assert "/api/does-not-exist" not in paths


def test_时间线按分钟聚合任务与告警(tmp_path):
    with _client(tmp_path) as client:
        obs = get_observability()
        obs.inc("http.requests", 5, method="GET", route="/x", status="200")
        obs.inc("http.errors", 1, method="GET", route="/x", status="500")
        obs.inc("job.runs", 2, job="demo", status="failed")
        obs.inc("alerts.fired", 3, level="P1")
        obs.inc("alerts.fired", 1, level="P0")
        obs.observe_ms("http.request_ms", 10.0, method="GET", route="/x")
        obs.force_flush()

        body = client.get("/api/platform/observability").json()

    point = body["timeline"][-1]
    assert point["requests"] == 5
    assert point["errors"] == 1
    assert point["failed_runs"] == 2
    assert point["alerts"] == 4
    assert point["p0"] == 1
    assert point["p95_ms"] is not None


def test_算法与任务统计来自全维度累计(tmp_path):
    with _client(tmp_path) as client:
        obs = get_observability()
        obs.inc("detector.calls", 3, detector="iqr", status="ok")
        obs.inc("detector.calls", 1, detector="iqr", status="fallback")
        obs.observe_ms("detector.duration_ms", 2.0, detector="iqr")
        obs.inc("job.runs", 1, job="demo", status="success")
        obs.observe_ms("job.stage_ms", 30.0, stage="load")
        obs.force_flush()

        body = client.get("/api/platform/observability").json()

    detector = next(row for row in body["detectors"] if row["detector"] == "iqr")
    assert detector["calls"] == 4
    assert detector["fallbacks"] == 1
    assert detector["avg_ms"] == 2.0

    job = next(row for row in body["jobs"] if row["job"] == "demo")
    assert job["runs"] == 1

    stage = next(row for row in body["stages"] if row["stage"] == "load")
    assert stage["count"] >= 1


def test_OTel_默认不导出但状态可见(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/platform/observability").json()

    assert body["otel"]["enabled"] is False
    assert "ANOMALY_OTEL_ENDPOINT" in body["otel"]["hint"]
