"""数据浏览器端点。"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import unquote

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


class _RecordingHandler(BaseHTTPRequestHandler):
    """记录收到的请求 —— 用来断言「远端到底收到了什么」。"""

    def log_message(self, *args):
        pass

    def _respond(self):
        self.server.requests.append(self.path)
        body = self.server.body
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        else:
            body = body.encode()
        try:
            self.send_response(self.server.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # ⚠️ 客户端超时断开后写响应会炸 —— 那正是超时用例的常态
            pass

    def do_GET(self):
        self._respond()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        self.server.requests.append(raw.decode(errors="replace"))
        self._respond()


@pytest.fixture
def recording_remote():
    """一个会记录请求的假远端。"""
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.requests = []
    server.status = 200
    server.body = {"data": [{"ts": "2026-10-30T09:00:00+00:00", "value": 3.5}]}
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


def _client_with_config(tmp_path, config, name="remote"):
    client = TestClient(create_app(platform_data_root=tmp_path))
    response = client.post(
        "/api/platform/sources",
        json={"name": name, "kind": "http", "config": config},
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


def test_timefilter_error_tells_user_how_to_unblock(tmp_path, remote):
    """⚠️ 消息必须**可操作**。

    ⚠️ 用户正是靠这条 SQL 才知道结果里有哪些列的 ——
       只说「需要指定时间列」，他不知道自己下一步该干什么。
       告诉他绕法：先去掉 $timefilter 跑一次看列，再把时间列填回来。
    """
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts FROM t WHERE $timefilter"},
    )
    detail = response.json()["detail"]
    assert "先去掉 $timefilter" in detail
    assert "时间列" in detail


# ---------- time_values：给前端画时序图用的时间轴坐标 ----------


def _sqlite_client_with_rows(tmp_path, rows, ddl="CREATE TABLE metrics (ts, value)"):
    """建一个 SQLite 源，行内容自定。"""
    db = tmp_path / "source.db"
    conn = sqlite3.connect(db)
    conn.execute(ddl)
    conn.executemany("INSERT INTO metrics VALUES (?, ?)", rows)
    conn.commit()
    conn.close()
    client = TestClient(create_app(platform_data_root=tmp_path))
    response = client.post(
        "/api/platform/sources",
        json={"name": "local", "kind": "sqlite", "path": "source.db"},
    )
    assert response.status_code == 200, response.text
    return client, response.json()["id"]


def test_time_values_is_null_without_time_column(tmp_path):
    """没指定时间列 → 没有时间轴坐标（图不画）。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT ts, value FROM metrics"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["time_values"] is None


def test_time_values_are_epoch_milliseconds(tmp_path):
    """⚠️ 时间轴坐标是 **epoch 毫秒** —— ECharts 的时间轴吃毫秒。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics",
            "time_column": "ts",
            "time_format": "iso_utc",
        },
    )
    assert response.status_code == 200, response.text
    values = response.json()["time_values"]
    assert len(values) == 2
    # 2026-10-30T00:00:00Z = 1793318400000 ms
    assert values[0] == 1793318400000
    assert values[1] == 1793318700000


def test_time_values_follow_source_timezone_for_naive_timestamps(tmp_path):
    """⚠️ `iso_naive` 的墙钟按**源时区**解释 —— 这是与指标运行时同一份逻辑。

    ⚠️ 放前端自己解析必然漂移 —— 这条测试守的就是「别漂移」。
    """
    client, source_id = _sqlite_client_with_rows(
        tmp_path, [("2026-10-30 08:00:00", 1.0), ("2026-10-30 08:05:00", 2.0)]
    )
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics",
            "time_column": "ts",
            "time_format": "iso_naive",
            "source_timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 200, response.text
    values = response.json()["time_values"]
    # 08:00 东八区 = 00:00 UTC
    assert values[0] == 1793318400000


def test_time_values_respect_epoch_unit(tmp_path):
    """⚠️ epoch_s 与 epoch_ms 差 1000 倍 —— 弄错就是 1970 年附近。"""
    client, source_id = _sqlite_client_with_rows(
        tmp_path,
        [(1793328000, 1.0), (1793328300, 2.0)],
        ddl="CREATE TABLE metrics (ts INTEGER, value REAL)",
    )
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics",
            "time_column": "ts",
            "time_format": "epoch_s",
        },
    )
    assert response.status_code == 200, response.text
    # 源数据是 1793328000 秒 → 毫秒就是 ×1000
    assert response.json()["time_values"][0] == 1793328000000


def test_time_values_null_for_unparseable_rows(tmp_path):
    """⚠️ 解析不出来的行给 None（断点）—— **绝不画到 1970 年**。

    那样看着像「数据都在 1970 年」，比空白更误导。
    """
    client, source_id = _sqlite_client_with_rows(
        tmp_path, [("2026-10-30T00:00:00+00:00", 1.0), ("不是时间", 2.0)]
    )
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics",
            "time_column": "ts",
            "time_format": "iso_utc",
        },
    )
    assert response.status_code == 200, response.text
    values = response.json()["time_values"]
    assert values[0] == 1793318400000
    assert values[1] is None


def test_time_values_null_when_column_not_in_result(tmp_path):
    """指定的时间列不在结果里 → 没有时间轴坐标（而不是报错）。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT value FROM metrics", "time_column": "ts"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["time_values"] is None


