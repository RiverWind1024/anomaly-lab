"""连接器层的共用后处理与时间字面量。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.base import (
    series_from_frame,
    sql_literal,
    time_filter_parts,
    time_literal,
)
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
        "freq": "5min",
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
