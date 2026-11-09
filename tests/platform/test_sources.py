"""连接器层的共用后处理与时间字面量。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pandas as pd
import pytest

from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.base import (
    TimeContext,
    series_from_frame,
    sql_literal,
    time_filter_parts,
    time_literal,
)
from anomaly_lab.platform.sources.http_sql import HttpSqlConnector
from anomaly_lab.platform.sources.sqlite import SqliteConnector
from anomaly_lab.platform.validation import validate_query, validate_readonly_sql


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


def _create_db(root: Path) -> Path:
    """建一个含 10 个点的 SQLite 源库。"""
    path = root / "src.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (ts TEXT, value REAL)")
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [
            (datetime(2026, 1, 1, 0, i, tzinfo=UTC).isoformat(), float(i))
            for i in range(10)
        ],
    )
    conn.commit()
    conn.close()
    return path


def _connector(path: Path, data_root: Path) -> SqliteConnector:
    source = Source(id=1, name="s", kind="sqlite", path=str(path), created_at="")
    return SqliteConnector(source, data_root)


def test_empty_frame_returns_no_series():
    assert series_from_frame(pd.DataFrame(), _metric()) == []


def test_missing_value_column_raises():
    frame = pd.DataFrame({"ts": ["2026-10-30T00:00:00+00:00"], "other": [1]})
    with pytest.raises(ValueError, match="缺少 value_column"):
        series_from_frame(frame, _metric())


def test_missing_group_column_raises():
    frame = pd.DataFrame(
        {"ts": ["2026-10-30T00:00:00+00:00"], "value": [1.0], "other": [2]}
    )
    with pytest.raises(ValueError, match="缺少 group_column"):
        series_from_frame(frame, _metric(group_column="host"))


def test_missing_columns_report_group_column_first():
    """⚠️ 检查顺序与重构前逐位等价 —— group_column 先于 value_column。

    两个列同时缺失时，抛的是 group_column 那条。
    """
    frame = pd.DataFrame({"ts": ["2026-10-30T00:00:00+00:00"]})
    with pytest.raises(ValueError, match="缺少 group_column"):
        series_from_frame(frame, _metric(group_column="host"))


def test_split_by_group_column():
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:00:00+00:00",
            ],
            "value": [1.0, 2.0],
            "host": ["web-1", "web-2"],
        }
    )
    series = series_from_frame(frame, _metric(group_column="host"))
    assert [item.series_id for item in series] == ["demo:web-1", "demo:web-2"]
    assert series[0].meta["group"] == "web-1"
    assert series[0].meta["sufficient"] is False  # 只有 1 个点，不足 10


def test_missing_value_dropped_by_policy():
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:05:00+00:00",
            ],
            "value": [1.0, None],
        }
    )
    series = series_from_frame(frame, _metric(missing_policy="drop"))
    assert len(series[0].values) == 1
    assert len(series[0].timestamps) == 1
    assert series[0].meta["n_missing"] == 1


def test_missing_value_interpolated_keeps_all_points():
    """⚠️ interpolate 策略下**值与时间戳长度必须都保持原样**。

    只对 drop 策略过滤时间戳 —— 否则 values 与 timestamps 长度不一致，
    `SeriesBundle.__post_init__` 会抛错。
    """
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:05:00+00:00",
                "2026-10-30T00:10:00+00:00",
            ],
            "value": [1.0, None, 3.0],
        }
    )
    series = series_from_frame(frame, _metric(missing_policy="interpolate"))
    assert len(series[0].values) == 3
    assert len(series[0].timestamps) == 3
    assert series[0].meta["n_missing"] == 1


def test_missing_policy_error_raises():
    frame = pd.DataFrame(
        {
            "ts": ["2026-10-30T00:00:00+00:00", "2026-10-30T00:05:00+00:00"],
            "value": [1.0, None],
        }
    )
    with pytest.raises(ValueError, match="缺失值"):
        series_from_frame(frame, _metric(missing_policy="error"))


def test_time_literal_iso_utc_matches_to_iso_format():
    """⚠️ 必须与平台的 to_iso() 同格式 —— T 分隔 + +00:00 偏移。

    用 Z 会让字符串字典序与时间序不一致（'+'0x2B < 'Z'0x5A），边界行被误判。
    """
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert time_literal(value, "iso_utc", "UTC") == "2026-10-30T09:38:00+00:00"


def test_time_literal_epoch_formats():
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert time_literal(value, "epoch_s", "UTC") == "1793353080"
    assert time_literal(value, "epoch_ms", "UTC") == "1793353080000"


def test_sql_literal_quotes_strings_but_not_numbers():
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert sql_literal(value, "iso_utc", "UTC") == "'2026-10-30T09:38:00+00:00'"
    assert sql_literal(value, "epoch_s", "UTC") == "1793353080"


def test_time_literal_rejects_unknown_format():
    with pytest.raises(ValueError, match="不支持的 time_format"):
        time_literal(datetime(2026, 1, 1, tzinfo=UTC), "nope", "UTC")


def test_time_literal_iso_naive_uses_source_timezone_wall_clock():
    """`iso_naive` 渲染的是**源时区的墙钟**，不带时区后缀。"""
    value = datetime(2026, 10, 30, 9, 38, tzinfo=UTC)
    assert time_literal(value, "iso_naive", "Asia/Shanghai") == "2026-10-30T17:38:00"
    assert sql_literal(value, "iso_naive", "Asia/Shanghai") == "'2026-10-30T17:38:00'"


def test_time_filter_parts_renders_julianday_condition():
    """SQLite 侧用 julianday() 按时间语义比较；参数是**空格**分隔的 UTC 文本。"""
    start = datetime(2026, 10, 30, tzinfo=UTC)
    end = datetime(2026, 10, 31, tzinfo=UTC)
    condition, params = time_filter_parts("ts", "iso_utc", "UTC", start, end)
    assert condition == 'julianday("ts") >= julianday(?) AND julianday("ts") < julianday(?)'
    assert params == ("2026-10-30 00:00:00+00:00", "2026-10-31 00:00:00+00:00")


def test_series_from_frame_does_not_mutate_input_frame():
    """⚠️ `series_from_frame` 内部必须 `.copy()` —— 它会把时间列就地换成时间戳。

    改到调用方的 frame 上，调用者手里的原始表就被污染了。
    """
    frame = pd.DataFrame(
        {
            "ts": ["2026-10-30T00:00:00+00:00", "2026-10-30T00:05:00+00:00"],
            "value": [1.0, 2.0],
        }
    )
    before = frame.copy()
    series_from_frame(frame, _metric())
    pd.testing.assert_frame_equal(frame, before)


def test_group_key_none_becomes_nan_label():
    """⚠️ pandas 的 `groupby(dropna=False)` 给的 key 是 `nan`，不是 `None`。

    所以空分组值的标签是 "nan"（`str(nan)`），而不是 "null"。
    """
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:00:00+00:00",
            ],
            "value": [1.0, 2.0],
            "host": [None, "web-1"],
        }
    )
    series = series_from_frame(frame, _metric(group_column="host"))
    assert [item.series_id for item in series] == ["demo:nan", "demo:web-1"]
    assert series[0].meta["group"] == "nan"


def test_group_key_nan_becomes_nan_label():
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:00:00+00:00",
            ],
            "value": [1.0, 2.0],
            "host": [float("nan"), "web-1"],
        }
    )
    series = series_from_frame(frame, _metric(group_column="host"))
    assert [item.series_id for item in series] == ["demo:nan", "demo:web-1"]
    assert series[0].meta["group"] == "nan"


# ---------- SqliteConnector ----------


def test_connector_path_resolves_relative_against_data_root(tmp_path):
    connector = SqliteConnector(
        Source(id=1, name="s", kind="sqlite", path="sub/src.db", created_at=""),
        tmp_path,
    )
    assert connector.path == tmp_path / "sub" / "src.db"

    absolute = SqliteConnector(
        Source(id=1, name="s", kind="sqlite", path=str(tmp_path / "x.db"), created_at=""),
        tmp_path,
    )
    assert absolute.path == tmp_path / "x.db"


def test_execute_sql_wraps_limit_and_binds_params(tmp_path):
    connector = _connector(_create_db(tmp_path), tmp_path)
    unbounded = connector.execute_sql("SELECT value FROM t WHERE value >= ?", params=(5.0,))
    assert unbounded["value"].tolist() == [5.0, 6.0, 7.0, 8.0, 9.0]

    limited = connector.execute_sql(
        "SELECT value FROM t WHERE value >= ?", limit=2, params=(5.0,)
    )
    assert limited["value"].tolist() == [5.0, 6.0]


def test_test_connection_detects_missing_and_corrupt_files(tmp_path):
    missing_ok, missing_msg = _connector(tmp_path / "nope.db", tmp_path).test_connection()
    assert missing_ok is False
    assert "不存在" in missing_msg

    good = _connector(_create_db(tmp_path), tmp_path)
    assert good.test_connection() == (True, "连接正常")

    # ⚠️ 文件存在但不是 SQLite 库 —— 不能报「连接正常」
    broken = tmp_path / "broken.db"
    broken.write_text("this is not a sqlite database", encoding="utf-8")
    broken_ok, broken_msg = _connector(broken, tmp_path).test_connection()
    assert broken_ok is False
    assert "无法打开数据源" in broken_msg


# ---------- 查询校验的两档 ----------


def test_readonly_sql_does_not_require_timefilter():
    """浏览用的 SQL 不该强制带 $timefilter —— 那是指标的要求。"""
    assert validate_readonly_sql("SELECT ts, value FROM t LIMIT 10")


def test_readonly_sql_rejects_non_select():
    with pytest.raises(ValueError, match="SELECT 或 WITH"):
        validate_readonly_sql("DELETE FROM t")


def test_readonly_sql_rejects_multiple_statements():
    with pytest.raises(ValueError, match="单条语句"):
        validate_readonly_sql("SELECT 1; SELECT 2")


def test_readonly_sql_rejects_write_keywords():
    """⚠️ 输入必须以 SELECT 开头 —— 否则先撞上「必须以 SELECT 开头」那条。

    写关键字藏在 SELECT 里（子查询 / UNION）才是真正要拦的。
    """
    with pytest.raises(ValueError, match="写操作"):
        validate_readonly_sql("SELECT id FROM t WHERE id IN (SELECT id FROM drop)")


def test_metric_query_still_requires_exactly_one_timefilter():
    with pytest.raises(ValueError, match="timefilter"):
        validate_query("SELECT ts FROM t")
    with pytest.raises(ValueError, match="timefilter"):
        validate_query("SELECT ts FROM t WHERE $timefilter AND x = $timefilter")
    assert validate_query("SELECT ts FROM t WHERE $timefilter")


# ---------- 连接器注册表 ----------


def test_get_connector_returns_sqlite_connector(tmp_path):
    from anomaly_lab.platform.sources import get_connector

    source = Source(
        id=1, name="local", kind="sqlite", path="platform/source.db",
        created_at="2026-10-30T00:00:00+00:00",
    )
    connector = get_connector(source, tmp_path)
    assert connector.kind == "sqlite"


def test_get_connector_returns_http_connector(tmp_path):
    from anomaly_lab.platform.sources import get_connector

    source = Source(
        id=2, name="remote", kind="http", path="",
        created_at="2026-10-30T00:00:00+00:00",
        config={"url": "https://x/q?q={sql}"},
    )
    connector = get_connector(source, tmp_path)
    assert connector.kind == "http"


def test_get_connector_rejects_unknown_kind(tmp_path):
    from anomaly_lab.platform.sources import get_connector

    source = Source(
        id=3, name="x", kind="kafka", path="",
        created_at="2026-10-30T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="不支持的数据源类型"):
        get_connector(source, tmp_path)


# ---------- 时间列名的注入面 ----------


def test_sqlite_build_time_condition_rejects_injected_column(tmp_path):
    """⚠️ 浏览端点是用户自由输入的入口 —— 列名必须过标识符校验。"""
    connector = _connector(_create_db(tmp_path), tmp_path)
    with pytest.raises(ValueError, match="time_column"):
        connector.build_time_condition(
            TimeContext(
                column='ts" ; DROP TABLE users ; --',
                fmt="iso_utc",
                timezone="UTC",
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )


def test_http_build_time_condition_rejects_injected_column():
    """⚠️ HTTP 侧同样要拒 —— 不校验就等于把写关键字送到远端执行。"""
    connector = HttpSqlConnector(
        Source(
            id=1, name="remote", kind="http", path="",
            created_at="2026-10-30T00:00:00+00:00",
            config={"url": "https://x/q?q={sql}"},
        )
    )
    with pytest.raises(ValueError, match="time_column"):
        connector.build_time_condition(
            TimeContext(
                column='ts" ; DROP TABLE users ; --',
                fmt="iso_utc",
                timezone="UTC",
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )


# ---------- 连接器一致性：sqlite 与 http 必须给出同一份结果 ----------


_ROWS = [
    {"ts": "2026-10-30T00:00:00+00:00", "value": 1.0},
    {"ts": "2026-10-30T00:05:00+00:00", "value": 2.0},
]


@pytest.fixture
def rows_server():
    """一个只会返回固定几行的假远端。"""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps({"data": _ROWS}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def test_sqlite_and_http_connectors_return_same_series(tmp_path, rows_server):
    """⚠️ spec §8：同一段 SQL、同一区间 → 两条路径返回相同的 SeriesBundle 集合。

    SQLite 侧真的存在一张表（窗口外还有一行），
    远端侧返回它自己算出来的窗口内结果 —— 两边必须一致。
    """
    db = tmp_path / "src.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (ts TEXT, value REAL)")
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [
            ("2026-10-30T00:00:00+00:00", 1.0),
            ("2026-10-30T00:05:00+00:00", 2.0),
            ("2026-10-31T00:00:00+00:00", 3.0),  # 窗口外 —— SQLite 侧要滤掉
        ],
    )
    conn.commit()
    conn.close()

    metric = _metric()
    start = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 30, 0, 10, tzinfo=UTC)

    sqlite_series = series_from_frame(
        _connector(db, tmp_path).fetch(metric, start, end), metric
    )
    http_series = series_from_frame(
        HttpSqlConnector(
            Source(
                id=1, name="remote", kind="http", path="",
                created_at="2026-10-30T00:00:00+00:00",
                config={
                    "url": f"http://127.0.0.1:{rows_server.server_port}/q?q={{sql}}",
                    "rows_path": "data",
                },
            )
        ).fetch(metric, start, end),
        metric,
    )

    assert [item.series_id for item in sqlite_series] == [
        item.series_id for item in http_series
    ]
    assert len(sqlite_series) == 1
    assert sqlite_series[0].values.tolist() == http_series[0].values.tolist() == [1.0, 2.0]
    assert sqlite_series[0].timestamps.tolist() == http_series[0].timestamps.tolist()


def test_sqlite_browse_and_metric_paths_agree(tmp_path):
    """⚠️ D11：浏览路径与指标路径必须给出**同一批行**。

    浏览走 `execute_sql` + 自己替换条件，指标走 `fetch` ——
    两条路径的条件必须逐字相同（同一个 `build_time_condition`）。
    """
    connector = _connector(_create_db(tmp_path), tmp_path)
    metric = _metric()
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)

    condition, params = connector.build_time_condition(
        TimeContext(
            column="ts", fmt="iso_utc", timezone="UTC", start=start, end=end
        )
    )
    browse = connector.execute_sql(
        metric.query.replace("$timefilter", condition), params=params
    )
    runtime = connector.fetch(metric, start, end)

    assert browse["value"].tolist() == runtime["value"].tolist()
    assert browse["ts"].tolist() == runtime["ts"].tolist()
