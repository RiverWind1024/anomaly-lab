"""数据能力探测 —— 这个指标会让哪些算法失效。

⚠️ 只**报告**，不修数据。和 lab 的体检一样：
   看到的就是检测器实际会拿到的，不做二次清洗。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from anomaly_lab.detectors.scale import numeric_floor, robust_scale

MIN_NONZERO_SAMPLES = 30    # 非零样本少于它 → 幅度估不准


@dataclass(frozen=True)
class CapabilityWarning:
    detector: str
    reason: str


@dataclass(frozen=True)
class Capability:
    n: int
    zero_ratio: float
    n_nonzero: int
    looks_like_counts: bool
    scale_probe: dict[str, float]
    verdict: str                      # ok / unsuitable / undetermined
    warnings: list[CapabilityWarning] = field(default_factory=list)
    message: str = ""


def probe(values: np.ndarray) -> Capability:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = int(v.size)
    if n == 0:
        return Capability(0, 0.0, 0, False, {}, "undetermined", [], "没有有效数据")

    nonzero = v != 0
    n_nonzero = int(nonzero.sum())
    zero_ratio = 1.0 - n_nonzero / n

    # ⚠️ 复用 scale.py 的候选值，别再抄一份 IQR/MAD/std ——
    #    两份同源实现迟早会因为一处改动而给出不同的诊断结论。
    est = robust_scale(v)
    probe_scales = dict(est.probe)
    floor = numeric_floor(v)
    looks_like_counts = bool(
        n_nonzero > 0
        and np.all(v >= 0)
        and np.all(np.equal(np.mod(v, 1), 0))
        and n_nonzero < n
    )

    # ⚠️ `none` 意味着所有候选都低于浮点噪声 —— 不是「没算出尺度」，是「没有可分辨的变化」。
    if est.source == "none":
        return Capability(
            n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
            "undetermined", [], "整段没有可分辨的变化（或全为 0），无法判定",
        )

    warnings: list[CapabilityWarning] = []
    # ⚠️ 判据用**实际算出来的尺度**，不用百分比近似 ——
    #    恰好 75% 零时 q75 会落在非零区，IQR > 0，百分比阈值会误报；
    #    恰好 50% 零时 median 也可能落在非零值上，MAD 同样 > 0。
    if probe_scales["iqr"] <= floor:
        warnings.append(
            CapabilityWarning(
                "iqr",
                f"IQR = {probe_scales['iqr']:.3g}（零值占 {zero_ratio:.1%}），分母为 0，会退回标准差",
            )
        )
    if probe_scales["mad"] <= floor:
        warnings.append(
            CapabilityWarning(
                "mad",
                f"MAD = {probe_scales['mad']:.3g}（零值占 {zero_ratio:.1%}），比 IQR 更早失效",
            )
        )
    if n_nonzero < MIN_NONZERO_SAMPLES:
        warnings.append(
            CapabilityWarning(
                "zero_inflated_iqr",
                f"非零点只有 {n_nonzero} 个（< {MIN_NONZERO_SAMPLES}），幅度估不准",
            )
        )
    if looks_like_counts:
        warnings.append(
            CapabilityWarning("zscore", "计数型数据近似泊松，用标准差标准化会失真")
        )

    if not warnings:
        return Capability(
            n, zero_ratio, n_nonzero, looks_like_counts, probe_scales, "ok", [], ""
        )
    return Capability(
        n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
        "unsuitable", warnings, "；".join(w.reason for w in warnings),
    )
