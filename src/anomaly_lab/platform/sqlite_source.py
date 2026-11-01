"""SQLite 数据源 —— **薄壳**。

真正的实现在 `anomaly_lab.platform.sources.sqlite`；这里保留旧名字是为了
让既有测试与 monkeypatch 目标名（`anomaly_lab.platform.runner.load_series`）
零改动。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.sources.base import MAX_ROWS, MIN_VALID_POINTS
from anomaly_lab.platform.sources.sqlite import fetch_sqlite_series

__all__ = ["MAX_ROWS", "MIN_VALID_POINTS", "load_series"]


def load_series(
    metric: Metric,
    source_path: Path,
    start: datetime,
    end: datetime,
) -> list[SeriesBundle]:
    """在 [start, end) 区间取数，按 group_column 拆成多条序列。"""
    return fetch_sqlite_series(metric, source_path, start, end)
