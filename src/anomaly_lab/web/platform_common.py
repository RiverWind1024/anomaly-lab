"""平台 API 的请求模型与 HTTP 通用工具。

从 `platform_routes.py` 拆出来：模型和解析/筛选工具与具体端点无关。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

import numpy as np
from fastapi import HTTPException
from pydantic import BaseModel

from anomaly_lab.web.json_utils import clean_floats

TimeFormat = Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]
MissingPolicy = Literal["drop", "interpolate", "error"]


def _parse_decision(raw: object) -> dict:
    """把 `decision_json` 解析成对象；老数据 / 坏数据一律返回空 dict。

    ⚠️ 绝不能让一条老记录的坏 JSON 把整页打成 500 ——
       决策链是**附加信息**，读不出来就当作「这次没记」。
    """
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class SourceIn(BaseModel):
    name: str
    path: str = ""
    kind: str = "sqlite"
    config: dict | None = None


class SourcePatchIn(BaseModel):
    """数据源更新：**全部可选** —— 只传要改的字段。"""

    name: str | None = None
    path: str | None = None
    kind: str | None = None
    config: dict | None = None


class MetricPatchIn(BaseModel):
    """指标更新：**全部可选** —— 只传要改的字段。"""

    name: str | None = None
    query: str | None = None
    time_column: str | None = None
    value_column: str | None = None
    group_column: str | None = None
    time_format: TimeFormat | None = None
    freq: str | None = None
    source_timezone: str | None = None
    missing_policy: MissingPolicy | None = None


class MetricIn(BaseModel):
    source_id: int
    name: str
    query: str
    time_column: str
    value_column: str
    group_column: str | None = None
    time_format: TimeFormat = "iso_utc"
    freq: str = "5min"
    source_timezone: str = "UTC"
    missing_policy: MissingPolicy = "drop"


class JobIn(BaseModel):
    metric_id: int
    name: str
    detector: str = "auto"
    alert_threshold: float | None = None
    critical_threshold: float | None = None
    window_points: int = 500
    interval_seconds: int = 300
    enabled: bool = True
    alert_rules: list[AlertRuleIn] | None = None
    alert_direction: str | None = None


class AlertRuleIn(BaseModel):
    """一条告警规则。

    两种条件二选一：`multiplier` 是倍数条件（缩放因子），
    `op`+`value` 是绝对值条件（如「值 > 50 记 P1」）。
    """

    level: str
    multiplier: float | None = None
    op: str | None = None
    value: float | None = None


class JobToggleIn(BaseModel):
    """任务配置更新：**全部可选** —— 只传要改的字段。

    ⚠️ `alert_rules` 现在**可以自由编辑**了（之前只读）——
       告警阈值（2.5 / 3.75 那些）本来就该是能调的，
       只让用户在新建任务时填、事后改不了，是把配置锁在了错误的时机。
       改了规则表，后端会把 `alert_threshold` / `critical_threshold`
       **同步**成规则表里的最低/最高档倍数（两边必须一致）。
    """

    name: str | None = None
    metric_id: int | None = None
    enabled: bool | None = None
    detector: str | None = None
    alert_threshold: float | None = None
    critical_threshold: float | None = None
    window_points: int | None = None
    interval_seconds: int | None = None
    alert_rules: list[AlertRuleIn] | None = None
    alert_direction: str | None = None


class FeedbackIn(BaseModel):
    """一条人工反馈：某段时间内检测行为对不对（粒度对齐 CloudWatch）。"""

    job_id: int
    series_id: str
    start_ts: str
    end_ts: str
    kind: Literal["correct", "false_alarm", "missed", "other"]
    note: str = ""
    run_id: int | None = None


class ApplySuggestionIn(BaseModel):
    """应用反馈建议：可同时改告警倍数与检测算法。"""

    multiplier: float
    detector: str | None = None


#: NaN/Inf → None，避免 JSON 里出现非法值（实现见 web/json_utils.py）
_clean = clean_floats


def _not_found(exc: ValueError) -> HTTPException:
    """「资源不存在」→ 404。

    ⚠️ **不要用「消息里有没有『不存在』」来判断** ——
       「不支持的检测器: 不存在的算法」也会命中那个词。
    """
    return HTTPException(status_code=404, detail=str(exc))


def _parse_ts(value: str | None) -> datetime | None:
    """解析 ISO 时间戳；解析不了就返回 None（当作没这个筛选条件）。

    ⚠️ **不能直接拿字符串比较时间** —— 事件的时间戳是 `2026-10-30T07:23:00`，
       浏览器给的可能是 `2026-10-30T07:23:00.000Z`，
       两种格式字典序一比就错了。
    """
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # 没带时区的按 UTC 解释（平台侧的时间一律是 UTC）
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _at_or_after(event_ts: str, moment: datetime) -> bool:
    """事件时间是否在 moment 之后（含）。

    事件时间解析不出来时**保留**该事件 —— 宁可多给一条，
    也不要因为格式问题把用户的告警藏起来。
    """
    parsed = _parse_ts(event_ts)
    if parsed is None:
        return True
    return parsed >= moment


def _at_or_before(event_ts: str, moment: datetime) -> bool:
    parsed = _parse_ts(event_ts)
    if parsed is None:
        return True
    return parsed <= moment


MAX_PREVIEW_POINTS = 2000


def _sample_indices(n: int, max_points: int) -> np.ndarray | None:
    """点数过多时等间隔抽样；返回 None 表示不需要抽样。"""
    if n <= max_points:
        return None
    return np.unique(np.linspace(0, n - 1, max_points).round().astype(int))


