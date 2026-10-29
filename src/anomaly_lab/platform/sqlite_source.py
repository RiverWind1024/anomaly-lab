"""SQLite 数据源：只读执行带 $timefilter 的查询，并按 group by 拆成独立序列。

拆分放在加载层：检测器永远只面对「一条序列」，与用户想法一致。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.validation import validate_identifier, validate_query

MAX_ROWS = 100_000


def _connect(path: Path) -> sqlite3.Connection:
    """以只读模式打开，避免用户查询意外写入源库。"""
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _time_value(value: datetime, time_format: str):
    if time_format == "iso":
        return value.astimezone(UTC).isoformat()
    stamp = value.timestamp()
    if time_format == "epoch_s":
        return int(stamp)
    if time_format == "epoch_ms":
        return int(stamp * 1000)
    raise ValueError(f"不支持的 time_format: {time_format}")


def _group_label(value: object) -> str:
    if value is None:
        return "null"
    text = str(value)
    return text if text else "null"


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

    clause = f'"{metric.time_column}" >= ? AND "{metric.time_column}" < ?'
    sql = f"SELECT * FROM ({query.replace('$timefilter', clause)}) LIMIT ?"
    params = (
        _time_value(start, metric.time_format),
        _time_value(end, metric.time_format),
        MAX_ROWS + 1,
    )
    with _connect(path) as conn:
        cursor = conn.execute(sql, params)
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

    if metric.time_format == "iso":
        frame[metric.time_column] = pd.to_datetime(frame[metric.time_column], utc=True)
    elif metric.time_format in {"epoch_s", "epoch_ms"}:
        unit = "s" if metric.time_format == "epoch_s" else "ms"
        numeric = pd.to_numeric(frame[metric.time_column], errors="raise")
        frame[metric.time_column] = pd.to_datetime(numeric, unit=unit, utc=True)
    else:
        raise ValueError(f"不支持的 time_format: {metric.time_format}")
    frame = frame.sort_values(metric.time_column)

    if metric.group_column:
        grouped = frame.groupby(metric.group_column, dropna=False)
        parts = [(key, part) for key, part in grouped]
    else:
        parts = [(None, frame)]

    result: list[SeriesBundle] = []
    for raw_group, part in parts:
        values = pd.to_numeric(part[metric.value_column], errors="raise").to_numpy(dtype=float)
        timestamps = (
            part[metric.time_column].dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
        )
        group = None if raw_group is None else _group_label(raw_group)
        series_id = metric.name if group is None else f"{metric.name}:{group}"
        result.append(
            SeriesBundle(
                series_id=series_id,
                values=values,
                timestamps=timestamps,
                freq=metric.freq,
                meta={
                    "metric_id": metric.id,
                    "metric_name": metric.name,
                    "group": group,
                    "source_id": metric.source_id,
                },
            )
        )
    return sorted(result, key=lambda item: item.series_id)
