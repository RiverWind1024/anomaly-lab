"""数据源 API：config 透传与**脱敏**。

⚠️ 这一层之前 0 覆盖 —— 脱敏是「前端拿不到明文」的最后一道防线，
   必须在 API 边界上守住：响应体里不能出现任何凭据明文。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app


def _client_and_store(tmp_path):
    """测试客户端 + 同一个 store —— 后者用来断言**存储层**的真值。"""
    store = PlatformStore(tmp_path / "platform.db")
    client = TestClient(create_app(platform_store=store, platform_data_root=tmp_path))
    return client, store


def _http_payload(**overrides):
    payload = {
        "name": "remote",
        "kind": "http",
        "config": {
            "url": "https://ch.internal:8123/?query={sql}&token=SECRET-TOKEN",
            "headers": {"Authorization": "Bearer SECRET-TOKEN"},
        },
    }
    payload.update(overrides)
    return payload


def test_create_http_source_redacts_secrets(tmp_path):
    client, _ = _client_and_store(tmp_path)
    resp = client.post("/api/platform/sources", json=_http_payload())
    assert resp.status_code == 200
    assert "SECRET-TOKEN" not in resp.text
    body = resp.json()
    assert body["config"]["headers"]["Authorization"] == "Bearer ••••"
    # ⚠️ 模板不能被重新编码 —— `{sql}` 变成 `%7Bsql%7D` 就废了
    assert "{sql}" in body["config"]["url"]
    assert "SECRET-TOKEN" not in body["config"]["url"]


def test_create_http_source_without_url_is_400(tmp_path):
    client, _ = _client_and_store(tmp_path)
    resp = client.post(
        "/api/platform/sources", json=_http_payload(config={"format": "csv"})
    )
    assert resp.status_code == 400
    assert "url" in resp.json()["detail"]


def test_create_unknown_kind_is_400(tmp_path):
    client, _ = _client_and_store(tmp_path)
    resp = client.post(
        "/api/platform/sources", json={"name": "x", "kind": "kafka", "path": "a.db"}
    )
    assert resp.status_code == 400
    assert "不支持的数据源类型" in resp.json()["detail"]


def test_create_sqlite_source_without_path_is_400(tmp_path):
    client, _ = _client_and_store(tmp_path)
    resp = client.post("/api/platform/sources", json={"name": "x", "kind": "sqlite"})
    assert resp.status_code == 400


def test_patch_source_keeps_secret_when_only_name_changes(tmp_path):
    """⚠️ 只改名字不能把密钥冲掉。"""
    client, store = _client_and_store(tmp_path)
    source_id = client.post("/api/platform/sources", json=_http_payload()).json()["id"]
    resp = client.patch(f"/api/platform/sources/{source_id}", json={"name": "renamed"})
    assert resp.status_code == 200
    raw = store.get_source_raw(source_id).config
    assert raw["headers"]["Authorization"] == "Bearer SECRET-TOKEN"
    assert "SECRET-TOKEN" in raw["url"]


def test_patch_source_with_redacted_value_keeps_secret(tmp_path):
    """前端把脱敏值原样传回来 → 存储层的真值必须保住。"""
    client, store = _client_and_store(tmp_path)
    created = client.post("/api/platform/sources", json=_http_payload()).json()
    resp = client.patch(
        f"/api/platform/sources/{created['id']}", json={"config": created["config"]}
    )
    assert resp.status_code == 200
    raw = store.get_source_raw(created["id"]).config
    assert raw["headers"]["Authorization"] == "Bearer SECRET-TOKEN"
    assert raw["url"] == "https://ch.internal:8123/?query={sql}&token=SECRET-TOKEN"


def test_patch_source_changing_host_keeps_template_and_secret(tmp_path):
    """⚠️ 改 host 是最常见的操作 —— 不能顺带毁掉模板与密钥。"""
    client, store = _client_and_store(tmp_path)
    created = client.post("/api/platform/sources", json=_http_payload()).json()
    config = dict(created["config"])
    config["url"] = config["url"].replace("ch.internal", "ch2.internal")
    resp = client.patch(f"/api/platform/sources/{created['id']}", json={"config": config})
    assert resp.status_code == 200
    raw = store.get_source_raw(created["id"]).config
    assert raw["url"] == "https://ch2.internal:8123/?query={sql}&token=SECRET-TOKEN"


def test_catalog_does_not_leak_secrets(tmp_path):
    client, _ = _client_and_store(tmp_path)
    client.post("/api/platform/sources", json=_http_payload())
    resp = client.get("/api/platform/catalog")
    assert resp.status_code == 200
    assert "SECRET-TOKEN" not in resp.text
