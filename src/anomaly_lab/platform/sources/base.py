"""连接器层：统一的「SQL → DataFrame」入口，与方言无关的后处理。

每个连接器只负责「怎么把一段 SQL 变成一张表」；时间解析、排序、
group by 拆分、缺失策略在这里统一处理 —— 它们只依赖 pandas，不依赖方言。

⚠️ 拆分的理由：原 `sqlite_source.load_series` 把「取数」与「后处理」混在一个
   函数里，换一种数据源就要复制一遍后处理逻辑。切分点在
   `pd.DataFrame(rows, columns=columns)` 之后。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric

MAX_ROWS = 100_000
MIN_VALID_POINTS = 10


@dataclass(frozen=True)
class TimeContext:
    """替换 `$timefilter` 所需的上下文。"""

    column: str
    fmt: str
    timezone: str
    start: datetime
    end: datetime


def _group_label(value: object) -> str:
    """分组值的显示形式：None → "null"，空串 → "null"。"""
    text = str(value)
    return text if text else "null"


def _wall_clock(value: datetime, timezone_name: str) -> str:
    """把 UTC 时刻转成源库时区的墙钟字符串（不带时区后缀）。"""
    local = value.astimezone(ZoneInfo(timezone_name))
    return local.replace(tzinfo=None).isoformat(sep=" ")


def _parse_time_column(frame: pd.DataFrame, metric: Metric) -> pd.Series:
    """按 `time_format` 把时间列解析成 UTC 时间戳。

    ⚠️ 时间语义不猜 —— 存储形式由 `time_format` 声明，
       无时区时间戳按 `source_timezone` 解释（对应 CloudWatch 的 MetricTimezone）。
    """
    column = metric.time_column
    if metric.time_format == "iso_utc":
        return pd.to_datetime(frame[column], utc=True)
    if metric.time_format == "iso_naive":
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


def time_literal(value: datetime, fmt: str, timezone_name: str) -> str:
    """把时刻渲染成**裸值**（不含引号）。

    ⚠️ `iso_utc` 用 **T 分隔 + `+00:00` 偏移**，与平台的 `to_iso()` 完全一致 ——
       同一偏移、同一格式下**字符串字典序 == 时间序**，边界比较才正确。
       用 `Z` 会让 `'+'`(0x2B) < `'Z'`(0x5A) → 边界行被误判。
    """
    if fmt == "iso_utc":
        return value.astimezone(UTC).isoformat(timespec="seconds")
    if fmt == "iso_naive":
        return (
            value.astimezone(ZoneInfo(timezone_name))
            .replace(tzinfo=None)
            .isoformat(timespec="seconds")
        )
    if fmt == "epoch_s":
        return str(int(value.timestamp()))
    if fmt == "epoch_ms":
        return str(int(value.timestamp() * 1000))
    raise ValueError(f"不支持的 time_format: {fmt}")


def sql_literal(value: datetime, fmt: str, timezone_name: str) -> str:
    """把时刻渲染成**可直接嵌进 SQL 的字面量**（字符串加引号，数字不加）。"""
    text = time_literal(value, fmt, timezone_name)
    if fmt in {"epoch_s", "epoch_ms"}:
        return text
    return f"'{text}'"


def time_filter_parts(
    column: str, fmt: str, timezone_name: str, start: datetime, end: datetime
) -> tuple[str, tuple]:
    """**SQLite 方言**的时间条件（参数绑定）。

    ⚠️ 只对 SQLite 有效 —— `julianday()` 是 SQLite 专有函数。
       其它方言由各自的连接器渲染（见 `HttpSqlConnector.build_time_condition`）。
    """
    quoted = f'"{column}"'
    if fmt in {"iso_utc", "iso_naive"}:
        if fmt == "iso_utc":
            low = start.astimezone(UTC).isoformat(sep=" ")
            high = end.astimezone(UTC).isoformat(sep=" ")
        else:
            # 源库存的是源时区的墙钟时间，边界也要换算成墙钟再比较
            low = _wall_clock(start, timezone_name)
            high = _wall_clock(end, timezone_name)
        # julianday 让 SQLite 按时间语义比较，避开 ISO 字符串字典序的坑
        condition = (
            f"julianday({quoted}) >= julianday(?) AND julianday({quoted}) < julianday(?)"
        )
        return condition, (low, high)
    if fmt == "epoch_s":
        low, high = int(start.timestamp()), int(end.timestamp())
    elif fmt == "epoch_ms":
        low, high = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    else:
        raise ValueError(f"不支持的 time_format: {fmt}")
    return f"{quoted} >= ? AND {quoted} < ?", (low, high)


def series_from_frame(frame: pd.DataFrame, metric: Metric) -> list[SeriesBundle]:
    """方言无关的后处理：解析时间列 → 排序 → group by 拆序列 → 缺失策略。

    契约：
    - 空表返回 `[]`
    - 缺 `value_column` / `group_column` 列 → `ValueError`
    - 每条序列的 `meta` 含 metric_id / metric_name / group / source_id /
      n_missing / n_valid / sufficient
    - `values` 与 `timestamps` 长度永远一致（`drop` 策略下同步过滤）
    """
    if frame.empty:
        return []
    if metric.value_column not in frame.columns:
        raise ValueError(f"查询结果缺少 value_column: {metric.value_column}")
    if metric.group_column and metric.group_column not in frame.columns:
        raise ValueError(f"查询结果缺少 group_column: {metric.group_column}")

    frame = frame.copy()
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
        # ⚠️ 只有 `drop` 策略过滤时间戳 —— interpolate 策略下值是插值出来的、
        #    点数不变，两边长度必须一致，否则 SeriesBundle 会抛「长度不一致」。
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
