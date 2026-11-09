"""平台层的时间与频率工具：统一使用 UTC，避免各处混用本地时区。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_FREQ = re.compile(r"^(\d+)(s|min|m|h|d)$")
_FREQ_SECONDS = {"s": 1, "min": 60, "m": 60, "h": 3600, "d": 86400}


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def freq_delta(freq: str) -> timedelta:
    """把频率字符串解析成时间间隔，例如 `5min`、`1h`、`1d`。"""
    match = _FREQ.fullmatch(freq.strip().lower())
    if not match:
        raise ValueError(f"不支持的频率: {freq!r}（示例：5min、1h、1d）")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"频率必须为正数: {freq!r}")
    return timedelta(seconds=amount * _FREQ_SECONDS[match.group(2)])


def infer_freq(timestamps, default: str = "1min") -> str:
    """从时间戳推断实际粒度 → 能被 `freq_delta` 解析的字符串。

    平台不再要求用户填指标频率 —— 数据粒度由 SQL 决定。
    周期识别 / 质量判断需要「点 ↔ 时间」的换算系数，所以从取回的时间戳算：
    取相邻间隔的**中位数**（缺几个点不会把结果带偏）。

    ⚠️ 少于两个点 / 全部同时间戳时无法推断，退回 `default`。
    """
    import numpy as np

    stamps = np.asarray(timestamps)
    if stamps.size < 2:
        return default
    seconds = np.diff(stamps.astype("datetime64[s]").astype("int64"))
    seconds = seconds[seconds > 0]
    if seconds.size == 0:
        return default
    step = int(np.median(seconds))
    if step <= 0:
        return default
    if step % 86400 == 0:
        return f"{step // 86400}d"
    if step % 3600 == 0:
        return f"{step // 3600}h"
    if step % 60 == 0:
        return f"{step // 60}min"
    return f"{step}s"
