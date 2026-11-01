"""数据浏览器端点。"""

from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps(
            {"data": [{"ts": "2026-10-30T09:00:00+00:00", "value": 3.5}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def remote():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _client(tmp_path, remote):
    client = TestClient(create_app(platform_data_root=tmp_path))
    response = client.post(
        "/api/platform/sources",
        json={
            "name": "remote",
            "kind": "http",
            "config": {
                "url": f"http://127.0.0.1:{remote.server_port}/q?q={{sql}}",
                "rows_path": "data",
            },
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()


def _sqlite_client(tmp_path):
    """建一个本地 SQLite 源，返回 (client, source_id)。"""
    db = tmp_path / "source.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, value REAL)")
    conn.executemany(
        "INSERT INTO metrics VALUES (?, ?)",
        [("2026-10-30T00:00:00+00:00", 1.0), ("2026-10-30T00:05:00+00:00", 2.0)],
    )
    conn.commit()
    conn.close()
    client = TestClient(create_app(platform_data_root=tmp_path))
    response = client.post(
        "/api/platform/sources",
        json={"name": "local", "kind": "sqlite", "path": "source.db"},
    )
    assert response.status_code == 200, response.text
    return client, response.json()["id"]


def test_query_returns_columns_and_rows(tmp_path, remote):
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts, value FROM t", "limit": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [col["name"] for col in body["columns"]] == ["ts", "value"]
    assert body["rows"] == [["2026-10-30T09:00:00+00:00", 3.5]]
    assert "elapsed_ms" in body
    assert body["total"] == 1
    assert body["truncated"] is False


def test_query_rejects_write_sql(tmp_path, remote):
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "DELETE FROM t"},
    )
    assert response.status_code == 400


def test_query_with_timefilter_without_time_column_is_400(tmp_path, remote):
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts FROM t WHERE $timefilter"},
    )
    assert response.status_code == 400
    assert "time_column" in response.json()["detail"]


def test_query_on_missing_source_is_404(tmp_path, remote):
    client, _ = _client(tmp_path, remote)
    response = client.post(
        "/api/platform/sources/999/query",
        json={"sql": "SELECT 1"},
    )
    assert response.status_code == 404


def test_query_on_remote_error_is_502(tmp_path):
    class _Boom(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Boom)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = TestClient(create_app(platform_data_root=tmp_path))
        source = client.post(
            "/api/platform/sources",
            json={
                "name": "boom",
                "kind": "http",
                "config": {"url": f"http://127.0.0.1:{server.server_port}/q?q={{sql}}"},
            },
        ).json()
        response = client.post(
            f"/api/platform/sources/{source['id']}/query",
            json={"sql": "SELECT 1"},
        )
        assert response.status_code == 502
    finally:
        server.shutdown()


def test_query_on_sqlite_source_with_timefilter(tmp_path):
    """⚠️ SQLite 的时间条件带 `?` 绑定参数 —— 端点必须把 params 传给 execute_sql。

    不传的话会抛 `Incorrect number of bindings supplied`。
    """
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "time_format": "iso_utc",
            "start": "2026-10-30T00:00:00+00:00",
            "end": "2026-10-30T01:00:00+00:00",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert body["rows"][0][1] == 1.0


def test_query_on_sqlite_source_timefilter_excludes_out_of_range_rows(tmp_path):
    """时间条件真的生效 —— 窗口外的行不该出现。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "time_format": "iso_utc",
            "start": "2026-10-30T00:00:00+00:00",
            "end": "2026-10-30T00:03:00+00:00",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1


def test_query_limit_truncates_rows_but_keeps_total(tmp_path):
    """limit 只截**返回**的行 —— total 仍是真实总行数，truncated 标记截断。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT ts, value FROM metrics", "limit": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["total"] == 2
    assert body["truncated"] is True


@pytest.mark.parametrize(
    "template",
    [
        "SELECT ts, value FROM metrics WHERE ts >= {start} AND ts < {end}",
        "SELECT ts, value FROM metrics WHERE ts >= '{start}' AND ts < '{end}'",
    ],
)
def test_query_supports_start_end_placeholders(tmp_path, template):
    """`{start}` / `{end}` 占位符 —— 用户自己写列名，不依赖 $timefilter。

    ⚠️ 带引号与不带引号都要认 —— 用户手写 SQL 时很可能自己加了引号，
       而平台插入的字面量**自带**引号。
    """
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": template,
            "time_format": "iso_utc",
            "start": "2026-10-30T00:00:00+00:00",
            "end": "2026-10-30T00:03:00+00:00",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0][1] == 1.0


def test_query_turns_null_into_json_null(tmp_path):
    """NULL 要变成 JSON 的 null —— 留着 NaN 会让序列化直接 500。

    ⚠️ Starlette 的 JSONResponse 用 allow_nan=False 序列化。
    """
    conn = sqlite3.connect(tmp_path / "nulls.db")
    conn.execute("CREATE TABLE t (ts TEXT, value REAL)")
    conn.execute("INSERT INTO t VALUES ('2026-10-30T00:00:00+00:00', NULL)")
    conn.commit()
    conn.close()
    client = TestClient(create_app(platform_data_root=tmp_path))
    source = client.post(
        "/api/platform/sources",
        json={"name": "nulls", "kind": "sqlite", "path": "nulls.db"},
    ).json()
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts, value FROM t"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [["2026-10-30T00:00:00+00:00", None]]


def test_query_on_sqlite_source_with_bad_sql_is_400(tmp_path):
    """⚠️ SQL 写错是**用户的错** → 400（不是 502，那是「远端挂了」的意思）。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT * FROM 不存在的表"},
    )
    assert response.status_code == 400
    assert "不存在的表" in response.json()["detail"]
