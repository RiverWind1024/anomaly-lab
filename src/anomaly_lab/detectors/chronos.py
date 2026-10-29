"""Chronos 预训练模型适配器；权重不可用时优雅降级，不在 import 时下载。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.base import TimedDetector

MODEL_NAME = "amazon/chronos-t5-tiny"


class ChronosUnavailable(RuntimeError):
    """chronos 包或本地权重不可用。"""


def _hf_cache_roots() -> list[Path]:
    roots = []
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


def chronos_available() -> bool:
    if importlib.util.find_spec("chronos") is None:
        return False
    pattern = "models--amazon--chronos-t5-*"
    return any(
        any(root.glob(pattern)) for root in _hf_cache_roots() if root.exists()
    )


class ChronosDetector(TimedDetector):
    """用预训练模型的分位数预测区间宽度/越界程度作为异常分数。"""

    name = "chronos"
    score_type = "prob"
    default_threshold = 0.5

    def __init__(self, model_name: str = MODEL_NAME, window: int = 256, horizon: int = 64) -> None:
        self.model_name = model_name
        self.window = int(window)
        self.horizon = int(horizon)
        self.pipeline = None

    def fit(self, series: SeriesBundle) -> ChronosDetector:
        if not chronos_available():
            raise ChronosUnavailable(
                "chronos 未安装或本地无权重缓存；跳过该检测器"
            )
        try:
            from chronos import ChronosPipeline

            self.pipeline = ChronosPipeline.from_pretrained(
                self.model_name, device_map="cpu"
            )
        except Exception as exc:
            raise ChronosUnavailable(f"加载 Chronos 失败: {exc}") from exc
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        if self.pipeline is None:
            self.fit(series)
        assert self.pipeline is not None
        import torch

        values = np.asarray(series.values, dtype=float)
        n = len(values)
        scores = np.zeros(n)
        context_len = min(self.window, max(8, n - self.horizon))
        starts = list(range(context_len, n, self.horizon))
        for start in starts:
            context = values[max(0, start - context_len) : start]
            target = values[start : start + self.horizon]
            if len(target) == 0:
                continue
            tensor = torch.tensor(context, dtype=torch.float32).unsqueeze(0)
            try:
                samples = self.pipeline.predict(tensor, prediction_length=len(target))
                arr = np.asarray(samples)
                low = np.quantile(arr.reshape(-1, len(target)), 0.1, axis=0)
                high = np.quantile(arr.reshape(-1, len(target)), 0.9, axis=0)
            except Exception as exc:
                raise ChronosUnavailable(f"Chronos 预测失败: {exc}") from exc
            width = np.maximum(high - low, 1e-6)
            outside = np.maximum(low - target, 0.0) + np.maximum(target - high, 0.0)
            scores[start : start + len(target)] = outside / width
        low, high = float(scores.min()), float(scores.max())
        if high - low < 1e-12:
            return np.zeros_like(scores)
        return (scores - low) / (high - low)

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)
