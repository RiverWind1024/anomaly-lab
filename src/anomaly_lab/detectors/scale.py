"""稳健尺度估计 —— 所有「|x - center| / scale」型检测器共用。

⚠️ 为什么需要降级链：
    IQR / MAD 在零膨胀或全常数序列上会算出 0，
    而 score = 偏差 / 0 的 NaN 一旦被写成 0，
    「算不出来」就被翻译成了「一切正常」—— 这是静默失效。

⚠️ 降级顺序是有依据的，不是随便排的：
    - 零值 >75%：IQR = q75 − q25 = 0
    - 零值 >50%：MAD = median(|x − med|) = 0（比 IQR 更早失效）
    - std 在零膨胀数据上仍有值（10% 非零、幅度 25 → std ≈ 7.5）
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

_ORDER = ("iqr", "mad", "std")


@dataclass(frozen=True)
class ScaleEstimate:
    value: float
    #: iqr / mad / std / none
    source: str
    #: 每个候选的原始值（诊断用）
    probe: dict[str, float] = field(default_factory=dict)


def _candidates(values: np.ndarray) -> dict[str, float]:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return {"iqr": 0.0, "mad": 0.0, "std": 0.0}
    q1, q3 = np.percentile(v, [25, 75])
    med = np.median(v)
    return {
        "iqr": float(q3 - q1),
        "mad": float(np.median(np.abs(v - med)) * 1.4826),
        "std": float(np.std(v)),
    }


def _ordered(prefer: str) -> list[str]:
    if prefer not in _ORDER:
        raise ValueError(f"未知尺度: {prefer}")
    return [prefer, *(name for name in _ORDER if name != prefer)]


def numeric_floor(values: np.ndarray) -> float:
    """低于这个值的尺度差异是浮点误差，不是信号。

    ⚠️ 常数序列经过 polyfit / STL 之后残差不是精确的 0，而是 1e-16 量级。
       直接拿它当尺度，会把数值噪声放大成几十倍的分数 —— 常数序列报出一堆假告警。
    """
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return 0.0
    return 1e-12 * max(1.0, float(np.max(np.abs(v))))


def robust_scale(values: np.ndarray, *, prefer: str = "iqr") -> ScaleEstimate:
    """整段序列的尺度：按顺序挑第一个大于数值噪声的候选。"""
    candidates = _candidates(values)
    floor = numeric_floor(values)
    for name in _ordered(prefer):
        if candidates[name] > floor:
            return ScaleEstimate(candidates[name], name, candidates)
    return ScaleEstimate(0.0, "none", candidates)


def pick_scale(
    *, prefer: str, candidates: dict[str, np.ndarray], floor: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """逐点挑尺度（滚动检测器用）。

    ⚠️ **只考虑 candidates 里真的给了的候选** ——
       ZScore 只提供 std，不能因为链里有 iqr 就 KeyError。

    返回 `(scale, source)`；`source` 是 object 数组，值为候选名或 "none"。
    """
    names = [name for name in _ordered(prefer) if name in candidates]
    arrays = {name: np.asarray(candidates[name], dtype=float) for name in names}
    if not arrays:
        raise ValueError("candidates 不能为空")

    n = max(arr.size for arr in arrays.values())
    scale = np.zeros(n, dtype=float)
    source = np.full(n, "none", dtype=object)
    # ⚠️ 必须按**优先级从高到低**写，且只在还是 none 的位置写。
    #    写成 reversed() 会让最低优先级的 std 永远赢 —— 正常数据的分数会全变。
    for name in names:
        arr = np.broadcast_to(arrays[name], (n,))
        use = np.isfinite(arr) & (arr > floor) & (source == "none")
        scale[use] = arr[use]
        source[use] = name
    return scale, source


def majority_source(source: np.ndarray) -> str:
    """逐点来源 → 一个代表值（忽略 none）。"""
    values = [item for item in source if item != "none"]
    if not values:
        return "none"
    return Counter(values).most_common(1)[0][0]
