"""数据正确性回归：缺失值不得静默失效，时区必须按声明解释。"""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.sqlite_source import load_series

QUERY = "SELECT ts, g, v FROM m WHERE $timefilter ORDER BY ts"


def _db(root: Path, rows, name="src.db") -> Path:
    db = root / name
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE m (ts TEXT, g TEXT, v REAL)")
    conn.executemany("INSERT INTO m VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def _metric(**overrides) -> Metric:
    base = {
        "id": 1,
        "source_id": 1,
        "name": "d",
        "query": QUERY,
        "time_column": "ts",
        "value_column": "v",
        "group_column": "g",
        "time_format": "iso_utc",
        "created_at": "",
    }
    base.update(overrides)
    return Metric(**base)


BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# ---------- #1 缺失值 ----------


def test_missing_values_are_dropped_and_counted(tmp_path):
    rows = [
        ((BASE - timedelta(minutes=60 - i)).isoformat(), "a", None if i == 5 else float(i))
        for i in range(61)
    ]
    db = _db(tmp_path, rows)
    series = load_series(_metric(), db, BASE - timedelta(minutes=60), BASE)
    # 窗口 [BASE-60min, BASE) 内有 60 个点，其中 1 个缺失被丢弃
    assert series[0].n == 59
    assert series[0].meta["n_missing"] == 1
    assert not np.isnan(series[0].values).any()


def test_interpolate_policy_fills_gaps(tmp_path):
    rows = [
        ((BASE - timedelta(minutes=60 - i)).isoformat(), "a", None if i == 5 else float(i))
        for i in range(61)
    ]
    db = _db(tmp_path, rows)
    series = load_series(
        _metric(missing_policy="interpolate"), db, BASE - timedelta(minutes=60), BASE
    )
    assert series[0].n == 60
    assert not np.isnan(series[0].values).any()
    assert series[0].meta["n_missing"] == 1
    # 线性插值后第 5 个点应落在 4 与 6 之间
    assert 4.0 < series[0].values[5] < 6.0


def test_error_policy_rejects_missing_values(tmp_path):
    rows = [
        ((BASE - timedelta(minutes=60 - i)).isoformat(), "a", None if i == 5 else float(i))
        for i in range(61)
    ]
    db = _db(tmp_path, rows)
    with pytest.raises(ValueError, match="缺失"):
        load_series(
            _metric(missing_policy="error"), db, BASE - timedelta(minutes=60), BASE
        )


def test_all_missing_series_is_reported_as_insufficient(tmp_path):
    rows = [
        ((BASE - timedelta(minutes=60 - i)).isoformat(), "a", None) for i in range(61)
    ]
    db = _db(tmp_path, rows)
    series = load_series(_metric(), db, BASE - timedelta(minutes=60), BASE)
    assert series[0].n == 0
    assert series[0].meta["n_missing"] == 60
    assert series[0].meta["sufficient"] is False


# ---------- #2/#3 时区 ----------


def test_source_with_offset_timestamps_is_queried_correctly(tmp_path):
    """源库存 +08:00 偏移的时间戳时，julianday 会正确换算成 UTC 再比较。"""
    tz8 = timezone(timedelta(hours=8))
    rows = [
        ((BASE - timedelta(minutes=60 - i)).astimezone(tz8).isoformat(), "a", float(i))
        for i in range(61)
    ]
    db = _db(tmp_path, rows)
    series = load_series(
        _metric(time_format="iso_utc"),
        db,
        BASE - timedelta(minutes=60),
        BASE,
    )
    assert series[0].n == 60


def test_naive_timestamps_use_declared_timezone(tmp_path):
    """源库存的是墙钟时间，必须按 source_timezone 换算边界，否则整段取不到。"""
    tz8 = timezone(timedelta(hours=8))
    wall = [
        (BASE - timedelta(minutes=60 - i)).astimezone(tz8).replace(tzinfo=None).isoformat()
        for i in range(61)
    ]
    rows = [(ts, "a", float(i)) for i, ts in enumerate(wall)]
    db = _db(tmp_path, rows)
    series = load_series(
        _metric(time_format="iso_naive", source_timezone="Asia/Shanghai"),
        db,
        BASE - timedelta(minutes=60),
        BASE,
    )
    assert series[0].n == 60


def test_naive_timestamps_without_declared_timezone_are_wrong(tmp_path):
    """反面用例：同一份墙钟数据，若不声明时区就会取错区间。"""
    tz8 = timezone(timedelta(hours=8))
    wall = [
        (BASE - timedelta(minutes=60 - i)).astimezone(tz8).replace(tzinfo=None).isoformat()
        for i in range(61)
    ]
    rows = [(ts, "a", float(i)) for i, ts in enumerate(wall)]
    db = _db(tmp_path, rows)
    series = load_series(
        _metric(time_format="iso_naive", source_timezone="UTC"),
        db,
        BASE - timedelta(minutes=60),
        BASE,
    )
    # 声明错了时区会取不到数据（空结果 → 任务标记「数据不足」），而不是悄悄取错区间
    assert series == []


def test_utc_timestamps_with_offset_are_supported(tmp_path):
    rows = [
        ((BASE - timedelta(minutes=60 - i)).isoformat(), "a", float(i)) for i in range(61)
    ]
    db = _db(tmp_path, rows)
    series = load_series(
        _metric(time_format="iso_utc"), db, BASE - timedelta(minutes=60), BASE
    )
    assert series[0].n == 60


def test_epoch_seconds_still_work(tmp_path):
    rows = [
        (int((BASE - timedelta(minutes=60 - i)).timestamp()), "a", float(i)) for i in range(61)
    ]
    db = _db(tmp_path, rows)
    series = load_series(
        _metric(time_format="epoch_s"), db, BASE - timedelta(minutes=60), BASE
    )
    assert series[0].n == 60