def test_time_values_row_count_matches_rows(tmp_path):
    """⚠️ `time_values` 与 `rows` 必须**逐行对应** —— 错位了图就是错的。"""
    client, source_id = _sqlite_client_with_rows(
        tmp_path, [(f"2026-10-30T00:0{i}:00+00:00", float(i)) for i in range(5)]
    )
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics",
            "time_column": "ts",
            "time_format": "iso_utc",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["time_values"]) == len(body["rows"])


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


def test_freq_and_window_points_compute_the_window(tmp_path):
    """⚠️ 给了 `freq` + `window_points` → 时间范围由平台算。

    这让「指标预览」能取到**告警任务真正会取的那一段**，
    而不是让前端自己算（算错了就是「预览的不是跑出来的」）。
    """
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "time_format": "iso_utc",
            "freq": "5min",
            "window_points": 60,
        },
    )
    assert response.status_code == 200, response.text
    # 范围是「现在往前 5 小时」—— 库里那两条 2026 年的数据不在窗口里
    assert response.json()["total"] == 0


def test_window_range_matches_runtime_computation(tmp_path):
    """⚠️ **同一段代码**算范围 —— 浏览与指标运行时必须一致。

    指标运行时：`end - freq_delta(freq) * window_points`（runner.py）。
    浏览端点用的是同一个 `freq_delta` —— 逻辑放两处必然漂移。
    """
    from anomaly_lab.platform.timeutil import freq_delta, utcnow

    client, source_id = _sqlite_client(tmp_path)
    before = utcnow()
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "time_format": "iso_utc",
            "freq": "1min",
            "window_points": 30,
        },
    )
    after = utcnow()
    assert response.status_code == 200, response.text

    # 端点算的范围应当落在 [before - 30min, after] 之内
    expected_start = before - freq_delta("1min") * 30
    expected_end = after
    assert expected_start <= expected_end
    # 用一条落在窗口内的数据验证真的生效
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute(
        "INSERT INTO metrics VALUES (?, ?)",
        ((before - freq_delta("1min") * 5).isoformat(), 9.0),
    )
    conn.commit()
    conn.close()

    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "time_format": "iso_utc",
            "freq": "1min",
            "window_points": 30,
        },
    )
    assert response.json()["total"] == 1


