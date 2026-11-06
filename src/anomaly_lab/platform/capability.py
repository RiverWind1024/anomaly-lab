"""数据能力探测 —— 这个指标会让哪些算法失效。

⚠️ 只**报告**，不修数据。和 lab 的体检一样：
   看到的就是检测器实际会拿到的，不做二次清洗。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from anomaly_lab.detectors.scale import robust_scale

IQR_MIN_NONZERO = 0.25      # 非零比例低于它 → IQR=0
MAD_MIN_NONZERO = 0.50      # 非零比例低于它 → MAD=0
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
    looks_like_counts = bool(
        n_nonzero > 0
        and np.all(v >= 0)
        and np.all(np.equal(np.mod(v, 1), 0))
        and n_nonzero < n
    )

    if n_nonzero == 0 or all(x == 0 for x in probe_scales.values()):
        return Capability(
            n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
            "undetermined", [], "整段没有变化（或全为 0），无法判定",
        )

    warnings: list[CapabilityWarning] = []
    if zero_ratio >= 1 - IQR_MIN_NONZERO:
        warnings.append(
            CapabilityWarning(
                "iqr",
                f"零值占 {zero_ratio:.1%}，Q3−Q1 = 0，会退回标准差（对零膨胀不稳健）",
            )
        )
    if zero_ratio >= 1 - MAD_MIN_NONZERO:
        warnings.append(
            CapabilityWarning(
                "mad", f"零值占 {zero_ratio:.1%}，MAD = 0（比 IQR 更早退回标准差）"
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
