"""Web 层的 JSON 序列化工具：把 numpy 数值安全地变成 JSON 能接受的值。"""

from __future__ import annotations

import numpy as np


def clean_floats(values: np.ndarray) -> list[float | None]:
    """把 NaN/Inf 转成 None，避免 JSON 里出现非法值。

    前端拿到 null 会把折线断开 —— 不会画出「NaN」这种假数据。
    """
    result: list[float | None] = []
    for value in np.asarray(values, dtype=float):
        result.append(float(value) if np.isfinite(value) else None)
    return result
