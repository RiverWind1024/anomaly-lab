"""数据浏览端点：在数据源上执行一段只读 SQL，返回列结构与前 N 行。

⚠️ 单独一个文件 —— `platform_routes.py` 已经 1000+ 行了。
⚠️ 只读校验是**关键字黑名单**，绕得过去 —— 对 HTTP 源，
   真正的安全边界是**远端账号的权限**（见 `sources/http_sql.py`）。
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from anomaly_lab.platform.sources import get_connector
from anomaly_lab.platform.sources.base import TimeContext, parse_time_column, sql_literal
from anomaly_lab.platform.sources.http_sql import ConfigError
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.validation import validate_readonly_sql, validate_timezone

TimeFormat = Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]

#: 时间边界缺省时的极宽窗口 —— 「不限时间」比「报参数缺失」友好。
_MIN_TIME = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_TIME = datetime(2100, 1, 1, tzinfo=UTC)


class SourceQueryIn(BaseModel):
    """数据浏览器的一次查询。"""

    sql: str
    start: str | None = None
    end: str | None = None
    limit: int | None = 100
    # ⚠️ 仅当 SQL 含 $timefilter 时需要 —— 平台才知道替换成什么时间条件
    time_column: str | None = None
    time_format: TimeFormat | None = None
    source_timezone: str | None = None


def _parse_boundary(value: str | None, default: datetime) -> datetime:
    """解析时间边界；缺省时用一个极宽的默认值（不限制）。

    ⚠️ `fromisoformat` 自 3.11 起就能吃 `Z` 后缀 —— 不用再手工替换成 `+00:00`。
    """
    if not value:
        return default
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _column_type(dtype) -> str:
    """列类型（给前端做推断提示）。

    ⚠️ 按**位置**取 dtype，不按列名取 `frame[name]` ——
       重名列（`SELECT ts, ts FROM t`）取出来是 DataFrame，会直接炸。
    """
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(dtype):
        return "REAL"
    return "TEXT"


def _json_safe(value):
    """把 numpy 标量转成能 JSON 序列化的 Python 值。

    ⚠️ NaN / NaT / NA 一律转成 None —— JSON 没有 NaN，
       Starlette 的 JSONResponse 用 allow_nan=False 序列化，留着 NaN 会直接 500。
    """
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _replace_boundary(sql: str, token: str, literal: str) -> str:
    """把 `{start}` / `{end}` 占位符换成时间字面量。

    ⚠️ 两种写法都认：`{start}` 与 `'{start}'` ——
       用户手写 SQL 时很可能自己加了引号，而字面量**自带**引号，
       再套一层就成了 `''2026-...''`，SQL 直接语法错。
    """
    return sql.replace(f"'{token}'", literal).replace(token, literal)


def _apply_time_placeholders(sql: str, payload: SourceQueryIn, connector) -> tuple[str, tuple]:
    """替换浏览 SQL 里的时间占位符。

    - `$timefilter` → 由**连接器**渲染的时间条件（需要 time_column）
    - `{start}` / `{end}` → 共享的字面量（用户自己写列名）

    ⚠️ 返回 `(sql, params)` —— SQLite 的条件带 `?` 绑定参数，
       丢掉 params 会让执行抛「Incorrect number of bindings supplied」。
    """
    fmt = payload.time_format or "iso_utc"
    tz = payload.source_timezone or "UTC"
    # ⚠️ 时区要先校验 —— 否则 ZoneInfo 抛的是 KeyError，
    #    会被当成「执行失败」报 502，其实是用户填错了参数（该报 400）。
    validate_timezone(tz)
    params: tuple = ()

    if "$timefilter" in sql:
        if not payload.time_column:
            # ⚠️ 消息要**可操作** —— 光说「需要指定时间列」，
            #    用户不知道自己下一步该干什么（他正是靠这条 SQL 才知道有哪些列的）。
            #    告诉他绕法：先去掉 $timefilter 跑一次看列，再把时间列填回来。
            raise ValueError(
                "使用 $timefilter 需要指定时间列（time_column）："
                "先去掉 $timefilter 跑一次看结果里有哪些列，"
                "再把时间列名填进「时间列」（或把某一列指派为「时间列」）"
            )
        condition, params = connector.build_time_condition(
            TimeContext(
                column=payload.time_column,
                fmt=fmt,
                timezone=tz,
                start=_parse_boundary(payload.start, _MIN_TIME),
                end=_parse_boundary(payload.end, _MAX_TIME),
            )
        )
        sql = sql.replace("$timefilter", condition)

    if "{start}" in sql or "{end}" in sql:
        sql = _replace_boundary(
            sql,
            "{start}",
            sql_literal(_parse_boundary(payload.start, _MIN_TIME), fmt, tz),
        )
        sql = _replace_boundary(
            sql,
            "{end}",
            sql_literal(_parse_boundary(payload.end, _MAX_TIME), fmt, tz),
        )
    return sql, params


def build_source_query_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/platform/sources/{source_id}/query")
    def query_source(source_id: int, payload: SourceQueryIn) -> dict:
        """在数据源上执行一段只读 SQL，返回列结构与前 N 行。

        ⚠️ 这是**浏览**，不落库、不建指标 —— 只是让用户在定指标前
           先看到「查出来到底是什么结构」。
        """
        store = get_store()
        try:
            source = store.get_source_raw(source_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            sql = validate_readonly_sql(payload.sql)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            connector = get_connector(source, get_data_root())
        except ValueError as exc:
            # ⚠️ 库里 kind 被改成非法值 —— 那是**配置错**，该报 400
            #    （不在 try 里的话会变成 500，看起来像平台挂了）
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # ⚠️ 时间条件的渲染交给**连接器** —— 浏览与指标运行时必须一致，
        #    否则「预览看到的」≠「跑出来的」。
        try:
            sql, params = _apply_time_placeholders(sql, payload, connector)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        limit = payload.limit if payload.limit and payload.limit > 0 else 100
        started = time.perf_counter()
        try:
            # ⚠️ params 必须一起传 —— SQLite 的时间条件带 `?` 绑定参数
            # ⚠️ limit 必须**下推**到 SQL —— 否则整个结果集会被拉进内存
            #    （`SELECT * FROM huge_table` 打远端，全量过网络 + 全量进内存）。
            #    多取一行用来判断「还有更多」。
            frame = connector.execute_sql(sql, params=params, limit=limit + 1)
        except ConfigError as exc:
            # ⚠️ 配置不一致（body 与 config 的 format 对不上）—— 那是**配置错**，
            #    该报 400；远端解析失败仍然是 502。
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except sqlite3.Error as exc:
            # ⚠️ 本地 SQL 写错了（表不存在、语法错…）—— 那是**用户的错**，
            #    该报 400 让界面直接显示，不是 502（那是「远端挂了」的意思）
            raise HTTPException(status_code=400, detail=f"SQL 执行失败: {exc}") from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"执行失败: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # ⚠️ `total` 是**本次取到的行数**（≤ limit），不是结果集的真实总行数 ——
        #    limit 已下推，平台根本没看到更多的行。
        truncated = len(frame) > limit
        rows = frame.head(limit)

        # ⚠️ `time_column` 现在是**两用**的：
        #    ① SQL 含 `$timefilter` 时 —— 时间条件渲染到它上面
        #    ② 不管含不含 —— 把这一列解析成时间轴坐标，给前端的时序图用
        #    ② 用的是**与指标运行时同一份**解析逻辑（`parse_time_column`），
        #    否则浏览里画的图与真正跑出来的对不上（iso_naive 的源时区、
        #    epoch 毫秒/秒最容易错）。
        time_values = _parse_time_values(frame, rows, payload)

        return {
            "columns": [
                {"name": str(name), "type": _column_type(dtype)}
                for name, dtype in zip(frame.columns, frame.dtypes)
            ],
            "rows": [
                [_json_safe(value) for value in row]
                for row in rows.itertuples(index=False)
            ],
            "time_values": time_values,
            "total": len(rows),
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
        }

    return router


def _parse_time_values(
    frame: pd.DataFrame, rows: pd.DataFrame, payload: SourceQueryIn
) -> list[int | None] | None:
    """把时间列解析成 epoch 毫秒（ECharts 时间轴吃毫秒）。

    ⚠️ **返回 None 表示「没有时间列」** —— 与「有但全解析不出来」
       区分开：前者不画图，后者画一条空的轴。

    ⚠️ 解析不出来的行给 `None`（断点）—— **绝不画到 1970 年**。
       那样看着像「数据都在 1970 年」，比空白更误导。
    """
    column = payload.time_column
    if not column or column not in frame.columns:
        return None
    fmt = payload.time_format or "iso_utc"
    tz = payload.source_timezone or "UTC"
    # ⚠️ 时区要先校验 —— 否则 ZoneInfo 抛 KeyError，
    #    会被当成「查询失败」报 502，其实是参数填错了。
    validate_timezone(tz)
    parsed = parse_time_column(frame, column, fmt, tz, coerce=True)
    return [
        None if pd.isna(stamp) else int(stamp.value // 1_000_000)
        for stamp in parsed.head(len(rows))
    ]
