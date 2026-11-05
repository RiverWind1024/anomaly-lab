"""预检主流程：取数 → 采样 → 体检 → 形态推断。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.lab.inspect import inspect
from anomaly_lab.lab.spec import DataSpec, SamplingSpec
from anomaly_lab.platform.store import PlatformStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _db(path, *, n: int = 200, hosts: tuple[str, ...] = ("a",), spike_at: int | None = None):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    rows = []
    for i in range(n):
        ts = (BASE + timedelta(hours=i)).isoformat()
        for host in hosts:
            # 8 小时周期：50 点窗口能看到 6 个完整周期，分类器会判为 periodic
            value = float(np.sin(2 * np.pi * i / 8))
            if spike_at is not None and i == spike_at:
                value = 100.0
            rows.append((ts, host, value))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _store(tmp_path, db_path) -> tuple[PlatformStore, object, object]:
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db_path))
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="host",
        freq="1h",
    )
    return store, source, metric


def _spec(metric_id: int | None, *, end_hours: int = 200, **overrides) -> DataSpec:
    sampling = SamplingSpec(
        window_points=50,
        stride_points=50,
        max_points=200,
        max_windows=10,
        **{k: v for k, v in overrides.items() if k in {"mode", "min_valid_ratio"}},
    )
    return DataSpec(
        kind="metric",
        metric_id=metric_id,
        start=BASE,
        end=BASE + timedelta(hours=end_hours),
        sampling=sampling,
    )


def test_inspect_metric_returns_windows_quality_and_classification(tmp_path):
    db = tmp_path / "source.db"
    _db(db)
    store, _, metric = _store(tmp_path, db)

    result = inspect(store, tmp_path, _spec(metric.id))

    assert result["warnings"] == []
    series = result["series"][0]
    assert series["series_id"] == "m:a"
    assert len(series["windows"]) == 4
    first = series["windows"][0]
    assert first["n"] == 50
    assert first["expected"] == 50
    assert first["missing_ratio"] == 0.0
    assert first["sufficient"] is True
    assert first["classification"]["metric_class"] == "periodic"
    assert first["classification"]["candidates"]
    # 1h 粒度：日周期 24 点，50 点窗口可识别（50 // 24 = 2 < 3，不可识别）
    assert result["period_capability"]["daily_points"] == 24
    assert result["period_capability"]["daily_ok"] is False


def test_inspect_sql_kind_without_metric(tmp_path):
    db = tmp_path / "source.db"
    _db(db, hosts=("a",))
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db))

    spec = DataSpec(
        kind="sql",
        source_id=source.id,
        sql="SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        freq="1h",
        start=BASE,
        end=BASE + timedelta(hours=200),
        sampling=SamplingSpec(window_points=50, stride_points=50, max_points=200),
    )
    result = inspect(store, tmp_path, spec)

    assert [s["series_id"] for s in result["series"]] == ["lab"]
    assert len(result["series"][0]["windows"]) == 4


def test_inspect_rejects_freq_mismatch(tmp_path):
    db = tmp_path / "source.db"
    _db(db)
    store, _, metric = _store(tmp_path, db)
    spec = _spec(metric.id)
    spec = DataSpec(**{**spec.__dict__, "freq": "5min"})

    with pytest.raises(ValueError, match="freq"):
        inspect(store, tmp_path, spec)


def test_inspect_caps_series_and_reports_warning(tmp_path):
    db = tmp_path / "source.db"
    _db(db, hosts=("a", "b", "c"))
    store, _, metric = _store(tmp_path, db)
    spec = _spec(metric.id)
    spec = DataSpec(**{**spec.__dict__, "max_series": 2})

    result = inspect(store, tmp_path, spec)

    assert len(result["series"]) == 2
    assert any("未纳入" in warning for warning in result["warnings"])


def test_inspect_warns_when_range_is_shorter_than_one_window(tmp_path):
    db = tmp_path / "source.db"
    _db(db, n=20)
    store, _, metric = _store(tmp_path, db)

    result = inspect(store, tmp_path, _spec(metric.id, end_hours=10))

    assert result["series"][0]["windows"] == []
    assert any("不足一个窗口" in warning for warning in result["warnings"])


def test_inspect_reports_empty_data(tmp_path):
    db = tmp_path / "source.db"
    _db(db, n=0)
    store, _, metric = _store(tmp_path, db)

    result = inspect(store, tmp_path, _spec(metric.id))

    assert result["series"] == []
    assert any("没有取到数据" in warning for warning in result["warnings"])


def test_inspect_stratified_includes_suspicious_window(tmp_path):
    db = tmp_path / "source.db"
    _db(db, spike_at=125)  # 第 2 个窗口（125 // 50 = 2）
    store, _, metric = _store(tmp_path, db)
    spec = _spec(metric.id)
    spec = DataSpec(
        **{
            **spec.__dict__,
            "sampling": SamplingSpec(
                mode="stratified",
                window_points=50,
                stride_points=50,
                max_points=200,
                max_windows=2,
            ),
        }
    )

    result = inspect(store, tmp_path, spec)
    indices = [w["index"] for w in result["series"][0]["windows"]]

    assert len(indices) == 2
    assert 2 in indices


def test_inspect_reports_data_actual_span(tmp_path):
    db = tmp_path / "source.db"
    _db(db, n=50)
    store, _, metric = _store(tmp_path, db)

    result = inspect(store, tmp_path, _spec(metric.id))

    series = result["series"][0]
    assert series["data_start"] == "2026-01-01T00:00:00+00:00"
    assert series["data_end"] == "2026-01-03T01:00:00+00:00"


def test_inspect_warns_when_most_windows_are_empty(tmp_path):
    # 数据只在最后 100 小时，前面的窗口全是空的
    db = tmp_path / "source.db"
    _db(db, n=100)
    store, _, metric = _store(tmp_path, db)
    spec = DataSpec(
        kind="metric",
        metric_id=metric.id,
        start=BASE,
        end=BASE + timedelta(hours=400),
        sampling=SamplingSpec(window_points=50, stride_points=50, max_points=400),
    )

    result = inspect(store, tmp_path, spec)

    assert any("没有数据" in warning for warning in result["warnings"])


def test_inspect_skips_classification_for_short_windows(tmp_path):
    db = tmp_path / "source.db"
    _db(db, n=40)
    store, _, metric = _store(tmp_path, db)
    spec = DataSpec(
        kind="metric",
        metric_id=metric.id,
        start=BASE,
        end=BASE + timedelta(hours=40),
        sampling=SamplingSpec(window_points=20, stride_points=20, max_points=40),
    )

    result = inspect(store, tmp_path, spec)
    windows = result["series"][0]["windows"]

    assert windows[0]["n"] == 20
    assert windows[0]["classification"] is None
    assert "点数不足" in windows[0]["classification_reason"]
