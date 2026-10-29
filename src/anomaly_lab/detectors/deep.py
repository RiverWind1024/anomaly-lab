"""TCN/LSTM 重构式检测器：CPU 训练、模型缓存、分数归一到 [0, 1]。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.base import TimedDetector

WINDOW = 128
HIDDEN = 32


@dataclass(frozen=True, eq=False)
class TrainingResult:
    history: list[float]
    final_loss: float
    path: Path


class _CausalBlock(nn.Module):
    def __init__(self, channels: int, dilation: int) -> None:
        super().__init__()
        self.pad = (3 - 1) * dilation
        self.conv = nn.Conv1d(channels, channels, kernel_size=3, dilation=dilation)
        self.norm = nn.BatchNorm1d(channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = nn.functional.pad(x, (self.pad, 0))
        return torch.relu(self.norm(self.conv(x)))


class TCN(nn.Module):
    def __init__(self, hidden: int = HIDDEN) -> None:
        super().__init__()
        self.input = nn.Conv1d(1, hidden, kernel_size=1)
        self.blocks = nn.ModuleList(
            [_CausalBlock(hidden, dilation) for dilation in (1, 2, 4, 8, 16)]
        )
        self.output = nn.Conv1d(hidden, 1, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.input(x)
        for block in self.blocks:
            x = block(x)
        return self.output(x)


def _standardize(values: np.ndarray) -> np.ndarray:
    std = float(np.std(values))
    if std <= 0:
        return values - float(np.mean(values))
    return (values - float(np.mean(values))) / std


def _windows(values: np.ndarray, window: int, stride: int) -> np.ndarray:
    if len(values) <= window:
        return np.asarray([values], dtype=float)
    starts = range(0, len(values) - window + 1, stride)
    return np.stack([values[start : start + window] for start in starts])


def _prepare(series_list: list[SeriesBundle], window: int) -> torch.Tensor:
    chunks = []
    for series in series_list:
        values = _standardize(np.asarray(series.values, dtype=float))
        chunks.append(_windows(values, window, max(1, window // 2)))
    array = np.concatenate(chunks, axis=0)
    return torch.tensor(array, dtype=torch.float32).unsqueeze(1)


def _train(
    model: nn.Module,
    series_list: list[SeriesBundle],
    epochs: int,
    seed: int,
    out_path: Path,
    arch: str,
) -> TrainingResult:
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    data = _prepare(series_list, WINDOW)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()
    generator = torch.Generator().manual_seed(seed)
    history: list[float] = []
    batch_size = 16

    for _ in range(max(1, epochs)):
        permutation = torch.randperm(len(data), generator=generator)
        total = 0.0
        count = 0
        model.train()
        for start in range(0, len(data), batch_size):
            batch = data[permutation[start : start + batch_size]]
            optimizer.zero_grad()
            reconstruction = model(batch)
            loss = loss_fn(reconstruction, batch)
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * len(batch)
            count += len(batch)
        history.append(total / max(1, count))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"state_dict": model.state_dict(), "arch": arch, "window": WINDOW, "hidden": HIDDEN},
        out_path,
    )
    return TrainingResult(history=history, final_loss=history[-1], path=out_path)


def train_tcn(
    series: list[SeriesBundle],
    epochs: int = 5,
    seed: int = 42,
    out_path: Path = Path("models/tcn.pt"),
) -> TrainingResult:
    return _train(TCN(), series, epochs, seed, out_path, arch="tcn")


class _DeepDetector(TimedDetector):
    score_type = "prob"
    arch = ""
    default_threshold = 0.5

    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self.model: nn.Module | None = None
        self._window = WINDOW

    def _build_model(self) -> nn.Module:
        raise NotImplementedError

    def fit(self, series: SeriesBundle) -> _DeepDetector:
        checkpoint = torch.load(self.model_path, map_location="cpu", weights_only=False)
        if checkpoint.get("arch") != self.arch:
            raise ValueError(
                f"模型架构不符：期望 {self.arch}，实际 {checkpoint.get('arch')}"
            )
        model = self._build_model()
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        self.model = model
        self._window = int(checkpoint.get("window", WINDOW))
        return self

    def score(self, series: SeriesBundle) -> np.ndarray:
        if self.model is None:
            self.fit(series)
        assert self.model is not None
        values = _standardize(np.asarray(series.values, dtype=float))
        window = min(self._window, len(values))
        starts = list(range(0, max(1, len(values) - window + 1), max(1, window // 2)))
        if not starts or starts[-1] + window < len(values):
            starts.append(max(0, len(values) - window))
        errors = np.zeros(len(values))
        counts = np.zeros(len(values))
        with torch.no_grad():
            for start in sorted(set(starts)):
                chunk = values[start : start + window]
                tensor = torch.tensor(chunk, dtype=torch.float32).view(1, 1, -1)
                reconstruction = self.model(tensor).view(-1).numpy()
                errors[start : start + len(chunk)] += np.abs(reconstruction - chunk)
                counts[start : start + len(chunk)] += 1
        scores = errors / np.maximum(counts, 1)
        low, high = float(scores.min()), float(scores.max())
        if high - low < 1e-12:
            return np.zeros_like(scores)
        return (scores - low) / (high - low)

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


class TCNDetector(_DeepDetector):
    name = "tcn"
    arch = "tcn"

    def _build_model(self) -> nn.Module:
        return TCN()
