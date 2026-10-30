"""SPA 托管：深链接回退到 index.html，拼错的 API 仍回 JSON 404。

三条硬约束（都在 app.py 的 catch-all 上）：
1. catch-all 必须注册在所有 /api/* 路由之后
2. catch-all 必须在 /static 挂载之后
3. 不能 app.mount("/") —— Mount("/") 的正则会吞掉后面注册的一切
"""

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_spa_route_returns_index_html(make_dist):
    """深链接（刷新页面）不能让用户吃 404。"""
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/jobs/1")
    assert resp.status_code == 200
    assert "根" in resp.text


def test_unknown_api_path_returns_404_json(make_dist):
    """拼错的 API 不该拿到 HTML。"""
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/api/typo")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_asset_file_is_served(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_missing_dist_returns_503_without_crashing(tmp_path):
    """dist 不存在时 create_app 不能崩，页面请求给 503 + 人话提示。"""
    client = TestClient(create_app(frontend_dist=tmp_path / "不存在"))
    resp = client.get("/jobs/1")
    assert resp.status_code == 503
    assert "make frontend-build" in resp.text


def test_missing_dist_still_returns_404_for_api_typo(tmp_path):
    """⚠️ api/ 前缀判断要在 503 判断之前 —— 否则 /api/typo 会变 503。"""
    client = TestClient(create_app(frontend_dist=tmp_path / "不存在"))
    resp = client.get("/api/typo")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_existing_api_still_works(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    assert client.get("/api/health").json() == {"status": "ok"}


def test_path_traversal_cannot_escape_dist(tmp_path, make_dist):
    """⚠️ 安全回归：catch-all 不能变成任意文件读取。

    `dist / '../secret.txt'` 会指向 dist 外的文件；百分号编码的 %2f
    不会被 httpx 规范化掉，会原样到达 Starlette。
    """
    (tmp_path / "secret.txt").write_text("SECRET-CONTENT", encoding="utf-8")
    client = TestClient(create_app(frontend_dist=make_dist()))
    for path in ("/..%2fsecret.txt", "/%2e%2e/secret.txt"):
        resp = client.get(path)
        assert "SECRET-CONTENT" not in resp.text
        # 应该回退到 index.html
        assert resp.status_code == 200
        assert "根" in resp.text
