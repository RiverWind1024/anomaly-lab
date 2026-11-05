"""P1 补齐：单个窗口的详细时序数据（画图用）。

⚠️ 关键约束：图上标出的告警点数，必须与对比表里的 `n_alerts` **一致**。
   两处口径不一样的话，用户会对着图和表互相怀疑。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.lab.detect import run_experiment, window_detail
from anomaly_lab.lab.spec import DataSpec, SamplingSpec
from anomaly_lab.platform.store import PlatformStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _db(path, *, n: int = 600, period: int = 8) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, series TEXT, value REAL)")
    rows = []
    for i in range(n):
        ts = (BASE + timedelta(hours=i)).isoformat()
        value = float(np.sin(2 * np.pi * i / period))
        if 120 <= i < 130:
            value += 6.0
        rows.append((ts, "a", value))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _store(tmp_path, db_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db_path))
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="series",
        freq="1h",
    )
    return store, metric


def _spec(metric_id: int) -> DataSpec:
    return DataSpec(
        kind="metric",
        metric_id=metric_id,
        start=BASE,
        end=BASE + timedelta(hours=600),
        sampling=SamplingSpec(window_points=100, stride_points=100, max_points=600, max_windows=10),
    )


def _setup(tmp_path):
    db = tmp_path / "source.db"
    _db(db)
    store, metric = _store(tmp_path, db)
    return store, tmp_path, _spec(metric.id)


def test_window_detail_returns_series_values(tmp_path):
    store, root, spec = _setup(tmp_path)

    detail = window_detail(store, root, spec, series_id="m:a", window_index=0)

    assert detail["series_id"] == "m:a"
    assert detail["window_index"] == 0
    assert len(detail["timestamps"]) == len(detail["values"])
    assert detail["n"] == 100
    assert detail["freq"] == "1h"


def test_window_detail_includes_each_detector(tmp_path):
    store, root, spec = _setup(tmp_path)

    detail = window_detail(store, root, spec, series_id="m:a", window_index=0, detectors=["iqr", "zscore"])

    names = [item["detector"] for item in detail["detectors"]]
    assert names == ["iqr", "zscore"]
    for item in detail["detectors"]:
        assert len(item["scores"]) == detail["n"]
        assert len(item["severity"]) == detail["n"]


def test_window_detail_alert_count_matches_experiment(tmp_path):
    """图上标的告警点必须与对比表里的数字一致 —— 否则用户会互相怀疑。"""
    store, root, spec = _setup(tmp_path)

    experiment = run_experiment(store, root, spec, detectors=["iqr"])
    detail = window_detail(store, root, spec, series_id="m:a", window_index=0, detectors=["iqr"])

    table_n = next(
        item["n_alerts"]
        for item in experiment["results"][0]["per_window"]
        if item["series_id"] == "m:a" and item["window_index"] == 0
    )
    assert detail["detectors"][0]["n_alerts"] == table_n
    assert sum(1 for s in detail["detectors"][0]["severity"] if s > 0) == table_n


def test_window_detail_reports_bands_when_supported(tmp_path):
    store, root, spec = _setup(tmp_path)

    detail = window_detail(store, root, spec, series_id="m:a", window_index=0, detectors=["iqr"])

    bands = detail["detectors"][0]
    assert len(bands["baseline"]) == detail["n"]
    assert len(bands["upper"]) == detail["n"]


def test_window_detail_unknown_series_raises(tmp_path):
    store, root, spec = _setup(tmp_path)

    with pytest.raises(ValueError, match="序列"):
        window_detail(store, root, spec, series_id="m:nope", window_index=0)


def test_window_detail_unknown_window_raises(tmp_path):
    store, root, spec = _setup(tmp_path)

    with pytest.raises(ValueError, match="窗口"):
        window_detail(store, root, spec, series_id="m:a", window_index=99)