def test_explicit_start_end_wins_over_window(tmp_path):
    """⚠️ 显式给了 start/end 就用显式的 —— 窗口参数只是默认值。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts",
            "time_format": "iso_utc",
            "start": "2026-10-30T00:00:00+00:00",
            "end": "2026-10-30T01:00:00+00:00",
            "freq": "5min",
            "window_points": 60,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2


def test_query_limit_is_pushed_down_and_truncated_marks_more_rows(tmp_path):
    """⚠️ limit 必须**下推**到 SQL —— 否则整个结果集会被拉进内存。

    `total` 是**本次取到的行数**（≤ limit），`truncated` 表示「还有更多」。
    """
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT ts, value FROM metrics", "limit": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 1
    assert body["total"] == 1
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


# ---------- 注入面：time_column 必须过标识符校验 ----------


def test_query_rejects_injected_time_column(tmp_path, recording_remote):
    """⚠️ 浏览端点的 `time_column` 必须过 `validate_identifier`。

    只读校验跑在**替换之前** —— 注入内容是替换之后才进 SQL 的，
    不校验就等于把写关键字原样送到远端执行（黑名单被完全绕过）。
    """
    client, source = _client_with_config(
        tmp_path,
        {
            "url": f"http://127.0.0.1:{recording_remote.server_port}/q?q={{sql}}",
            "rows_path": "data",
        },
    )
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={
            "sql": "SELECT ts, value FROM t WHERE $timefilter",
            "time_column": 'ts" ; DROP TABLE users ; --',
        },
    )
    assert response.status_code == 400, response.text
    # ⚠️ 远端**一个请求都不能收到** —— 收到了就说明校验没生效
    assert recording_remote.requests == []


def test_query_rejects_injected_time_column_on_sqlite_source(tmp_path):
    """SQLite 侧同样要拒 —— 两套连接器都得堵。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={
            "sql": "SELECT ts, value FROM metrics WHERE $timefilter",
            "time_column": "ts; DROP TABLE metrics",
        },
    )
    assert response.status_code == 400, response.text


# ---------- 错误码分类 ----------


def test_query_timeout_is_504(tmp_path):
    """⚠️ 超时是**本地**判断（504）—— 不是远端的错（502）。

    这是唯一依赖 urllib 异常形态的分支：读超时会被 urllib 包成
    `URLError(socket.timeout)`，靠 `reason` 才认得出是超时。
    """
    class _Slow(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            time.sleep(3)
            try:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client, source = _client_with_config(
            tmp_path,
            {
                "url": f"http://127.0.0.1:{server.server_port}/q?q={{sql}}",
                "timeout_seconds": 1,
            },
        )
        response = client.post(
            f"/api/platform/sources/{source['id']}/query",
            json={"sql": "SELECT 1"},
        )
        assert response.status_code == 504, response.text
    finally:
        server.shutdown()


def test_query_on_remote_4xx_is_502(tmp_path):
    """⚠️ 远端 4xx（如 SQL 语法错）也是 502 —— 平台把远端的错透传出来。"""
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.requests = []
    server.status = 404
    server.body = {"error": "no such table"}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client, source = _client_with_config(
            tmp_path, {"url": f"http://127.0.0.1:{server.server_port}/q?q={{sql}}"}
        )
        response = client.post(
            f"/api/platform/sources/{source['id']}/query",
            json={"sql": "SELECT 1"},
        )
        assert response.status_code == 502, response.text
        assert "404" in response.json()["detail"]
    finally:
        server.shutdown()


def test_query_on_unreachable_remote_is_502(tmp_path):
    """连不上远端 → 502（「远端挂了」），不是 500。"""
    # 找一个**没人监听**的端口：绑一下就放开
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    client, source = _client_with_config(
        tmp_path, {"url": f"http://127.0.0.1:{port}/q?q={{sql}}"}
    )
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert response.status_code == 502, response.text


def test_query_on_unparsable_remote_response_is_502(tmp_path, recording_remote):
    """⚠️ 远端返回的东西**解析不了**是 502 —— 那不是「配置错」。

    与「body 与 config 的 format 对不上」（400）必须分得开。
    """
    recording_remote.body = "这不是 JSON"
    client, source = _client_with_config(
        tmp_path, {"url": f"http://127.0.0.1:{recording_remote.server_port}/q?q={{sql}}"}
    )
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert response.status_code == 502, response.text


def test_query_with_mismatched_body_format_is_400(tmp_path, recording_remote):
    """⚠️ body 里的 format 与 config 不一致 —— 那是**配置错**（400），不是 502。"""
    client, source = _client_with_config(
        tmp_path,
        {
            "url": f"http://127.0.0.1:{recording_remote.server_port}/q",
            "method": "POST",
            "format": "csv",
            "body": {"q": "{sql}", "format": "json"},
        },
    )
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT 1"},
    )
    assert response.status_code == 400, response.text
    assert "不一致" in response.json()["detail"]


