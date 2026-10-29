import sqlite3
from datetime import UTC, datetime

import numpy as np
import pytest

from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.sqlite_source import load_series


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    rows = []
    for i in range(30):
        ts = datetime(2026, 1, 1, tzinfo=UTC).replace(minute=i).isoformat()
        rows.append((ts, "a", float(i)))
        rows.append((ts, "b", float(i * 2)))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _metric(**overrides):
    base = {
        "id": 1,
        "source_id": 1,
        "name": "demo",
        "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        "time_column": "ts",
        "value_column": "value",
        "group_column": "host",
        "time_format": "iso",
        "freq": "1min",
        "created_at": "",
    }
    base.update(overrides)
    return Metric(**base)


def test_loads_and_splits_groups(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    series = load_series(_metric(), path, start, end)
    assert [s.series_id for s in series] == ["demo:a", "demo:b"]
    assert [s.n for s in series] == [30, 30]
    assert series[0].meta["group"] == "a"
    assert series[0].timestamps.dtype == np.dtype("datetime64[ns]")
    assert series[0].values[3] == 3.0


def test_timefilter_limits_rows(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    start = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    end = datetime(2026, 1, 1, 0, 20, tzinfo=UTC)
    series = load_series(_metric(), path, start, end)
    assert all(s.n == 10 for s in series)


def test_single_series_when_no_group_column(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    metric = _metric(query="SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
                     group_column=None)
    series = load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC),
                          datetime(2026, 1, 2, tzinfo=UTC))
    assert len(series) == 1
    assert series[0].series_id == "demo"
    assert series[0].meta["group"] is None


def test_rejects_non_select_query(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    metric = _metric(query="DELETE FROM metrics WHERE $timefilter")
    with pytest.raises(ValueError, match="SELECT"):
        load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC))


def test_rejects_write_keyword(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    metric = _metric(query="SELECT ts, value FROM metrics WHERE $timefilter; DROP TABLE metrics")
    with pytest.raises(ValueError, match="单条语句"):
        load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC))


def test_missing_group_column_returns_error(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    metric = _metric(group_column="missing")
    with pytest.raises(ValueError, match="group_column"):
        load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC))


def test_missing_source_file_raises(tmp_path):
    metric = _metric()
    with pytest.raises(FileNotFoundError, match="不存在"):
        load_series(metric, tmp_path / "nope.db", datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 2, tzinfo=UTC))


def test_epoch_time_format(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metrics (ts INTEGER, host TEXT, value REAL)")
    base = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    conn.executemany(
        "INSERT INTO metrics VALUES (?, ?, ?)",
        [(base + 60 * i, "a", float(i)) for i in range(10)],
    )
    conn.commit()
    conn.close()
    metric = _metric(query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
                     time_format="epoch_s")
    series = load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC),
                          datetime(2026, 1, 1, 0, 10, tzinfo=UTC))
    assert series[0].n == 10
    assert series[0].values[-1] == 9.0
