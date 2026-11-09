"""P1：多算法对比实验。

无真值口径 —— 产出「检出画像 + 取舍」：检出量、跨窗稳定性、耗时、倍数敏感性。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.lab.detect import run_experiment
from anomaly_lab.lab.spec import DataSpec, SamplingSpec
from anomaly_lab.platform.store import PlatformStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _db(path, *, n: int = 600, period: int = 8) -> None:
    """周期型序列；`spike_at` 位置放一个尖峰。"""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, series TEXT, value REAL)")
    rows = []
    for i in range(n):
        ts = (BASE + timedelta(hours=i)).isoformat()
        value = float(np.sin(2 * np.pi * i / period))
        rows.append((ts, "a", value))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _store(tmp_path, db_path) -> tuple[PlatformStore, object]:
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db_path))
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="series",
    )
    return store, metric


def _spec(metric_id: int, **overrides) -> DataSpec:
    sampling = SamplingSpec(
        window_points=100,
        stride_points=100,
        max_points=600,
        max_windows=10,
        **overrides,
    )
    return DataSpec(
        kind="metric",
        metric_id=metric_id,
        start=BASE,
        end=BASE + timedelta(hours=600),
        sampling=sampling,
    )


def _run(tmp_path, *, detectors=None, multipliers=None):
    db = tmp_path / "source.db"
    _db(db)
    store, metric = _store(tmp_path, db)
    return run_experiment(
        store,
        tmp_path,
        _spec(metric.id),
        detectors=detectors,
        multipliers=multipliers,
    )


def test_run_reports_one_result_per_detector(tmp_path):
    result = _run(tmp_path, detectors=["iqr", "mad"])

    names = [item["detector"] for item in result["results"]]
    assert names == ["iqr", "mad"]
    for item in result["results"]:
        assert item["aggregate"]["n_windows"] == 6
        assert item["aggregate"]["n_alerts"] >= 0
        assert item["aggregate"]["elapsed_ms"] >= 0


def test_run_auto_resolves_detector_per_window(tmp_path):
    result = _run(tmp_path, detectors=["auto"])

    run = result["results"][0]
    assert run["detector"] == "auto"
    # auto 是逐窗口解析的 —— 每个窗口都要说清楚实际用了哪个算法
    assert len(run["per_window"]) == 6
    for window in run["per_window"]:
        assert window["detector"]
        assert window["metric_class"]
        assert window["rationale"]


def test_run_auto_reports_which_detector_each_window_used(tmp_path):
    result = _run(tmp_path, detectors=["auto"])

    mix = result["results"][0]["aggregate"]["resolved_mix"]
    # auto 是逐窗口解析的 —— 分布的窗口数之和就是跑了多少窗
    assert sum(mix.values()) == result["results"][0]["aggregate"]["n_windows"]
    assert all(name for name in mix)


def test_run_sensitivity_is_monotonic_in_multiplier(tmp_path):
    result = _run(tmp_path, detectors=["iqr"], multipliers=[1.5, 2.5, 3.5])

    sensitivity = result["results"][0]["aggregate"]["sensitivity"]
    assert sensitivity["1.5"] >= sensitivity["2.5"] >= sensitivity["3.5"]


def test_run_sensitivity_defaults_to_standard_multipliers(tmp_path):
    result = _run(tmp_path, detectors=["iqr"])

    sensitivity = result["results"][0]["aggregate"]["sensitivity"]
    assert set(sensitivity) == {"1.5", "2.0", "2.5", "3.0", "3.5", "4.0"}


def test_run_aggregates_stability_across_windows(tmp_path):
    result = _run(tmp_path, detectors=["iqr"])

    aggregate = result["results"][0]["aggregate"]
    assert aggregate["n_windows"] == 6
    assert 0.0 <= aggregate["stability"] <= 1.0
    assert aggregate["n_windows_with_alerts"] <= aggregate["n_windows"]


def test_run_marks_insufficient_windows(tmp_path):
    # 8 点窗口 —— 少于 MIN_AUTO_POINTS(10)，形态推断与检测都做不了
    db = tmp_path / "source.db"
    _db(db, n=40)
    store, metric = _store(tmp_path, db)
    spec = DataSpec(
        kind="metric",
        metric_id=metric.id,
        start=BASE,
        end=BASE + timedelta(hours=40),
        sampling=SamplingSpec(window_points=8, stride_points=8, max_points=40),
    )

    result = run_experiment(store, tmp_path, spec, detectors=["iqr"])

    window = result["results"][0]["per_window"][0]
    assert window["skipped"] is True
    assert window["n_alerts"] == 0
    assert window["skip_reason"]


def test_run_rejects_unknown_detector(tmp_path):
    with pytest.raises(ValueError, match="检测器"):
        _run(tmp_path, detectors=["not-a-detector"])


def test_run_keeps_windows_and_warnings(tmp_path):
    result = _run(tmp_path, detectors=["iqr"])

    assert "windows" in result
    assert result["windows"][0]["expected"] == 100
    assert "warnings" in result
