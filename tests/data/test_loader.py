"""数据集落盘与加载的往返一致性。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.data.loader import build_synthetic_dataset, load_dataset, save_dataset


def _series(n: int = 50, freq: str = "5min") -> SeriesBundle:
    stamps = (np.arange(n) * np.timedelta64(5, "m")).astype("datetime64[ns]")
    return SeriesBundle(
        series_id="s-1",
        values=np.arange(n, dtype=float),
        timestamps=stamps,
        freq=freq,
        labels=np.zeros(n, dtype=np.int8),
        label_source="synthetic",
        meta={"metric_class": "stationary"},
    )


def test_timestamps_round_trip_keeps_span(tmp_path: Path):
    """落盘再加载，时间戳的**跨度**不能被压扁。

    ⚠️ npz 里存的是「距 epoch 的纳秒偏移」——
       加载时直接 `astype("datetime64[ns]")` 会被当成**绝对**纳秒，
       500 个点全挤在 `1970-01-01T00:00:00`，图表 x 轴直接退化。
    """
    original = _series()
    save_dataset([original], tmp_path)
    restored = load_dataset(tmp_path)[0]

    assert restored.timestamps[0] == original.timestamps[0]
    assert restored.timestamps[-1] == original.timestamps[-1]
    span_before = original.timestamps[-1] - original.timestamps[0]
    span_after = restored.timestamps[-1] - restored.timestamps[0]
    assert span_after == span_before


def test_generated_dataset_keeps_span(tmp_path: Path):
    """生成的合成数据集，跨度要等于 (n-1) × freq。"""
    series = build_synthetic_dataset(n_per_class=1, out_dir=tmp_path)
    assert series
    for original in series:
        restored = load_dataset(tmp_path)
        match = next(s for s in restored if s.series_id == original.series_id)
        expected = np.timedelta64((len(original.values) - 1) * 5, "m")
        assert match.timestamps[-1] - match.timestamps[0] == expected
