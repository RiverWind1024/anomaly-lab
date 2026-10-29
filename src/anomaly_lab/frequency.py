"""采样频率解析：把 `5min` / `1h` 这类频率字符串解析成秒。

放在顶层是因为检测器与平台层都要用——检测器不该反向依赖平台层。
"""

from __future__ import annotations

import re

_FREQ = re.compile(r"^(\d+)(s|min|m|h|d)$")
_FREQ_SECONDS = {"s": 1, "min": 60, "m": 60, "h": 3600, "d": 86400}


def freq_seconds(freq: str) -> float:
    """把频率字符串解析成秒间隔，例如 `5min` → 300.0。"""
    match = _FREQ.fullmatch(freq.strip().lower())
    if not match:
        raise ValueError(f"不支持的频率: {freq!r}（示例：5min、1h、1d）")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError(f"频率必须为正数: {freq!r}")
    return float(amount * _FREQ_SECONDS[match.group(2)])
