"""P1：多算法对比实验。

⚠️ **无真值**是主场景 —— 所以这里不产出 F1，产出「检出画像 + 取舍」：
   检出量、跨窗稳定性、耗时、倍数敏感性。

⚠️ **倍数敏感性零额外算力** —— 分数只算一次，换一套告警规则表重判等级即可。
   这不是取巧：倍数阈值改的就是「分数超过几倍算异常」，本来就该走同一份分数。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from anomaly_lab.detectors.bands import compute_bands
from anomaly_lab.lab.inspect import Prepared, PreparedWindow, prepare, spec_dict
from anomaly_lab.lab.spec import DataSpec
from anomaly_lab.platform.alerts import (
    SEVERITY_NORMAL,
    AlertRule,
    severity_from_conditions,
)
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DETECTOR_FACTORIES,
    create_detector,
    resolve_detector,
)
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso

#: 倍数敏感性的默认档位 —— 覆盖「宽到很严」的常见区间。
DEFAULT_MULTIPLIERS = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0)

#: 主口径用的倍数（与平台默认告警阈值一致）。
PRIMARY_MULTIPLIER = 2.5


def check_detectors(detectors: list[str]) -> list[str]:
    """校验检测器名。`auto` 单独放行。"""
    for name in detectors:
        if name == AUTO_DETECTOR:
            continue
        if name not in DETECTOR_FACTORIES:
            raise ValueError(
                f"未知的检测器: {name!r}（可选：{AUTO_DETECTOR} 或 {sorted(DETECTOR_FACTORIES)}）"
            )
    return detectors


def _alerts_at(scores: np.ndarray, values: np.ndarray, multiplier: float) -> int:
    """给定倍数下有多少个点被判为异常。

    ⚠️ 用**单档**规则表 —— 「超过 N 倍算异常」是最简单的口径，
       不掺档位逻辑，结果才和用户心里想的「N 倍敏感度」对得上。
    """
    rules = [AlertRule(level="P1", multiplier=float(multiplier))]
    severity = severity_from_conditions(scores, values, rules)
    return int((severity > SEVERITY_NORMAL).sum())


@dataclass
class WindowDetection:
    """一个窗口 × 一个检测器的检测结果。"""

    series_id: str
    window_index: int
    #: 实际使用的算法名（`auto` 会逐窗口解析）。
    detector: str
    requested: str
    metric_class: str | None
    fallback: bool
    rationale: str
    n: int
    n_alerts: int
    alert_ratio: float
    elapsed_ms: float
    #: 倍数 → 该倍数下的检出点数。
    sensitivity: dict[str, int] = field(default_factory=dict)
    #: 数据不足被跳过时的原因。
    skipped: bool = False
    skip_reason: str | None = None


def _detect_window(
    prepared: Prepared,
    item: PreparedWindow,
    requested: str,
    multipliers: tuple[float, ...],
    series_id: str,
) -> WindowDetection:
    """在**一个窗口**上跑一个检测器。"""
    quality = item.quality
    window_index = quality.index

    if not quality.sufficient:
        return WindowDetection(
            series_id=series_id,
            window_index=window_index,
            detector=requested,
            requested=requested,
            metric_class=None,
            fallback=False,
            rationale="",
            n=quality.n,
            n_alerts=0,
            alert_ratio=0.0,
            elapsed_ms=0.0,
            skipped=True,
            skip_reason=quality.insufficient_reason or "数据不足",
        )

    resolution = resolve_detector(requested, item.bundle)
    started = time.perf_counter()
    detector = create_detector(resolution.detector).fit(item.bundle)
    result = detector.detect(item.bundle, threshold=float(detector.default_threshold))
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    scores = np.asarray(result.scores, dtype=float)
    values = np.asarray(item.bundle.values, dtype=float)
    sensitivity = {
        f"{multiplier:.1f}": _alerts_at(scores, values, multiplier)
        for multiplier in multipliers
    }
    primary = f"{PRIMARY_MULTIPLIER:.1f}"
    n_alerts = sensitivity.get(primary, _alerts_at(scores, values, PRIMARY_MULTIPLIER))
    n = len(values)

    return WindowDetection(
        series_id=series_id,
        window_index=window_index,
        detector=resolution.detector,
        requested=requested,
        metric_class=resolution.metric_class,
        fallback=resolution.fallback,
        rationale=resolution.rationale,
        n=n,
        n_alerts=n_alerts,
        alert_ratio=(n_alerts / n) if n else 0.0,
        elapsed_ms=elapsed_ms,
        sensitivity=sensitivity,
    )


def _aggregate(detections: list[WindowDetection]) -> dict[str, Any]:
    """把一个检测器在所有窗口上的结果汇成一张画像。"""
    ran = [item for item in detections if not item.skipped]
    n_points = sum(item.n for item in ran)
    n_alerts = sum(item.n_alerts for item in ran)
    ratios = [item.alert_ratio for item in ran]

    # ⚠️ 稳定性 = 各窗口检出率的**离散度**。
    #    同一算法在有的窗口报 10% 有的报 0%，说明它在跟着数据形态漂 ——
    #    这种算法上线后阈值难调，比平均检出量更能说明问题。
    stability: float | None = None
    if len(ratios) >= 2:
        stability = round(float(np.std(ratios)), 4)
    elif len(ratios) == 1:
        stability = 0.0

    sensitivity: dict[str, int] = {}
    if ran:
        for key in ran[0].sensitivity:
            sensitivity[key] = sum(item.sensitivity.get(key, 0) for item in ran)

    # ⚠️ `auto` 是**逐窗口**解析的 —— 同一批窗口里可能用了好几个算法。
    #    这个分布就是「auto 到底在干什么」的答案，不能只报一个总数。
    resolved_mix: dict[str, int] = {}
    for item in ran:
        resolved_mix[item.detector] = resolved_mix.get(item.detector, 0) + 1

    return {
        "n_windows": len(ran),
        "n_windows_skipped": len(detections) - len(ran),
        "n_points": n_points,
        "n_alerts": n_alerts,
        "alert_ratio": round(n_alerts / n_points, 4) if n_points else 0.0,
        "n_windows_with_alerts": sum(1 for item in ran if item.n_alerts > 0),
        "stability": stability,
        "elapsed_ms": round(sum(item.elapsed_ms for item in ran), 3),
        "sensitivity": sensitivity,
        "resolved_mix": resolved_mix,
    }


def default_detectors(prepared: Prepared) -> list[str]:
    """默认跑哪些算法：`auto` + 形态分类推荐的候选。

    ⚠️ 候选取自**序列级**形态（各窗口投票的多数类）——
       与 auto 自己逐窗口解析的口径不完全一样，但这正是要对比的东西：
       「每窗各选一个」与「全局选一个」哪个更稳。
    """
    names: list[str] = [AUTO_DETECTOR]
    for item in prepared.series:
        classes = [
            window.classification["metric_class"]
            for window in item.windows
            if window.classification
        ]
        if not classes:
            continue
        majority = max(set(classes), key=classes.count)
        for window in item.windows:
            if window.classification and window.classification["metric_class"] == majority:
                for candidate in window.classification["candidates"]:
                    if candidate in DETECTOR_FACTORIES and candidate not in names:
                        names.append(candidate)
                break
    return names


def run_experiment(
    store: PlatformStore,
    data_root: Path,
    spec: DataSpec,
    *,
    detectors: list[str] | None = None,
    multipliers: list[float] | None = None,
) -> dict[str, Any]:
    """在同一批窗口上跑多个检测器，产出对比画像。

    **不落盘** —— 产物全在返回值里。
    """
    prepared = prepare(store, data_root, spec)
    factors = tuple(multipliers) if multipliers else DEFAULT_MULTIPLIERS
    requested = check_detectors(list(detectors) if detectors else default_detectors(prepared))

    results: list[dict[str, Any]] = []
    for name in requested:
        detections: list[WindowDetection] = []
        for item in prepared.series:
            for window in item.windows:
                detections.append(
                    _detect_window(prepared, window, name, factors, item.series.series_id)
                )
        results.append(
            {
                "detector": name,
                "per_window": [
                    {
                        "series_id": item.series_id,
                        "window_index": item.window_index,
                        "detector": item.detector,
                        "requested": item.requested,
                        "metric_class": item.metric_class,
                        "fallback": item.fallback,
                        "rationale": item.rationale,
                        "n": item.n,
                        "n_alerts": item.n_alerts,
                        "alert_ratio": round(item.alert_ratio, 4),
                        "elapsed_ms": round(item.elapsed_ms, 3),
                        "sensitivity": item.sensitivity,
                        "skipped": item.skipped,
                        "skip_reason": item.skip_reason,
                    }
                    for item in detections
                ],
                "aggregate": _aggregate(detections),
            }
        )

    windows = [
        {
            "series_id": item.series.series_id,
            "index": window.quality.index,
            "start": window.quality.start.isoformat(),
            "end": window.quality.end.isoformat(),
            "n": window.quality.n,
            "expected": window.quality.expected,
            "sufficient": window.quality.sufficient,
            "missing_ratio": round(window.quality.missing_ratio, 4),
        }
        for item in prepared.series
        for window in item.windows
    ]

    return {
        # ⚠️ 完整 spec（含 sampling）—— 前端拿它就能原样再发一次请求，
        #    比如拉单个窗口的曲线时不用自己拼。
        "spec": spec_dict(prepared.spec),
        "freq": prepared.freq,
        "window_points": prepared.spec.sampling.window_points,
        "multipliers": [f"{factor:.1f}" for factor in factors],
        "primary_multiplier": f"{PRIMARY_MULTIPLIER:.1f}",
        "windows": windows,
        "results": results,
        "warnings": prepared.warnings,
    }


def _window_detector_detail(
    bundle,
    requested: str,
    width: float,
) -> dict[str, Any]:
    """在**一个窗口**上跑一个检测器，返回画图要的全套数据。

    ⚠️ 告警判定用的是**单档 P1 规则**（`width` 倍）—— 与 `_alerts_at` 同一口径，
       所以图上标出的告警点数 == 对比表里的 `n_alerts`。
    """
    resolution = resolve_detector(requested, bundle)
    detector = create_detector(resolution.detector).fit(bundle)
    result = detector.detect(bundle, threshold=float(detector.default_threshold))

    scores = np.asarray(result.scores, dtype=float)
    values = np.asarray(bundle.values, dtype=float)
    rules = [AlertRule(level="P1", multiplier=float(width))]
    severity = severity_from_conditions(scores, values, rules)

    bands = compute_bands(detector, bundle, width)
    baseline = np.asarray(bands.baseline, dtype=float) if bands else np.array([])
    lower = np.asarray(bands.lower, dtype=float) if bands else np.array([])
    upper = np.asarray(bands.upper, dtype=float) if bands else np.array([])

    def _clean(array: np.ndarray) -> list[float]:
        """NaN / Inf 不能进 JSON —— 转成 null。"""
        return [None if not np.isfinite(v) else float(v) for v in array.tolist()]

    return {
        "detector": requested,
        "resolved": resolution.detector,
        "metric_class": resolution.metric_class,
        "fallback": resolution.fallback,
        "rationale": resolution.rationale,
        "scores": _clean(scores),
        "severity": [int(s) for s in severity.tolist()],
        "baseline": _clean(baseline),
        "lower": _clean(lower),
        "upper": _clean(upper),
        "n_alerts": int((severity > SEVERITY_NORMAL).sum()),
        "multiplier": float(width),
    }


def window_detail(
    store: PlatformStore,
    data_root: Path,
    spec: DataSpec,
    *,
    series_id: str,
    window_index: int,
    detectors: list[str] | None = None,
) -> dict[str, Any]:
    """单个窗口的详细时序数据 —— 供前端画图。

    ⚠️ **按需拉取**，不塞进 `/api/lab/run` 的响应 ——
       一次实验可能有上百个窗口，全量带曲线会把响应撑爆。
    """
    prepared = prepare(store, data_root, spec)

    target: PreparedWindow | None = None
    for item in prepared.series:
        if item.series.series_id != series_id:
            continue
        for window in item.windows:
            if window.quality.index == window_index:
                target = window
                break
        if target is not None:
            break

    if target is None:
        known = {item.series.series_id for item in prepared.series}
        if series_id not in known:
            raise ValueError(f"序列不存在: {series_id}（本次实验有 {sorted(known)}）")
        raise ValueError(f"窗口不存在: {series_id}#{window_index}")

    bundle = target.bundle
    names = check_detectors(list(detectors) if detectors else [AUTO_DETECTOR])

    timestamps = [
        int(value)
        for value in bundle.timestamps.astype("datetime64[ms]").astype("int64").tolist()
    ]
    values = [None if not np.isfinite(v) else float(v) for v in np.asarray(bundle.values).tolist()]

    return {
        "series_id": series_id,
        "window_index": window_index,
        "start": to_iso(target.quality.start),
        "end": to_iso(target.quality.end),
        "freq": prepared.freq,
        "n": int(bundle.n),
        "expected": int(target.quality.expected),
        "missing_ratio": round(target.quality.missing_ratio, 4),
        "timestamps": timestamps,
        "values": values,
        "detectors": [
            _window_detector_detail(bundle, name, PRIMARY_MULTIPLIER) for name in names
        ],
        "warnings": prepared.warnings,
    }
