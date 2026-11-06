"""数据能力探测 —— 这个指标会让哪些算法失效。

⚠️ 只**报告**，不修数据。和 lab 的体检一样：
   看到的就是检测器实际会拿到的，不做二次清洗。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter1d

from anomaly_lab.detectors.period import estimate_period
from anomaly_lab.detectors.scale import numeric_floor, robust_scale
from anomaly_lab.detectors.zero_inflated import MIN_NONZERO_SAMPLES

#: 线性去趋势后残差「仍有结构」的门槛 —— 用滑动平均能解释的残差方差比例衡量。
#:
#: 实测（120 条合成序列）：白噪声 / 纯线性趋势 ≈ 0.07–0.17，
#: 周期型 ≈ 0.66–0.89，阶梯型 ≈ 0.34–0.86。
#: 0.30 落在两者之间：不会把线性趋势误判成非线性，也不会漏掉周期 / 阶梯。
DETRENDED_STRUCTURE_THRESHOLD = 0.30


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
    #: 泊松 / 事件计数类算法是否适用（非负整数即可，允许全非零）。
    #: 前端在选中 poisson_count / event_count 时用它提示「数据不是计数」。
    #: ⚠️ 与 `looks_like_counts` 不同：后者要求「含零」（稀疏计数），
    #:    只用于 zscore 的「近似泊松」警告。
    count_ready: bool = False
    warnings: list[CapabilityWarning] = field(default_factory=list)
    message: str = ""
    #: 有没有**可信**周期（`estimate_period` 认为可用）——
    #: 只用于「形态 × 算法」适配性，不参与 verdict。
    has_period: bool = False
    #: 线性去趋势后残差的结构强度（0–1）——
    #: 接近 1 说明残差几乎全是平滑成分（周期 / 阶梯 / 非线性趋势）。
    detrended_structure: float = 0.0
    #: 「算法 × 形态」不适配的说明。
    #:
    #: ⚠️ 与 `warnings` **分开**：这些算法（seasonal / stl_residual /
    #:    trend_residual_iqr / theil_sen）对数据形态有前提，数据本身没问题，
    #:    只是这类算法不适用。放进 `warnings` 会让几乎所有非周期序列
    #:    都被判成 `unsuitable`，verdict 就失去意义了。
    shape_warnings: list[CapabilityWarning] = field(default_factory=list)


def _detrended_structure(values: np.ndarray) -> float:
    """线性去趋势后，残差里还有多少「平滑结构」。

    1 = 残差几乎全是平滑成分（周期 / 阶梯 / 非线性趋势）；
    0 = 残差接近白噪声（线性趋势 + 噪声）。
    """
    n = int(values.size)
    if n < 10:
        return 0.0
    t = np.arange(n, dtype=float)
    residual = values - np.polyval(np.polyfit(t, values, 1), t)
    total = float(np.var(residual))
    if total <= 0.0:
        return 0.0
    # 窗口取序列长度的 2%，至少 5 点：足够跨过噪声，又短于任何真实周期。
    window = max(5, n // 50)
    if window % 2 == 0:
        window += 1
    smooth = uniform_filter1d(residual, size=window, mode="nearest")
    return float(np.clip(1.0 - np.var(residual - smooth) / total, 0.0, 1.0))


def _shape_warnings(
    values: np.ndarray, freq: str | None
) -> tuple[bool, float, list[CapabilityWarning]]:
    """形态与算法的适配性 —— 返回 (有周期, 残差结构, 警告)。"""
    period = estimate_period(values, freq or "1min")
    has_period = bool(period.usable)
    structure = _detrended_structure(values)

    warnings: list[CapabilityWarning] = []
    if not has_period:
        warnings.append(
            CapabilityWarning(
                "seasonal",
                "没有可识别的周期，相位分组会退化成全局稳健统计（与 IQR 类似）",
            )
        )
        warnings.append(
            CapabilityWarning(
                "stl_residual",
                "没有可信周期，STL 会估出伪周期，残差里混入季节项",
            )
        )
    if structure >= DETRENDED_STRUCTURE_THRESHOLD:
        detail = (
            f"主周期约 {period.period_points} 点，周期波动会被当成趋势残差"
            if has_period
            else f"去线性趋势后残差仍有结构（平滑成分解释 {structure:.0%} 的残差方差）"
        )
        warnings.append(
            CapabilityWarning("trend_residual_iqr", f"{detail}，趋势线拟合不完整")
        )
        warnings.append(
            CapabilityWarning("theil_sen", f"{detail}，趋势线拟合不完整")
        )
    return has_period, structure, warnings


def probe(values: np.ndarray, freq: str | None = None) -> Capability:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = int(v.size)
    if n == 0:
        return Capability(
            0, 0.0, 0, False, {}, "undetermined", count_ready=False,
            message="没有有效数据",
        )

    nonzero = v != 0
    n_nonzero = int(nonzero.sum())
    zero_ratio = 1.0 - n_nonzero / n

    # ⚠️ 复用 scale.py 的候选值，别再抄一份 IQR/MAD/std ——
    #    两份同源实现迟早会因为一处改动而给出不同的诊断结论。
    est = robust_scale(v)
    probe_scales = dict(est.probe)
    floor = numeric_floor(v)
    #: 非负整数 —— 泊松类算法的输入要求
    nonneg_int = bool(
        n_nonzero > 0
        and np.all(v >= 0)
        and np.all(np.equal(np.mod(v, 1), 0))
    )
    #: 稀疏计数（含零）—— zscore 的「近似泊松」警告用这个
    looks_like_counts = bool(nonneg_int and n_nonzero < n)
    #: 泊松类算法可用 —— 只要是非负整数（含全非零）
    count_ready = nonneg_int

    # ⚠️ `none` 意味着所有候选都低于浮点噪声 —— 不是「没算出尺度」，是「没有可分辨的变化」。
    if est.source == "none":
        return Capability(
            n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
            "undetermined", count_ready=count_ready,
            message="整段没有可分辨的变化（或全为 0），无法判定",
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

    has_period, structure, shape_warnings = _shape_warnings(v, freq)

    if not warnings:
        return Capability(
            n, zero_ratio, n_nonzero, looks_like_counts, probe_scales, "ok",
            count_ready=count_ready,
            has_period=has_period,
            detrended_structure=round(structure, 4),
            shape_warnings=shape_warnings,
        )
    return Capability(
        n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
        "unsuitable", count_ready=count_ready, warnings=warnings,
        message="；".join(w.reason for w in warnings),
        has_period=has_period,
        detrended_structure=round(structure, 4),
        shape_warnings=shape_warnings,
    )
