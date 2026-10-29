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
