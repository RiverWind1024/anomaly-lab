"""SQLite 连接器：本地文件，只读执行。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.base import (
    MAX_ROWS,
    TimeContext,
    series_from_frame,
    time_filter_parts,
)
from anomaly_lab.platform.validation import validate_identifier, validate_query


def _connect(path: Path) -> sqlite3.Connection:
    """以只读模式打开，避免用户查询意外写入源库。"""
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def fetch_sqlite_series(
    metric: Metric,
    source_path: Path,
    start: datetime,
    end: datetime,
) -> list[SeriesBundle]:
    """在 [start, end) 区间取数，按 group_column 拆成多条序列。"""
    query = validate_query(metric.query)
    validate_identifier(metric.time_column, "time_column")
    validate_identifier(metric.value_column, "value_column")
    if metric.group_column:
        validate_identifier(metric.group_column, "group_column")
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"数据源不存在: {path}")

    condition, params = time_filter_parts(
        metric.time_column, metric.time_format, metric.source_timezone, start, end
    )
    sql = f"SELECT * FROM ({query.replace('$timefilter', condition)}) LIMIT ?"
    with closing(_connect(path)) as conn:
        cursor = conn.execute(sql, (*params, MAX_ROWS + 1))
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError(f"单次查询超过 {MAX_ROWS} 行，请缩小窗口或增加聚合")

    frame = pd.DataFrame(rows, columns=columns)
    return series_from_frame(frame, metric)


class SqliteConnector:
    """SQLite 连接器。"""

    kind = "sqlite"

    def __init__(self, source: Source, data_root: Path) -> None:
        self.source = source
        self.data_root = Path(data_root)

    @property
    def path(self) -> Path:
        """源库路径。绝对路径直接用，相对路径拼 data_root。"""
        raw = Path(self.source.path)
        return raw if raw.is_absolute() else self.data_root / raw

    def describe(self) -> str:
        return f"SQLite {self.source.path}"

    def test_connection(self) -> tuple[bool, str]:
        if not self.path.exists():
            return False, f"数据源不存在: {self.path}"
        return True, "连接正常"

    def build_time_condition(self, ctx: TimeContext) -> tuple[str, tuple]:
        return time_filter_parts(ctx.column, ctx.fmt, ctx.timezone, ctx.start, ctx.end)

    def execute_sql(
        self, sql: str, *, limit: int | None = None, params: tuple = ()
    ) -> pd.DataFrame:
        """执行只读 SQL，返回表格。"""
        text = sql
        if limit is not None:
            text = f"SELECT * FROM ({sql}) LIMIT {int(limit)}"
        with closing(_connect(self.path)) as conn:
            cursor = conn.execute(text, params)
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=columns)

    def fetch(self, metric: Metric, start: datetime, end: datetime) -> pd.DataFrame:
        """取 [start, end) 的数据（做 `$timefilter` 替换）。"""
        query = validate_query(metric.query)
        validate_identifier(metric.time_column, "time_column")
        condition, params = self.build_time_condition(
            TimeContext(
                column=metric.time_column,
                fmt=metric.time_format,
                timezone=metric.source_timezone,
                start=start,
                end=end,
            )
        )
        sql = f"SELECT * FROM ({query.replace('$timefilter', condition)}) LIMIT ?"
        with closing(_connect(self.path)) as conn:
            cursor = conn.execute(sql, (*params, MAX_ROWS + 1))
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        if len(rows) > MAX_ROWS:
            raise ValueError(f"单次查询超过 {MAX_ROWS} 行，请缩小窗口或增加聚合")
        return pd.DataFrame(rows, columns=columns)
