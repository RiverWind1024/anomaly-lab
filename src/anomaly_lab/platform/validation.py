"""平台层输入校验：SQL 标识符、只读查询、阈值与频率。

这些校验是安全边界的一部分：用户提供的 SQL 只能读取，不能写入。
"""

from __future__ import annotations

import re

import numpy as np

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)
_LITERAL = re.compile(r"'(?:''|[^'])*'")
_TIME_FORMATS = {"iso_utc", "iso_naive", "epoch_s", "epoch_ms"}
_MISSING_POLICIES = {"drop", "interpolate", "error"}
SUPPORTED_SOURCE_KINDS = ("sqlite", "http")


def validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} 必须是合法 SQL 标识符：{value!r}")


def validate_readonly_sql(sql: str) -> str:
    """校验只读查询，返回去掉尾分号的查询文本。

    ⚠️ **不要求** `$timefilter` —— 那是指标 SQL 的要求，
       浏览用的 SQL 应该是自由的。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("查询不能为空")
    text = sql.strip().rstrip(";").strip()
    if not text.lower().startswith(("select", "with")):
        raise ValueError("查询必须以 SELECT 或 WITH 开头")
    if ";" in text:
        raise ValueError("查询只允许单条语句")
    clean = _LITERAL.sub("''", text)
    if _FORBIDDEN.search(clean):
        raise ValueError("查询包含不允许的写操作关键字")
    return text


def validate_query(query: str) -> str:
    """校验指标查询：只读 + 必须恰好一个 `$timefilter`。

    ⚠️ 语义与拆分前**完全一致** —— 现有调用方零改动。
    """
    text = validate_readonly_sql(query)
    if text.count("$timefilter") != 1:
        raise ValueError("查询必须且只能包含一个 $timefilter")
    return text


def validate_time_format(value: str) -> str:
    if value not in _TIME_FORMATS:
        raise ValueError(
            f"不支持的 time_format: {value!r}（可选 {sorted(_TIME_FORMATS)}；"
            "iso_utc=带时区或UTC的ISO时间，iso_naive=无时区墙钟时间）"
        )
    return value


def validate_missing_policy(value: str) -> str:
    if value not in _MISSING_POLICIES:
        raise ValueError(
            f"不支持的 missing_policy: {value!r}（可选 {sorted(_MISSING_POLICIES)}）"
        )
    return value


def validate_timezone(value: str) -> str:
    """校验 IANA 时区名；SQLite 自身不认识时区，所以必须显式声明。"""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValueError(f"无效的时区: {value!r}（需 IANA 名称，如 UTC、Asia/Shanghai）") from exc
    return value


def validate_thresholds(alert: float, critical: float) -> None:
    if not np.isfinite(alert) or not np.isfinite(critical):
        raise ValueError("阈值必须是有限数字")
    if critical <= alert:
        raise ValueError("critical_threshold 必须大于 alert_threshold")


def validate_name(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 不能为空")
    return value.strip()


def validate_window_points(value: int) -> int:
    if value < 10:
        raise ValueError("window_points 至少为 10")
    if value > 100_000:
        raise ValueError("window_points 不能超过 100000")
    return int(value)


def validate_interval_seconds(value: int) -> int:
    if value < 10:
        raise ValueError("interval_seconds 至少为 10 秒")
    return int(value)


def validate_kind(value: str) -> str:
    """数据源类型。"""
    if value not in SUPPORTED_SOURCE_KINDS:
        raise ValueError(
            f"不支持的数据源类型: {value!r}（可选 {list(SUPPORTED_SOURCE_KINDS)}）"
        )
    return value


def validate_http_config(config: dict) -> dict:
    """HTTP 数据源的配置。

    ⚠️ 空的 config 是允许的（先建后配）；非空时必须有 url。
    ⚠️ 跨类型切换（sqlite → http）需要**同时**提供 url ——
       否则切过去就是一个立刻不可用的源。
    """
    if isinstance(config, dict):
        if not config:
            return config
        url = config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("HTTP 数据源必须配置 url")
        method = str(config.get("method", "GET")).upper()
        if method not in {"GET", "POST"}:
            raise ValueError(f"不支持的 method: {method}（可选 GET / POST）")
        fmt = str(config.get("format", "json"))
        if fmt not in {"json", "csv", "jsonl"}:
            raise ValueError(f"不支持的 format: {fmt}（可选 json / csv / jsonl）")
        timeout = config.get("timeout_seconds", 30)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout_seconds 必须是正数")
        return config
    # ⚠️ 抛 ValueError 而不是 TypeError —— 路由层按 ValueError 返回 400
    raise ValueError("HTTP 数据源的 config 必须是对象")
