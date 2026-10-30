"""对一组序列回测检测器：逐条搜索阈值并汇总指标。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.base import Detector
from anomaly_lab.evaluation.metrics import precision_recall_f1, range_based_prf
from anomaly_lab.evaluation.thresholds import search_threshold


@dataclass(frozen=True, eq=False)
class BacktestRow:
    series_id: str
    metric_class: str
    detector: str
    score_type: str
    threshold: float
    precision: float
    recall: float
    f1: float
    range_f1: float
    n_truth: int
    n_pred: int
    elapsed_ms: float
    #: 序列的时间范围（ISO 秒精度）—— 前端按它筛时间
    start_ts: str = ""
    end_ts: str = ""
    #: 数据来源维度 —— 前端按它聚合（形态 / 算法 / 来源）
    source: str = ""


def series_span(series: SeriesBundle) -> tuple[str, str]:
    """序列的时间范围（ISO 秒精度）。

    ⚠️ datetime64[ns] 直接 str() 会带上 9 位纳秒 —— 前端按字符串比较
    时间范围时格式必须一致，所以统一截到秒。
    """
    stamps = series.timestamps
    if len(stamps) == 0:
        return "", ""
    return str(stamps[0])[:19], str(stamps[-1])[:19]


def _mask_to_intervals(mask: np.ndarray) -> list[tuple[int, int]]:
    mask = np.asarray(mask).astype(bool)
    padded = np.concatenate([[False], mask, [False]])
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:]) - 1
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


def backtest_detector(
    series_list: list[SeriesBundle],
    detector_factory: Callable[[], Detector],
    use_searched_threshold: bool = True,
) -> list[BacktestRow]:
    rows: list[BacktestRow] = []
    for series in series_list:
        detector = detector_factory().fit(series)
        if use_searched_threshold:
            scores = detector.score(series)
            searched = search_threshold(scores, detector.score_type, series.labels)
            result = detector.detect(series, threshold=searched.threshold)
        else:
            result = detector.detect(series)

        pred = np.asarray(result.is_anomaly).astype(bool)
        truth = np.asarray(series.labels).astype(bool)
        precision, recall, f1 = precision_recall_f1(pred, truth)
        _, _, range_f1 = range_based_prf(
            _mask_to_intervals(pred), _mask_to_intervals(truth)
        )
        start_ts, end_ts = series_span(series)
        rows.append(
            BacktestRow(
                series_id=series.series_id,
                metric_class=str(series.meta.get("metric_class", "unknown")),
                detector=result.detector,
                score_type=result.score_type,
                threshold=float(result.threshold),
                precision=precision,
                recall=recall,
                f1=f1,
                range_f1=range_f1,
                n_truth=int(truth.sum()),
                n_pred=int(pred.sum()),
                elapsed_ms=float(result.elapsed_ms),
                start_ts=start_ts,
                end_ts=end_ts,
                source=str(series.meta.get("source", "synthetic")),
            )
        )
    return rows
