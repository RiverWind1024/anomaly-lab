"""TCN/LSTM 重构式检测器：CPU 训练、模型缓存、分数归一到 [0, 1]。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.bands import Bands
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


def _prepare(
    series_list: list[SeriesBundle], window: int, channels_first: bool
) -> torch.Tensor:
    chunks = []
    for series in series_list:
        values = _standardize(np.asarray(series.values, dtype=float))
        chunks.append(_windows(values, window, max(1, window // 2)))
    array = np.concatenate(chunks, axis=0)
    tensor = torch.tensor(array, dtype=torch.float32)
    return tensor.unsqueeze(1) if channels_first else tensor.unsqueeze(2)


def _train(
    model: nn.Module,
    series_list: list[SeriesBundle],
    epochs: int,
    seed: int,
    out_path: Path,
    arch: str,
    channels_first: bool = True,
) -> TrainingResult:
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    data = _prepare(series_list, WINDOW, channels_first)
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


class LSTMAutoencoder(nn.Module):
    def __init__(self, hidden: int = HIDDEN) -> None:
        super().__init__()
        self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, num_layers=1, batch_first=True)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.head(out)


def train_lstm(
    series: list[SeriesBundle],
    epochs: int = 5,
    seed: int = 42,
    out_path: Path = Path("models/lstm.pt"),
) -> TrainingResult:
    return _train(
        LSTMAutoencoder(),
        series,
        epochs,
        seed,
        out_path,
        arch="lstm",
        channels_first=False,
    )


class _DeepDetector(TimedDetector):
    score_type = "prob"
    arch = ""
    channels_first = True
    default_threshold = 0.5

    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self.model: nn.Module | None = None
        self._window = WINDOW
        # 缓存最近一次的重构结果，bands() 复用 —— 避免为画基线再跑一遍模型
        # 结构：(重构值, 平均绝对误差, 原始序列副本[用于判断缓存是否有效])
        self._reconstruction: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None

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

    def _reconstruct(self, series: SeriesBundle) -> tuple[np.ndarray, np.ndarray]:
        """跑一遍模型，返回 (重构值[原始单位], 平均绝对重构误差[原始单位])。

        缓存最近一次的结果 —— `bands()` 要用重构值画基线，
        不能为画图再跑一遍模型（CPU 上一次几百毫秒到几秒）。
        """
        raw = np.asarray(series.values, dtype=float)
        cache = self._reconstruction
        if cache is not None and np.array_equal(cache[2], raw):
            return cache[0], cache[1]

        if self.model is None:
            self.fit(series)
        assert self.model is not None
        mean = float(np.mean(raw))
        std = float(np.std(raw))
        values = _standardize(raw)
        window = min(self._window, len(values))
        starts = list(range(0, max(1, len(values) - window + 1), max(1, window // 2)))
        if not starts or starts[-1] + window < len(values):
            starts.append(max(0, len(values) - window))
        recon_sum = np.zeros(len(values))
        errors = np.zeros(len(values))
        counts = np.zeros(len(values))
        with torch.no_grad():
            for start in sorted(set(starts)):
                chunk = values[start : start + window]
                tensor = torch.tensor(chunk, dtype=torch.float32)
                tensor = tensor.view(1, 1, -1) if self.channels_first else tensor.view(1, -1, 1)
                reconstruction = self.model(tensor).view(-1).numpy()
                recon_sum[start : start + len(chunk)] += reconstruction
                errors[start : start + len(chunk)] += np.abs(reconstruction - chunk)
                counts[start : start + len(chunk)] += 1
        counts = np.maximum(counts, 1)
        recon_std = recon_sum / counts
        err_std = errors / counts
        # 从标准化空间还原到原始单位。
        # ⚠️ std <= 0 时 `_standardize` 只做平移不做缩放，
        #    所以还原时也只能平移 —— 用 scale=1 而不是 std=0，
        #    否则误差会被压成 0，min-max 归一后全变 0。
        scale = std if std > 0 else 1.0
        recon = recon_std * scale + mean
        err = err_std * scale
        self._reconstruction = (recon, err, raw.copy())
        return recon, err

    def score(self, series: SeriesBundle) -> np.ndarray:
        _, err = self._reconstruct(series)
        low, high = float(err.min()), float(err.max())
        if high - low < 1e-12:
            return np.zeros_like(err)
        return (err - low) / (high - low)

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        """基线 = 模型的重构值；带 = 重构值 ± 阈值对应的误差宽度。

        ⚠️ 带的宽度**不是** `threshold × 某个尺度` —— 深度检测器的分数是
        序列内 min-max 归一的相对量，阈值 0.5 落在归一化区间的中间。
        这里换算回原始单位：误差的归一化下界 + 阈值 ×（上界 − 下界）。
        """
        recon, err = self._reconstruct(series)
        low, high = float(err.min()), float(err.max())
        if high - low < 1e-12:
            width = np.zeros_like(err)
        else:
            width = np.full_like(err, low + float(threshold) * (high - low))
        return Bands(
            baseline=recon,
            lower=recon - width,
            upper=recon + width,
            detector=self.name,
            threshold=float(threshold),
            kind="prediction_interval",
        )

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)


class TCNDetector(_DeepDetector):
    name = "tcn"
    arch = "tcn"

    def _build_model(self) -> nn.Module:
        return TCN()


class LSTMDetector(_DeepDetector):
    name = "lstm"
    arch = "lstm"
    channels_first = False

    def _build_model(self) -> nn.Module:
        return LSTMAutoencoder()
