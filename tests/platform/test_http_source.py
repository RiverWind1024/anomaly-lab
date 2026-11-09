"""HTTP 透传连接器。

⚠️ 这里的假端点只是**测试夹具** —— 不承担「持续产数」职责
   （那是 spec 2 的「假远端时序数据库」）。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote, urlparse

import pytest

from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.runner import load_series
from anomaly_lab.platform.sources.base import TimeContext
from anomaly_lab.platform.sources.http_sql import HttpSqlConnector, RemoteError
from anomaly_lab.platform.store import PlatformStore


class _Handler(BaseHTTPRequestHandler):
    """按测试预设的响应回话。"""

    def log_message(self, *args):
        pass

    def _payload(self):
        if self.command == "GET":
            # ⚠️ 存**原始** query 串 —— parse_qs 会把 %20 解码掉，
            #    那样就测不到「URL 里的 SQL 有没有被编码」了
            return urlparse(self.path).query
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return raw.decode(errors="replace")

    def _respond(self):
        self.server.requests.append(self._payload())
        body = self.server.body
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        else:
            body = body.encode()
        self.send_response(self.server.status)
        self.send_header("Content-Type", self.server.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._respond()

    def do_POST(self):
        self._respond()


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.status = 200
    server.body = {"data": []}
    server.content_type = "application/json"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _source(server, **config) -> Source:
    base = {
        "url": f"http://127.0.0.1:{server.server_port}/query?q={{sql}}",
        "method": "GET",
        "format": "json",
    }
    base.update(config)
    return Source(
        id=1,
        name="remote",
        kind="http",
        path="",
        created_at="2026-10-30T00:00:00+00:00",
        config=base,
    )


def _metric(**overrides) -> Metric:
    base = {
        "id": 1,
        "source_id": 1,
        "name": "demo",
        "query": "SELECT ts, value FROM t WHERE $timefilter",
        "time_column": "ts",
        "value_column": "value",
        "group_column": None,
        "time_format": "iso_utc",
        "created_at": "2026-10-30T00:00:00+00:00",
        "source_timezone": "UTC",
        "missing_policy": "drop",
    }
    base.update(overrides)
    return Metric(**base)


def test_url_template_encodes_sql(http_server):
    """URL 里的 SQL 要 URL 编码。"""
    http_server.body = {"data": []}
    HttpSqlConnector(_source(http_server)).execute_sql("SELECT 1")
    assert "SELECT%201" in http_server.requests[0]


def test_body_template_receives_raw_sql(http_server):
    """⚠️ body 里的 SQL **不能** URL 编码 —— 百分号编码会污染查询。"""
    http_server.body = {"data": []}
    source = _source(
        http_server,
        url=f"http://127.0.0.1:{http_server.server_port}/query",
        method="POST",
        format="csv",
        body={"db": "demo", "q": "{sql}", "format": "csv"},
    )
    HttpSqlConnector(source).execute_sql("SELECT ts FROM t")
    assert http_server.requests[0]["q"] == "SELECT ts FROM t"
    assert http_server.requests[0]["db"] == "demo"


def test_request_format_is_injected_when_body_omits_it(http_server):
    """⚠️ 请求的格式必须与解析的格式一致 —— body 没写就注入配置里的。"""
    http_server.body = {"data": []}
    source = _source(
        http_server,
        url=f"http://127.0.0.1:{http_server.server_port}/query",
        method="POST",
        format="json",
        body={"db": "demo", "q": "{sql}"},
    )
    HttpSqlConnector(source).execute_sql("SELECT 1")
    assert http_server.requests[0]["format"] == "json"


def test_mismatched_request_format_raises(http_server):
    """⚠️ body 里的 format 与配置不一致 → 当场报错。

    否则远端按 body 的格式返回、平台按配置的格式解析 → 解析失败，
    而且报错信息会指向完全无关的地方。
    """
    http_server.body = {"data": []}
    source = _source(
        http_server,
        url=f"http://127.0.0.1:{http_server.server_port}/query",
        method="POST",
        format="csv",
        body={"db": "demo", "q": "{sql}", "format": "json"},
    )
    with pytest.raises(ValueError, match="不一致"):
        HttpSqlConnector(source).execute_sql("SELECT 1")


def test_json_response_is_parsed(http_server):
    """⚠️ 顶层是对象时要靠 rows_path 指到那个数组。"""
    http_server.body = {"data": [{"ts": "2026-10-30T09:00:00+00:00", "value": 3.5}]}
    source = _source(http_server, rows_path="data")
    frame = HttpSqlConnector(source).execute_sql("SELECT 1")
    assert list(frame.columns) == ["ts", "value"]
    assert frame["value"].tolist() == [3.5]


def test_json_array_response_is_parsed(http_server):
    http_server.body = [{"a": 1}, {"a": 2}]
    frame = HttpSqlConnector(_source(http_server)).execute_sql("SELECT 1")
    assert len(frame) == 2


def test_rows_path_extracts_array(http_server):
    http_server.body = {"data": {"items": [{"a": 1}, {"a": 2}]}}
    source = _source(http_server, rows_path="data.items")
    frame = HttpSqlConnector(source).execute_sql("SELECT 1")
    assert len(frame) == 2


def test_missing_rows_path_raises(http_server):
    http_server.body = {"data": [{"a": 1}]}
    source = _source(http_server, rows_path="nope")
    with pytest.raises(ValueError, match="rows_path"):
        HttpSqlConnector(source).execute_sql("SELECT 1")


def test_csv_response_is_parsed(http_server):
    http_server.content_type = "text/csv"
    http_server.body = "ts,value\n2026-10-30T09:00:00+00:00,7\n"
    source = _source(http_server, format="csv")
    frame = HttpSqlConnector(source).execute_sql("SELECT 1")
    assert list(frame.columns) == ["ts", "value"]
    assert frame["value"].tolist() == [7]


def test_remote_error_status_raises(http_server):
    http_server.status = 500
    http_server.body = {"error": "boom"}
    with pytest.raises(RemoteError) as exc:
        HttpSqlConnector(_source(http_server)).execute_sql("SELECT 1")
    assert "500" in str(exc.value)


def test_timefilter_replaced_with_iso_literal(http_server):
    http_server.body = {"data": []}
    connector = HttpSqlConnector(_source(http_server))
    connector.fetch(
        _metric(),
        datetime(2026, 10, 30, tzinfo=UTC),
        datetime(2026, 10, 31, tzinfo=UTC),
    )
    # ⚠️ GET 的 query 串是**编码后**的（见 _Handler._payload）——
    #    要看 SQL 原文得先解码。
    sql = unquote(http_server.requests[0])
    assert "$timefilter" not in sql
    assert "2026-10-30T00:00:00+00:00" in sql


def test_build_time_condition_is_iso_literal(http_server):
    """⚠️ HTTP 方言用字面量（不是 julianday）—— 那是 SQLite 专有的。"""
    connector = HttpSqlConnector(_source(http_server))
    condition, params = connector.build_time_condition(
        TimeContext(
            column="ts",
            fmt="iso_utc",
            timezone="UTC",
            start=datetime(2026, 10, 30, tzinfo=UTC),
            end=datetime(2026, 10, 31, tzinfo=UTC),
        )
    )
    assert "julianday" not in condition
    assert params == ()
    assert "'2026-10-30T00:00:00+00:00'" in condition


def test_runner_load_series_works_with_http_source(http_server, tmp_path):
    """⚠️ 端到端：HTTP 源经连接器层取数。

    HTTP 源的 path 是空的 —— 走连接器层才不会去解析本地文件路径。
    """
    http_server.body = {
        "data": [
            {"ts": "2026-10-30T00:00:00+00:00", "value": 1.0, "host": "web-1"},
            {"ts": "2026-10-30T00:01:00+00:00", "value": 2.0, "host": "web-1"},
        ]
    }
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source(
        "remote",
        "",
        kind="http",
        config={
            "url": f"http://127.0.0.1:{http_server.server_port}/query?q={{sql}}",
            "method": "GET",
            "format": "json",
            "rows_path": "data",
        },
    )
    metric = store.add_metric(
        source_id=source.id,
        name="demo",
        query="SELECT ts, value, host FROM t WHERE $timefilter",
        time_column="ts",
        value_column="value",
        group_column="host",
        time_format="iso_utc",
    )
    series = load_series(
        store,
        metric,
        tmp_path,
        datetime(2026, 10, 30, tzinfo=UTC),
        datetime(2026, 10, 30, 0, 5, tzinfo=UTC),
    )
    assert [item.series_id for item in series] == ["demo:web-1"]
    assert series[0].values.tolist() == [1.0, 2.0]
