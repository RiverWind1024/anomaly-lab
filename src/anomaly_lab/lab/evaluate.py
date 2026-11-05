"""P3：有真值模式 —— 校准 / 测试分开的评估。

⚠️ **为什么必须分开**：
   用同一批数据既选阈值又报 F1，F1 一定是虚高的 ——
   那说明的不是「这个算法有多好」，而是「这个阈值在这批数据上有多贴合」。
   校准集负责选阈值，测试集负责验收，两者绝不重叠。

⚠️ **校准的粒度是「一个窗口」**：
   生产上每个窗口独立判定，所以校准也按窗口算 —— 某窗的最优阈值，
   再取各窗的中位数作为推荐值。这样不会被某个尺度异常的窗口带跑。

⚠️ **判定口径与平台一致**（`scores >= threshold`）：
   lab 的第一原则是「实验里看到的 = 上线后拿到的」。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from anomaly_lab.evaluation.metrics import precision_recall_f1, range_based_prf
from anomaly_lab.evaluation.thresholds import search_threshold
from anomaly_lab.lab.detect import DEFAULT_MULTIPLIERS, PRIMARY_MULTIPLIER, default_detectors
from anomaly_lab.lab.inspect import Prepared, prepare, spec_dict
from anomaly_lab.lab.spec import DataSpec
from anomaly_lab.platform.detectors import create_detector, resolve_detector
from anomaly_lab.platform.store import PlatformStore

#: 校准 / 测试的默认切分比例 —— 前一半校准，后一半测试。
DEFAULT_SPLIT_RATIO = 0.5


@dataclass
class ScoredWindow:
    """一个窗口的分数与真值。"""

    series_id: str
    window_index: int
    start: str
    scores: np.ndarray
    truth: np.ndarray
    resolved: str
    score_type: str


def _mask_to_intervals(mask: np.ndarray) -> list[tuple[int, int]]:
    """真值 / 预测掩码 → 区间列表（闭区间）。"""
    mask = np.asarray(mask).astype(bool)
    if not mask.any():
        return []
    padded = np.concatenate([[False], mask, [False]])
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:]) - 1
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def score_bundle(
    bundle: Any,
    name: str,
    *,
    series_id: str,
    window_index: int,
    start: str,
) -> ScoredWindow:
    """给一条序列（通常是一个窗口）打分数，并带上真值。

    ⚠️ **真值从 `bundle.labels` 取** —— 切窗时标签已经一起切好了。
    """
    resolution = resolve_detector(name, bundle)
    detector = create_detector(resolution.detector).fit(bundle)
    result = detector.detect(bundle, threshold=float(detector.default_threshold))
    scores = np.asarray(result.scores, dtype=float)
    labels = bundle.labels
    truth = (
        np.zeros(len(scores), dtype=bool)
        if labels is None
        else np.asarray(labels).astype(bool)
    )
    return ScoredWindow(
        series_id=series_id,
        window_index=window_index,
        start=start,
        scores=scores,
        truth=truth,
        resolved=resolution.detector,
        score_type=str(detector.score_type),
    )


def score_windows(prepared: Prepared, name: str) -> list[ScoredWindow]:
    """在所有窗口上跑一个检测器，收集分数与真值。"""
    scored: list[ScoredWindow] = []
    for item in prepared.series:
        for window in item.windows:
            if not window.quality.sufficient:
                continue
            scored.append(
                score_bundle(
                    window.bundle,
                    name,
                    series_id=item.series.series_id,
                    window_index=window.quality.index,
                    start=window.quality.start.isoformat(),
                )
            )
    return scored


def split_by_series(
    windows: list[ScoredWindow], ratio: float = DEFAULT_SPLIT_RATIO
) -> tuple[list[ScoredWindow], list[ScoredWindow]]:
    """按序列把窗口切成「校准集」与「测试集」。

    ⚠️ **按序列内的时间顺序切** —— 窗口本身不跨界，
       跨界的窗口会同时用到两半的数据，真值就泄漏到测试集里了。
    """
    by_series: dict[str, list[ScoredWindow]] = {}
    for item in windows:
        by_series.setdefault(item.series_id, []).append(item)

    calibration: list[ScoredWindow] = []
    test: list[ScoredWindow] = []
    for series_id in sorted(by_series):
        ordered = sorted(by_series[series_id], key=lambda x: (x.start, x.window_index))
        if len(ordered) < 2:
            # ⚠️ 一个窗口切不开 —— 全算校准集，测试集留空。
            calibration.extend(ordered)
            continue
        cut = round(len(ordered) * ratio)
        cut = max(1, min(cut, len(ordered) - 1))
        calibration.extend(ordered[:cut])
        test.extend(ordered[cut:])
    return calibration, test


def calibrate(windows: list[ScoredWindow]) -> tuple[float | None, dict[str, Any]]:
    """在校准集上搜出推荐阈值。

    ⚠️ **逐窗口搜、再取中位数** —— 每个窗口的分数尺度自成一体，
       直接把所有分数拼起来搜会被尺度最大的那个窗口带跑。
    """
    per_window: list[dict[str, Any]] = []
    thresholds: list[float] = []
    for item in windows:
        if not item.truth.any():
            # ⚠️ 没有真值点的窗口**不能**用来定阈值 ——
            #    在它上面搜出来的最优值就是「什么都不报」。
            continue
        searched = search_threshold(item.scores, item.score_type, item.truth)
        thresholds.append(float(searched.threshold))
        per_window.append(
            {
                "series_id": item.series_id,
                "window_index": item.window_index,
                "threshold": round(float(searched.threshold), 6),
                "f1": round(float(searched.f1), 4),
            }
        )

    if not thresholds:
        return None, {
            "threshold": None,
            "n_windows_used": 0,
            "n_windows_skipped": len(windows),
            "per_window": per_window,
        }

    # ⚠️ 中位数而不是均值 —— 个别窗口的最优阈值可能是离群值。
    recommended = float(np.median(thresholds))
    return recommended, {
        "threshold": round(recommended, 6),
        "n_windows_used": len(thresholds),
        "n_windows_skipped": len(windows) - len(thresholds),
        "per_window": per_window,
    }


def evaluate_at(windows: list[ScoredWindow], threshold: float) -> dict[str, Any]:
    """用给定阈值在一批窗口上算 P / R / F1。

    ⚠️ 点级指标是**全局拼接**后算的 —— 没有真值的窗口也要算进去，
       它们贡献误报（FP）。漏掉的话，「在没标注的窗口上乱报」不受惩罚。
    """
    if not windows:
        return {
            "threshold": round(float(threshold), 6),
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "range_f1": 0.0,
            "n_alerts": 0,
            "n_truth": 0,
            "n_windows": 0,
        }

    preds: list[np.ndarray] = []
    truths: list[np.ndarray] = []
    range_f1s: list[float] = []
    for item in windows:
        pred = np.asarray(item.scores, dtype=float) >= float(threshold)
        preds.append(pred)
        truths.append(item.truth)
        if not item.truth.any():
            # ⚠️ 没真值就没有区间可言 —— `range_based_prf` 会把「空 vs 空」
            #    判成满分 1.0，那是在奖励「什么都不报」。
            continue
        _, _, range_f1 = range_based_prf(
            _mask_to_intervals(pred), _mask_to_intervals(item.truth)
        )
        range_f1s.append(float(range_f1))

    precision, recall, f1 = precision_recall_f1(
        np.concatenate(preds), np.concatenate(truths)
    )
    return {
        "threshold": round(float(threshold), 6),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        # ⚠️ 区间级按窗口取平均 —— 每个窗口权重相同，
        #    不然点数多的窗口会主导结果。
        "range_f1": round(float(np.mean(range_f1s)) if range_f1s else 0.0, 4),
        "n_alerts": int(sum(int(item.sum()) for item in preds)),
        "n_truth": int(sum(int(item.sum()) for item in truths)),
        "n_windows": len(windows),
    }


def _resolved_mix(windows: list[ScoredWindow]) -> dict[str, int]:
    """`auto` 逐窗换算法 —— 这个分布要报出来。"""
    mix: dict[str, int] = {}
    for item in windows:
        mix[item.resolved] = mix.get(item.resolved, 0) + 1
    return mix


def _truth_summary(prepared: Prepared) -> dict[str, Any]:
    """真值概况 —— 有多少序列带真值、多少个真值点。"""
    n_truth = 0
    n_series = 0
    sources: set[str] = set()
    for item in prepared.series:
        labels = item.series.labels
        if labels is None:
            continue
        n_series += 1
        sources.add(item.series.label_source)
        n_truth += int(labels.sum())
    return {
        "sources": sorted(sources),
        "n_series_with_truth": n_series,
        "n_truth_points": n_truth,
    }


def evaluate_experiment(
    store: PlatformStore,
    data_root: Path,
    spec: DataSpec,
    *,
    detectors: list[str] | None = None,
    split_ratio: float = DEFAULT_SPLIT_RATIO,
    multipliers: list[float] | None = None,
) -> dict[str, Any]:
    """有真值的评估：校准集选阈值，测试集报 F1。

    **不落盘** —— 产物全在返回值里。
    """
    if not 0.0 < split_ratio < 1.0:
        raise ValueError("split_ratio 必须在 (0, 1) 内")

    prepared = prepare(store, data_root, spec)
    warnings = list(prepared.warnings)

    names = list(detectors) if detectors else default_detectors(prepared)
    factors = tuple(multipliers) if multipliers else DEFAULT_MULTIPLIERS

    truth = _truth_summary(prepared)
    if truth["n_truth_points"] == 0:
        warnings.append(
            "这批数据没有真值标注 —— 评估需要点级真值。"
            "合成与公开集自带标签；已有指标需要先在标注页标一段。"
        )

    results: list[dict[str, Any]] = []
    n_calibration = 0
    n_test = 0

    for name in names:
        scored = score_windows(prepared, name)
        if not scored:
            warnings.append(f"算法 {name} 没有任何可评估的窗口（数据不足）")
            continue

        calibration_windows, test_windows = split_by_series(scored, split_ratio)
        n_calibration = max(n_calibration, len(calibration_windows))
        n_test = max(n_test, len(test_windows))
        threshold, calibration_detail = calibrate(calibration_windows)

        # ⚠️ 真值太稀就切不开 —— 说清楚该调什么，而不是只报「没有真值」。
        n_truth_windows = sum(1 for item in scored if item.truth.any())
        if n_truth_windows < 2:
            warnings.append(
                f"只有 {n_truth_windows} 个窗口带真值 —— 真值太稀疏，校准与测试切不开。"
                "把「窗口点数」调小，让每个异常点各自落在窗口里"
            )

        if not test_windows:
            warnings.append(
                f"算法 {name} 的窗口不够切分（每条序列至少要 2 个窗口）—— "
                "只有校准集，没有测试集"
            )
            results.append(
                {
                    "detector": name,
                    "resolved_mix": _resolved_mix(scored),
                    "calibration": {**calibration_detail, "metrics": None},
                    "test": None,
                    "default_threshold": None,
                    "sensitivity": [],
                }
            )
            continue

        if threshold is None:
            warnings.append(
                f"算法 {name} 的校准集里没有带真值的窗口 —— 无法定阈值，"
                f"改用平台默认倍数 {PRIMARY_MULTIPLIER}。"
                "真值太稀疏时（公开集常见）就是这样：公开集本就不用于调参，"
                "这里的成绩是「平台默认阈值在真实数据上的表现」"
            )
            threshold = float(PRIMARY_MULTIPLIER)

        metrics = evaluate_at(test_windows, threshold)
        results.append(
            {
                "detector": name,
                "resolved_mix": _resolved_mix(scored),
                "calibration": {
                    **calibration_detail,
                    # ⚠️ 校准集自己的成绩 —— 与测试集一比就知道有没有过拟合。
                    "metrics": evaluate_at(calibration_windows, threshold),
                },
                "test": metrics,
                "default_threshold": evaluate_at(test_windows, float(PRIMARY_MULTIPLIER)),
                "sensitivity": [
                    {
                        "threshold": round(float(factor), 2),
                        **evaluate_at(test_windows, float(factor)),
                    }
                    for factor in factors
                ],
            }
        )

    return {
        "spec": spec_dict(prepared.spec),
        "truth": truth,
        "split": {
            "ratio": round(float(split_ratio), 4),
            "calibration_windows": n_calibration,
            "test_windows": n_test,
        },
        "results": results,
        "warnings": warnings,
    }
