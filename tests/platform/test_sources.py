"""连接器层的共用后处理与时间字面量。"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.sources.base import (
    series_from_frame,
    sql_literal,
    time_literal,
)


def _metric(**overrides) -> Metric:
    base = {
        "id": 1,
        "source_id": 1,
        "name": "demo",
        "query": "SELECT ts, value FROM t WHERE $timefilter",
        "time_column": "ts",
        "value_column": "value",
        "group_column": None,
        "time_format": "iso_utc",
        "freq": "5min",
        "created_at": "2026-10-30T00:00:00+00:00",
        "source_timezone": "UTC",
        "missing_policy": "drop",
    }
    base.update(overrides)
    return Metric(**base)


def test_empty_frame_returns_no_series():
    assert series_from_frame(pd.DataFrame(), _metric()) == []


def test_missing_value_column_raises():
    frame = pd.DataFrame({"ts": ["2026-10-30T00:00:00+00:00"], "other": [1]})
    with pytest.raises(ValueError, match="缺少 value_column"):
        series_from_frame(frame, _metric())


def test_missing_group_column_raises():
    frame = pd.DataFrame(
        {"ts": ["2026-10-30T00:00:00+00:00"], "value": [1.0], "other": [2]}
    )
    with pytest.raises(ValueError, match="缺少 group_column"):
        series_from_frame(frame, _metric(group_column="host"))


def test_split_by_group_column():
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:00:00+00:00",
            ],
            "value": [1.0, 2.0],
            "host": ["web-1", "web-2"],
        }
    )
    series = series_from_frame(frame, _metric(group_column="host"))
    assert [item.series_id for item in series] == ["demo:web-1", "demo:web-2"]
    assert series[0].meta["group"] == "web-1"
    assert series[0].meta["sufficient"] is False  # 只有 1 个点，不足 10


def test_missing_value_dropped_by_policy():
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:05:00+00:00",
            ],
            "value": [1.0, None],
        }
    )
    series = series_from_frame(frame, _metric(missing_policy="drop"))
    assert len(series[0].values) == 1
    assert len(series[0].timestamps) == 1
    assert series[0].meta["n_missing"] == 1


def test_missing_value_interpolated_keeps_all_points():
    """⚠️ interpolate 策略下**值与时间戳长度必须都保持原样**。

    只对 drop 策略过滤时间戳 —— 否则 values 与 timestamps 长度不一致，
    `SeriesBundle.__post_init__` 会抛错。
    """
    frame = pd.DataFrame(
        {
            "ts": [
                "2026-10-30T00:00:00+00:00",
                "2026-10-30T00:05:00+00:00",
                "2026-10-30T00:10:00+00:00",
            ],
            "value": [1.0, None, 3.0],
        }
    )
    series = series_from_frame(frame, _metric(missing_policy="interpolate"))
    assert len(series[0].values) == 3
    assert len(series[0].timestamps) == 3
    assert series[0].meta["n_missing"] == 1


def test_missing_policy_error_raises():
    frame = pd.DataFrame(
        {
            "ts": ["2026-10-30T00:00:00+00:00", "2026-10-30T00:05:00+00:00"],
            "value": [1.0, None],
        }
    )
    with pytest.raises(ValueError, match="缺失值"):
        series_from_frame(frame, _metric(missing_policy="error"))


def test_time_literal_iso_utc_matches_to_iso_format():
    """⚠️ 必须与平台的 to_iso() 同格式 —— T 分隔 + +00:00 偏移。

    用 Z 会让字符串字典序与时间序不一致（'+'0x2B < 'Z'0x5A），边界行被误判。
    """
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert time_literal(value, "iso_utc", "UTC") == "2026-10-30T09:38:00+00:00"


def test_time_literal_epoch_formats():
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert time_literal(value, "epoch_s", "UTC") == "1793353080"
    assert time_literal(value, "epoch_ms", "UTC") == "1793353080000"


def test_sql_literal_quotes_strings_but_not_numbers():
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert sql_literal(value, "iso_utc", "UTC") == "'2026-10-30T09:38:00+00:00'"
    assert sql_literal(value, "epoch_s", "UTC") == "1793353080"


def test_time_literal_rejects_unknown_format():
    with pytest.raises(ValueError, match="不支持的 time_format"):
        time_literal(datetime(2026, 1, 1, tzinfo=UTC), "nope", "UTC")