def test_query_on_invalid_kind_is_400(tmp_path):
    """⚠️ 库里 kind 被手改成非法值 —— 是**配置错**（400），不是 500。"""
    client, source_id = _sqlite_client(tmp_path)
    conn = sqlite3.connect(tmp_path / "platform.db")
    conn.execute("UPDATE sources SET kind = 'kafka' WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()

    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT 1"},
    )
    assert response.status_code == 400, response.text
    assert "不支持的数据源类型" in response.json()["detail"]


# ---------- limit 必须下推 ----------


def test_query_limit_is_pushed_down_to_remote(tmp_path, recording_remote):
    """⚠️ limit 必须**下推**到 SQL —— 否则整个结果集会被拉进内存。

    多取一行用来判断「还有更多」（`truncated`）。
    """
    client, source = _client_with_config(
        tmp_path,
        {"url": f"http://127.0.0.1:{recording_remote.server_port}/q?q={{sql}}"},
    )
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts, value FROM t", "limit": 10},
    )
    assert response.status_code == 200, response.text
    assert len(recording_remote.requests) == 1
    sent = unquote(recording_remote.requests[0])
    assert "LIMIT 11" in sent


def test_query_limit_pushdown_on_sqlite_source(tmp_path):
    """SQLite 侧同样下推 —— 结果集不会全量进内存。"""
    client, source_id = _sqlite_client(tmp_path)
    response = client.post(
        f"/api/platform/sources/{source_id}/query",
        json={"sql": "SELECT ts, value FROM metrics", "limit": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["truncated"] is True


def test_query_truncated_is_false_when_result_fits(tmp_path, recording_remote):
    """结果比 limit 少 → `truncated` 为 False。"""
    client, source = _client_with_config(
        tmp_path,
        {"url": f"http://127.0.0.1:{recording_remote.server_port}/q?q={{sql}}"},
    )
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts, value FROM t", "limit": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["truncated"] is False


# ---------- D11：浏览路径与指标路径生成同一条时间条件 ----------


def test_browse_and_metric_paths_generate_same_time_condition(tmp_path, recording_remote):
    """⚠️ D11：浏览预览与指标运行时必须生成**同一条** `$timefilter` 条件。

    否则「预览看到的」≠「跑出来的」—— 用户按预览建的指标是错的。
    """
    from anomaly_lab.platform.models import Metric, Source
    from anomaly_lab.platform.sources.base import TimeContext
    from anomaly_lab.platform.sources.http_sql import HttpSqlConnector

    url = f"http://127.0.0.1:{recording_remote.server_port}/q?q={{sql}}"
    client, source = _client_with_config(tmp_path, {"url": url})

    start = "2026-10-30T00:00:00+00:00"
    end = "2026-10-31T00:00:00+00:00"
    sql = "SELECT ts, value FROM t WHERE $timefilter"

    # 1. 浏览路径
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={
            "sql": sql,
            "time_column": "ts",
            "time_format": "iso_utc",
            "source_timezone": "UTC",
            "start": start,
            "end": end,
        },
    )
    assert response.status_code == 200, response.text
    browse_sql = unquote(recording_remote.requests[-1])

    # 2. 指标路径
    recording_remote.requests.clear()
    connector = HttpSqlConnector(
        Source(
            id=source["id"], name="remote", kind="http", path="",
            created_at="2026-10-30T00:00:00+00:00", config={"url": url},
        )
    )
    connector.fetch(
        Metric(
            id=1, source_id=source["id"], name="demo", query=sql,
            time_column="ts", value_column="value", group_column=None,
            time_format="iso_utc", freq="5min",
            created_at="2026-10-30T00:00:00+00:00",
            source_timezone="UTC", missing_policy="drop",
        ),
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
    )
    metric_sql = unquote(recording_remote.requests[-1])

    # ⚠️ 两条路径的条件必须逐字相同
    condition, _ = connector.build_time_condition(
        TimeContext(
            column="ts", fmt="iso_utc", timezone="UTC",
            start=datetime.fromisoformat(start),
            end=datetime.fromisoformat(end),
        )
    )
    assert condition in browse_sql
    assert condition in metric_sql

