"""跨检测器公平对比：动态导入、按形态聚合、不可用检测器记录原因。"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.evaluation.backtest import backtest_detector


@dataclass(frozen=True, eq=False)
class CompareRow:
    detector: str
    score_type: str
    metric_class: str
    precision: float
    recall: float
    f1: float
    range_f1: float
    mean_elapsed_ms: float
    params: int | None
    skipped_reason: str | None


def _count_params(detector: object) -> int | None:
    model = getattr(detector, "model", None)
    if model is not None and hasattr(model, "parameters"):
        return int(sum(p.numel() for p in model.parameters()))
    model_path = getattr(detector, "model_path", None)
    if model_path is not None and model_path.exists():
        try:
            import torch

            checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
            return int(
                sum(value.numel() for value in checkpoint["state_dict"].values())
            )
        except Exception:
            return None
    return None


def compare_detectors(
    series_list: list[SeriesBundle],
    detector_specs: list[tuple[str, str, str]],
    factories: dict[str, Callable] | None = None,
) -> list[CompareRow]:
    rows: list[CompareRow] = []
    for display_name, module_path, class_name in detector_specs:
        try:
            module = importlib.import_module(module_path)
            detector_cls = getattr(module, class_name)
            factory = (
                factories[display_name]
                if factories and display_name in factories
                else detector_cls
            )
            detector = factory()
            results = backtest_detector(series_list, factory)
        except Exception as exc:
            rows.append(
                CompareRow(
                    detector=display_name,
                    score_type="",
                    metric_class="ALL",
                    precision=0.0,
                    recall=0.0,
                    f1=0.0,
                    range_f1=0.0,
                    mean_elapsed_ms=0.0,
                    params=None,
                    skipped_reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        params = _count_params(detector)
        by_class: dict[str, list] = {}
        for result in results:
            by_class.setdefault(result.metric_class, []).append(result)
        for metric_class, items in sorted(by_class.items()):
            count = len(items)
            rows.append(
                CompareRow(
                    detector=display_name,
                    score_type=items[0].score_type,
                    metric_class=metric_class,
                    precision=sum(r.precision for r in items) / count,
                    recall=sum(r.recall for r in items) / count,
                    f1=sum(r.f1 for r in items) / count,
                    range_f1=sum(r.range_f1 for r in items) / count,
                    mean_elapsed_ms=sum(r.elapsed_ms for r in items) / count,
                    params=params,
                    skipped_reason=None,
                )
            )
    return rows
