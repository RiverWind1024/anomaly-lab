"""SQLite 数据源：只读执行带 $timefilter 的查询，并按 group by 拆成独立序列。

拆分放在加载层：检测器永远只面对「一条序列」，与用户想法一致。

时间语义不猜：时间列的存储形式由 `time_format` 声明，无时区时间戳按
`source_timezone` 解释（对应 CloudWatch 的 MetricTimezone）。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.validation import validate_identifier, validate_query

MAX_ROWS = 100_000
MIN_VALID_POINTS = 10


def _connect(path: Path) -> sqlite3.Connection:
    """以只读模式打开，避免用户查询意外写入源库。"""
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _wall_clock(value: datetime, timezone_name: str) -> str:
    """把 UTC 时刻转成源库时区的墙钟字符串（不带时区后缀）。"""
    local = value.astimezone(ZoneInfo(timezone_name))
    return local.replace(tzinfo=None).isoformat(sep=" ")


def _time_filter(metric: Metric, start: datetime, end: datetime) -> tuple[str, tuple]:
    """返回 (SQL 条件, 参数)。列名已校验，时间值一律参数绑定。"""
    column = f'"{metric.time_column}"'
    if metric.time_format in {"iso_utc", "iso_naive"}:
        if metric.time_format == "iso_utc":
            low = start.astimezone(UTC).isoformat(sep=" ")
            high = end.astimezone(UTC).isoformat(sep=" ")
        else:
            # 源库存的是源时区的墙钟时间，边界也要换算成墙钟再比较
            low = _wall_clock(start, metric.source_timezone)
            high = _wall_clock(end, metric.source_timezone)
        # julianday 让 SQLite 按时间语义比较，避开 ISO 字符串字典序的坑
        condition = f"julianday({column}) >= julianday(?) AND julianday({column}) < julianday(?)"
        return condition, (low, high)
    if metric.time_format == "epoch_s":
        low, high = int(start.timestamp()), int(end.timestamp())
    elif metric.time_format == "epoch_ms":
        low, high = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    else:
        raise ValueError(f"不支持的 time_format: {metric.time_format}")
    return f"{column} >= ? AND {column} < ?", (low, high)


def _group_label(value: object) -> str:
    if value is None:
        return "null"
    text = str(value)
    return text if text else "null"


def _parse_time_column(frame: pd.DataFrame, metric: Metric) -> pd.Series:
    column = metric.time_column
    if metric.time_format == "iso_utc":
        return pd.to_datetime(frame[column], utc=True)
    if metric.time_format == "iso_naive":
        # 无时区墙钟：先按字面解析，再贴上源时区
        naive = pd.to_datetime(frame[column], utc=False)
        if naive.dt.tz is not None:
            naive = naive.dt.tz_convert(None)
        return naive.dt.tz_localize(ZoneInfo(metric.source_timezone)).dt.tz_convert("UTC")
    unit = "s" if metric.time_format == "epoch_s" else "ms"
    numeric = pd.to_numeric(frame[column], errors="raise")
    return pd.to_datetime(numeric, unit=unit, utc=True)


def _apply_missing_policy(
    values: pd.Series, policy: str, series_id: str
) -> tuple[np.ndarray, int]:
    """返回 (处理后的值, 缺失个数)。非数字的非空值一律报错，不当缺失处理。"""
    raw = values
    numeric = pd.to_numeric(raw, errors="coerce")
    invalid = raw.notna() & numeric.isna()
    if invalid.any():
        bad = raw[invalid].iloc[0]
        raise ValueError(f"序列 {series_id} 的值列包含非数字内容: {bad!r}")
    missing = numeric.isna()
    n_missing = int(missing.sum())
    if n_missing and policy == "error":
        raise ValueError(f"序列 {series_id} 有 {n_missing} 个缺失值（missing_policy=error）")
    if policy == "interpolate" and n_missing:
        numeric = numeric.interpolate(limit_direction="both")
    if policy == "drop" and n_missing:
        numeric = numeric.dropna()
    return numeric.to_numpy(dtype=float), n_missing


def load_series(
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

    condition, params = _time_filter(metric, start, end)
    sql = f"SELECT * FROM ({query.replace('$timefilter', condition)}) LIMIT ?"
    with closing(_connect(path)) as conn:
        cursor = conn.execute(sql, (*params, MAX_ROWS + 1))
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError(f"单次查询超过 {MAX_ROWS} 行，请缩小窗口或增加聚合")

    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return []
    if metric.group_column and metric.group_column not in frame.columns:
        raise ValueError(f"查询结果缺少 group_column: {metric.group_column}")
    if metric.value_column not in frame.columns:
        raise ValueError(f"查询结果缺少 value_column: {metric.value_column}")

    frame[metric.time_column] = _parse_time_column(frame, metric)
    frame = frame.sort_values(metric.time_column)

    if metric.group_column:
        parts = list(frame.groupby(metric.group_column, dropna=False))
    else:
        parts = [(None, frame)]

    result: list[SeriesBundle] = []
    for raw_group, part in parts:
        group = None if raw_group is None else _group_label(raw_group)
        series_id = metric.name if group is None else f"{metric.name}:{group}"
        values, n_missing = _apply_missing_policy(
            part[metric.value_column], metric.missing_policy, series_id
        )
        keep = ~part[metric.value_column].isna()
        if metric.missing_policy == "drop":
            timestamps = part[metric.time_column][keep].dt.tz_convert(None)
        else:
            timestamps = part[metric.time_column].dt.tz_convert(None)
        result.append(
            SeriesBundle(
                series_id=series_id,
                values=values,
                timestamps=timestamps.to_numpy(dtype="datetime64[ns]"),
                freq=metric.freq,
                meta={
                    "metric_id": metric.id,
                    "metric_name": metric.name,
                    "group": group,
                    "source_id": metric.source_id,
                    "n_missing": n_missing,
                    "n_valid": len(values),
                    "sufficient": bool(len(values) >= MIN_VALID_POINTS),
                },
            )
        )
    return sorted(result, key=lambda item: item.series_id)
