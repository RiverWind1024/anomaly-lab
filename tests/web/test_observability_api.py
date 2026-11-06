"""服务监控 API：`GET /api/platform/observability`。"""

from fastapi.testclient import TestClient

from anomaly_lab.observability import reset_observability
from anomaly_lab.web.app import create_app


def _client(tmp_path) -> TestClient:
    # ⚠️ 先清掉单例，否则会拿到上一个测试的采样器（data_root 指向别的目录）。
    reset_observability()
    return TestClient(create_app(platform_data_root=tmp_path))


def test_监控端点返回状态与时序(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/platform/observability").json()

    assert body["service"]["service_name"] == "anomaly-lab"
    assert body["service"]["uptime_seconds"] >= 0
    assert body["interval_seconds"] == 60
    # 启动时采样线程已经走过一次，所以至少有当前值
    assert body["current"]["cpu_percent"] is not None
    assert isinstance(body["timeline"], list)


def test_请求会被中间件计数并归到路由模板(tmp_path):
    with _client(tmp_path) as client:
        client.get("/api/platform/observability")
        body = client.get("/api/platform/observability").json()

    routes = {(row["method"], row["route"]): row for row in body["http"]["routes"]}
    # ⚠️ 标签是模板，不是真实 URL —— 否则每个 job_id 都会新开一条时间序列。
    assert ("GET", "/api/platform/observability") in routes
    assert routes[("GET", "/api/platform/observability")]["count"] >= 1


def test_未匹配的路径归到兜底路由(tmp_path):
    """SPA 的 `/{full_path:path}` 会接住所有未知路径。

    ⚠️ 这里断言的是「不会把原始 URL 当标签」—— 只要标签是固定模板，
       基数就不会随用户输入增长。`<unmatched>` 只在连 SPA 都没挂时出现。
    """
    with _client(tmp_path) as client:
        client.get("/api/does-not-exist")
        body = client.get("/api/platform/observability").json()

    paths = [row["route"] for row in body["http"]["routes"]]
    assert "/api/does-not-exist" not in paths
    assert all("{" in path or path.startswith("/api/") for path in paths)


def test_没有调度器时明确报告未运行(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/platform/observability").json()

    assert body["scheduler"]["alive"] is False
    assert body["scheduler"]["last_tick_at"] is None


def test_OTel_默认不导出但状态可见(tmp_path):
    with _client(tmp_path) as client:
        body = client.get("/api/platform/observability").json()

    assert body["otel"]["enabled"] is False
    assert "ANOMALY_OTEL_ENDPOINT" in body["otel"]["hint"]
