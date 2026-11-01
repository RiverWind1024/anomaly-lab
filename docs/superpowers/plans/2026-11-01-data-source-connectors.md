# 数据源连接器与数据浏览器 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「只能连本地 SQLite」扩成「能连任意 SQL-over-HTTP 网关」，并加一个数据浏览器 —— 写 SQL → 看列结构与前 N 行 → 一键生成指标。

**Architecture:** 新增 `anomaly_lab.platform.sources` 包，把现有 `sqlite_source.load_series` 切成「连接器（SQL → DataFrame）」+「共用后处理（DataFrame → 序列）」两段。新增 `http_sql` 连接器：把指标 SQL 原样发给远端 SQL 网关，取回表格。`$timefilter` 的替换**由连接器自己渲染**（SQLite 用 `julianday()` 参数绑定，HTTP 用按 `time_format` 生成的字面量）—— 浏览预览与指标运行时走同一条路，结果必然一致。新增 `POST /api/platform/sources/{id}/query` 端点供前端的数据浏览器使用。

**Tech Stack:** Python 3.12、SQLite（标准库）、pandas、numpy、FastAPI、pytest；前端 React + TypeScript + antd + vitest。

**Spec:** `docs/superpowers/specs/2026-11-01-data-source-connectors-design.md`

---

## 设计边界（已与用户确认）

- 数据源类型：`sqlite`（现有）+ `http`（新增，SQL 透传）。**只做 SQL 型**；InfluxDB 2.x / Prometheus 的专有查询语言留到后续（spec §12 预留了协议位置）。
- 接口型数据源走**实时拉取**（不落本地缓存）。
- **零新依赖**：HTTP 客户端用标准库 `urllib.request`（项目 `data/public.py` 已有先例）；响应解析用已有的 pandas。
- 密钥脱敏在 **store 层**做；前端回写脱敏值时后端保留原值。
- 浏览与指标**共用同一套时间条件替换**（连接器渲染）→ 预览结果 == 运行时取数结果。
- 本轮**不做**「假远端时序数据库」（持续产数 + InfluxDB 形状的 SQL 端点）—— 那是 spec 2。本轮用 pytest 夹具起一个假 HTTP 端点验证透传路径。
- 非目标：告警外发、认证、检测记录筛选分页、容器化。

## 关键接口（实现时以这份为准）

```python
# src/anomaly_lab/platform/sources/base.py

@dataclass(frozen=True)
class TimeContext:
    """替换 `$timefilter` 所需的上下文。"""

    column: str
    fmt: str
    timezone: str
    start: datetime
    end: datetime


class SourceConnector(Protocol):
    kind: str

    def describe(self) -> str: ...

    def test_connection(self) -> tuple[bool, str]: ...

    def build_time_condition(self, ctx: TimeContext) -> tuple[str, tuple]:
        """渲染本方言的时间条件，返回 (SQL 片段, 绑定参数)。"""

    def execute_sql(
        self, sql: str, *, limit: int | None = None, params: tuple = ()
    ) -> pd.DataFrame: ...

    def fetch(self, metric: Metric, start: datetime, end: datetime) -> pd.DataFrame: ...
```

| 机制 | 用于 | 渲染者 |
|---|---|---|
| `$timefilter` | 指标 SQL、浏览 SQL | **连接器**（`build_time_condition`）—— SQLite 用 `julianday()`，HTTP 用字面量 |
| `{start}` / `{end}` | 浏览 SQL（用户自己写列名） | `base.sql_literal`（共享，与方言无关） |

## 文件结构

```
src/anomaly_lab/platform/
  sources/
    __init__.py        # 新增：注册表 get_connector / SUPPORTED_KINDS
    base.py            # 新增：共用后处理 + 时间字面量 + TimeContext
    sqlite.py          # 新增：SQLite 连接器
    http_sql.py        # 新增：HTTP 透传连接器
  sqlite_source.py     # 改：变薄壳（再导出 load_series，既有测试零改动）
  models.py            # 改：Source 加 config 字段
  store.py             # 改：config 列 + 解码 + 脱敏 + kind 枚举
  validation.py        # 改：校验拆分 + kind/config 校验
  runner.py            # 改：经连接器取数
src/anomaly_lab/web/
  platform_routes.py   # 改：SourceIn/SourcePatchIn 加 config；compare/suggestion 走连接器
  source_query_routes.py  # 新增：数据浏览端点（单独文件，避免 platform_routes 膨胀）
  app.py               # 改：挂上第二个 router
frontend/src/
  api/types.ts         # 改：CatalogSource 加 config（可选）、新增 QueryResult 类型
  api/platform.ts      # 改：createSource/updateSource 带 config、新增 querySource
  features/sources/SourceForm.tsx   # 改：kind 改 Select、http 时显示 config 字段
  features/sources/DataBrowser.tsx   # 新增：SQL 编辑器 + 结果表格
  pages/SourceDetailPage.tsx        # 改：挂 DataBrowser
  features/metrics/MetricForm.tsx   # 改：支持 initialValues 传入（从浏览结果建指标）
tests/platform/
  test_sources.py      # 新增：共用后处理 + 时间字面量 + 校验拆分 + 注册表
  test_http_source.py  # 新增：HTTP 连接器（用假 HTTP 端点夹具）
tests/web/
  test_source_query.py # 新增：浏览端点
```

## Chunk 1: 后端地基

### Task 1: 抽出共用后处理与时间字面量

**Files:**
- Create: `src/anomaly_lab/platform/sources/__init__.py`
- Create: `src/anomaly_lab/platform/sources/base.py`
- Create: `src/anomaly_lab/platform/sources/sqlite.py`
- Modify: `src/anomaly_lab/platform/sqlite_source.py`
- Test: `tests/platform/test_sources.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/platform/test_sources.py`：

```python
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
    base = dict(
        id=1,
        source_id=1,
        name="demo",
        query="SELECT ts, value FROM t WHERE $timefilter",
        time_column="ts",
        value_column="value",
        group_column=None,
        time_format="iso_utc",
        freq="5min",
        created_at="2026-10-30T00:00:00+00:00",
        source_timezone="UTC",
        missing_policy="drop",
    )
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
    assert time_literal(value, "epoch_s", "UTC") == "1793261880"
    assert time_literal(value, "epoch_ms", "UTC") == "1793261880000"


def test_sql_literal_quotes_strings_but_not_numbers():
    value = datetime(2026, 10, 30, 9, 38, 0, tzinfo=UTC)
    assert sql_literal(value, "iso_utc", "UTC") == "'2026-10-30T09:38:00+00:00'"
    assert sql_literal(value, "epoch_s", "UTC") == "1793261880"


def test_time_literal_rejects_unknown_format():
    with pytest.raises(ValueError, match="不支持的 time_format"):
        time_literal(datetime(2026, 1, 1, tzinfo=UTC), "nope", "UTC")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_sources.py -q -p no:warnings`
Expected: FAIL —— `ModuleNotFoundError: No module named 'anomaly_lab.platform.sources'`

- [ ] **Step 3: 写 `sources/base.py`**

创建 `src/anomaly_lab/platform/sources/base.py`：

```python
"""连接器层：统一的「SQL → DataFrame」入口，与方言无关的后处理。

每个连接器只负责「怎么把一段 SQL 变成一张表」；时间解析、排序、
group by 拆分、缺失策略在这里统一处理 —— 它们只依赖 pandas，不依赖方言。

⚠️ 拆分的理由：原 `sqlite_source.load_series` 把「取数」与「后处理」混在一个
   函数里，换一种数据源就要复制一遍后处理逻辑。切分点在
   `pd.DataFrame(rows, columns=columns)` 之后。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric

MAX_ROWS = 100_000
MIN_VALID_POINTS = 10


@dataclass(frozen=True)
class TimeContext:
    """替换 `$timefilter` 所需的上下文。"""

    column: str
    fmt: str
    timezone: str
    start: datetime
    end: datetime


def _group_label(value: object) -> str:
    """分组值的显示形式：None → "null"，空串 → "null"。"""
    text = str(value)
    return text if text else "null"


def _wall_clock(value: datetime, timezone_name: str) -> str:
    """把 UTC 时刻转成源库时区的墙钟字符串（不带时区后缀）。"""
    local = value.astimezone(ZoneInfo(timezone_name))
    return local.replace(tzinfo=None).isoformat(sep=" ")


def _parse_time_column(frame: pd.DataFrame, metric: Metric) -> pd.Series:
    """按 `time_format` 把时间列解析成 UTC 时间戳。

    ⚠️ 时间语义不猜 —— 存储形式由 `time_format` 声明，
       无时区时间戳按 `source_timezone` 解释（对应 CloudWatch 的 MetricTimezone）。
    """
    column = metric.time_column
    if metric.time_format == "iso_utc":
        return pd.to_datetime(frame[column], utc=True)
    if metric.time_format == "iso_naive":
        naive = pd.to_datetime(frame[column], utc=False)
        if naive.dt.tz is not None:
            naive = naive.dt.tz_convert(None)
        return naive.dt.tz_localize(ZoneInfo(metric.source_timezone)).dt.tz_convert("UTC")
    unit = "s" if metric.time_format == "epoch_s" else "ms"
    numeric = pd.to_numeric(frame[column], errors="raise")
    return pd.to_datetime(numeric, unit=unit, utc=True)


def _apply_missing_policy(
    values: pd.Series, policy: str, series_id: str
) -> tuple[np.ndarray, int]:
    """返回 (处理后的值, 缺失个数)。非数字的非空值一律报错，不当缺失处理。"""
    raw = values
    numeric = pd.to_numeric(raw, errors="coerce")
    invalid = raw.notna() & numeric.isna()
    if invalid.any():
        bad = raw[invalid].iloc[0]
        raise ValueError(f"序列 {series_id} 的值列包含非数字内容: {bad!r}")
    missing = numeric.isna()
    n_missing = int(missing.sum())
    if n_missing and policy == "error":
        raise ValueError(f"序列 {series_id} 有 {n_missing} 个缺失值（missing_policy=error）")
    if policy == "interpolate" and n_missing:
        numeric = numeric.interpolate(limit_direction="both")
    if policy == "drop" and n_missing:
        numeric = numeric.dropna()
    return numeric.to_numpy(dtype=float), n_missing


def time_literal(value: datetime, fmt: str, timezone_name: str) -> str:
    """把时刻渲染成**裸值**（不含引号）。

    ⚠️ `iso_utc` 用 **T 分隔 + `+00:00` 偏移**，与平台的 `to_iso()` 完全一致 ——
       同一偏移、同一格式下**字符串字典序 == 时间序**，边界比较才正确。
       用 `Z` 会让 `'+'`(0x2B) < `'Z'`(0x5A) → 边界行被误判。
    """
    if fmt == "iso_utc":
        return value.astimezone(UTC).isoformat(timespec="seconds")
    if fmt == "iso_naive":
        return (
            value.astimezone(ZoneInfo(timezone_name))
            .replace(tzinfo=None)
            .isoformat(timespec="seconds")
        )
    if fmt == "epoch_s":
        return str(int(value.timestamp()))
    if fmt == "epoch_ms":
        return str(int(value.timestamp() * 1000))
    raise ValueError(f"不支持的 time_format: {fmt}")


def sql_literal(value: datetime, fmt: str, timezone_name: str) -> str:
    """把时刻渲染成**可直接嵌进 SQL 的字面量**（字符串加引号，数字不加）。"""
    text = time_literal(value, fmt, timezone_name)
    if fmt in {"epoch_s", "epoch_ms"}:
        return text
    return f"'{text}'"


def time_filter_parts(
    column: str, fmt: str, timezone_name: str, start: datetime, end: datetime
) -> tuple[str, tuple]:
    """**SQLite 方言**的时间条件（参数绑定）。

    ⚠️ 只对 SQLite 有效 —— `julianday()` 是 SQLite 专有函数。
       其它方言由各自的连接器渲染（见 `HttpSqlConnector.build_time_condition`）。
    """
    quoted = f'"{column}"'
    if fmt in {"iso_utc", "iso_naive"}:
        if fmt == "iso_utc":
            low = start.astimezone(UTC).isoformat(sep=" ")
            high = end.astimezone(UTC).isoformat(sep=" ")
        else:
            # 源库存的是源时区的墙钟时间，边界也要换算成墙钟再比较
            low = _wall_clock(start, timezone_name)
            high = _wall_clock(end, timezone_name)
        # julianday 让 SQLite 按时间语义比较，避开 ISO 字符串字典序的坑
        condition = (
            f"julianday({quoted}) >= julianday(?) AND julianday({quoted}) < julianday(?)"
        )
        return condition, (low, high)
    if fmt == "epoch_s":
        low, high = int(start.timestamp()), int(end.timestamp())
    elif fmt == "epoch_ms":
        low, high = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    else:
        raise ValueError(f"不支持的 time_format: {fmt}")
    return f"{quoted} >= ? AND {quoted} < ?", (low, high)


def series_from_frame(frame: pd.DataFrame, metric: Metric) -> list[SeriesBundle]:
    """方言无关的后处理：解析时间列 → 排序 → group by 拆序列 → 缺失策略。

    契约：
    - 空表返回 `[]`
    - 缺 `value_column` / `group_column` 列 → `ValueError`
    - 每条序列的 `meta` 含 metric_id / metric_name / group / source_id /
      n_missing / n_valid / sufficient
    - `values` 与 `timestamps` 长度永远一致（`drop` 策略下同步过滤）
    """
    if frame.empty:
        return []
    if metric.value_column not in frame.columns:
        raise ValueError(f"查询结果缺少 value_column: {metric.value_column}")
    if metric.group_column and metric.group_column not in frame.columns:
        raise ValueError(f"查询结果缺少 group_column: {metric.group_column}")

    frame = frame.copy()
    frame[metric.time_column] = _parse_time_column(frame, metric)
    frame = frame.sort_values(metric.time_column)

    if metric.group_column:
        parts = list(frame.groupby(metric.group_column, dropna=False))
    else:
        parts = [(None, frame)]

    result: list[SeriesBundle] = []
    for raw_group, part in parts:
        group = None if raw_group is None else _group_label(raw_group)
        series_id = metric.name if group is None else f"{metric.name}:{group}"
        values, n_missing = _apply_missing_policy(
            part[metric.value_column], metric.missing_policy, series_id
        )
        keep = ~part[metric.value_column].isna()
        # ⚠️ 只有 `drop` 策略过滤时间戳 —— interpolate 策略下值是插值出来的、
        #    点数不变，两边长度必须一致，否则 SeriesBundle 会抛「长度不一致」。
        if metric.missing_policy == "drop":
            timestamps = part[metric.time_column][keep].dt.tz_convert(None)
        else:
            timestamps = part[metric.time_column].dt.tz_convert(None)
        result.append(
            SeriesBundle(
                series_id=series_id,
                values=values,
                timestamps=timestamps.to_numpy(dtype="datetime64[ns]"),
                freq=metric.freq,
                meta={
                    "metric_id": metric.id,
                    "metric_name": metric.name,
                    "group": group,
                    "source_id": metric.source_id,
                    "n_missing": n_missing,
                    "n_valid": len(values),
                    "sufficient": bool(len(values) >= MIN_VALID_POINTS),
                },
            )
        )
    return sorted(result, key=lambda item: item.series_id)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/platform/test_sources.py -q -p no:warnings`
Expected: PASS（11 passed）

- [ ] **Step 5: 把 SQLite 取数搬进 `sources/sqlite.py`**

创建 `src/anomaly_lab/platform/sources/sqlite.py` —— 内容是把原
`sqlite_source.py` 的取数部分搬过来（`_connect` / `fetch_sqlite_series`），
再补一个连接器类：

```python
"""SQLite 连接器：本地文件，只读执行。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.base import (
    MAX_ROWS,
    TimeContext,
    series_from_frame,
    time_filter_parts,
)
from anomaly_lab.platform.validation import validate_identifier, validate_query


def _connect(path: Path) -> sqlite3.Connection:
    """以只读模式打开，避免用户查询意外写入源库。"""
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def fetch_sqlite_series(
    metric: Metric,
    source_path: Path,
    start: datetime,
    end: datetime,
) -> list[SeriesBundle]:
    """在 [start, end) 区间取数，按 group_column 拆成多条序列。"""
    query = validate_query(metric.query)
    validate_identifier(metric.time_column, "time_column")
    validate_identifier(metric.value_column, "value_column")
    if metric.group_column:
        validate_identifier(metric.group_column, "group_column")
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"数据源不存在: {path}")

    condition, params = time_filter_parts(
        metric.time_column, metric.time_format, metric.source_timezone, start, end
    )
    sql = f"SELECT * FROM ({query.replace('$timefilter', condition)}) LIMIT ?"
    with closing(_connect(path)) as conn:
        cursor = conn.execute(sql, (*params, MAX_ROWS + 1))
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError(f"单次查询超过 {MAX_ROWS} 行，请缩小窗口或增加聚合")

    frame = pd.DataFrame(rows, columns=columns)
    return series_from_frame(frame, metric)


class SqliteConnector:
    """SQLite 连接器。"""

    kind = "sqlite"

    def __init__(self, source: Source, data_root: Path) -> None:
        self.source = source
        self.data_root = Path(data_root)

    @property
    def path(self) -> Path:
        """源库路径。绝对路径直接用，相对路径拼 data_root。"""
        raw = Path(self.source.path)
        return raw if raw.is_absolute() else self.data_root / raw

    def describe(self) -> str:
        return f"SQLite {self.source.path}"

    def test_connection(self) -> tuple[bool, str]:
        if not self.path.exists():
            return False, f"数据源不存在: {self.path}"
        return True, "连接正常"

    def build_time_condition(self, ctx: TimeContext) -> tuple[str, tuple]:
        return time_filter_parts(ctx.column, ctx.fmt, ctx.timezone, ctx.start, ctx.end)

    def execute_sql(
        self, sql: str, *, limit: int | None = None, params: tuple = ()
    ) -> pd.DataFrame:
        """执行只读 SQL，返回表格。"""
        text = sql
        if limit is not None:
            text = f"SELECT * FROM ({sql}) LIMIT {int(limit)}"
        with closing(_connect(self.path)) as conn:
            cursor = conn.execute(text, params)
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        return pd.DataFrame(rows, columns=columns)

    def fetch(self, metric: Metric, start: datetime, end: datetime) -> pd.DataFrame:
        """取 [start, end) 的数据（做 `$timefilter` 替换）。"""
        query = validate_query(metric.query)
        validate_identifier(metric.time_column, "time_column")
        condition, params = self.build_time_condition(
            TimeContext(
                column=metric.time_column,
                fmt=metric.time_format,
                timezone=metric.source_timezone,
                start=start,
                end=end,
            )
        )
        sql = f"SELECT * FROM ({query.replace('$timefilter', condition)}) LIMIT ?"
        with closing(_connect(self.path)) as conn:
            cursor = conn.execute(sql, (*params, MAX_ROWS + 1))
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        if len(rows) > MAX_ROWS:
            raise ValueError(f"单次查询超过 {MAX_ROWS} 行，请缩小窗口或增加聚合")
        return pd.DataFrame(rows, columns=columns)
```

⚠️ `fetch` 里 `LIMIT ?` 与 `MAX_ROWS` 检查是**SQLite 专属**的（本地内存保护），
HTTP 侧不设限（数据在远端）。

- [ ] **Step 6: 让 `sqlite_source.py` 变薄壳**

把 `src/anomaly_lab/platform/sqlite_source.py` 整个替换为：

```python
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
```

⚠️ **不要**在这里 import `series_from_frame` —— 没用上会被 ruff 判 F401。

- [ ] **Step 7: 建 `sources/__init__.py` 空壳**

创建 `src/anomaly_lab/platform/sources/__init__.py`：

```python
"""连接器层。"""

from __future__ import annotations

__all__: list[str] = []
```

⚠️ Task 1 阶段 `get_connector` 还不存在 —— 写进 `__all__` 会被 ruff 判 F822。
Task 5 再补上。

- [ ] **Step 8: 跑既有测试确认零回归**

Run: `.venv/bin/python -m pytest tests/platform -q -p no:warnings`
Expected: PASS —— `test_sqlite_source.py` / `test_data_quality.py` /
`test_robustness.py` 仍从 `sqlite_source` 导入 `load_series`，且
`test_data_quality.py::test_interpolate_policy_fills_gaps` 必须通过
（这正是「interpolate 分支被改坏」的守门测试）

- [ ] **Step 9: 跑全量 + lint**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint`
Expected: PASS + All checks passed!

- [ ] **Step 10: 提交**

```bash
git add src/anomaly_lab/platform/sources src/anomaly_lab/platform/sqlite_source.py tests/platform/test_sources.py
git commit -m "refactor(platform): 抽出连接器层的共用后处理

把 sqlite_source.load_series 切成「取数」与「后处理」两段：
- 后处理（时间解析/排序/group by 拆分/缺失策略）搬到 sources/base.py，
  只依赖 pandas，与方言无关 —— 换数据源不必再复制一遍
- 取数搬进 sources/sqlite.py
- sqlite_source.py 变薄壳，既有测试与 monkeypatch 目标名零改动

base.py 同时提供：
- time_literal / sql_literal：按 time_format 生成 SQL 字面量
  （iso_utc 用 T 分隔 + '+00:00'，与 to_iso() 一致 ——
   同一偏移下字符串字典序 == 时间序，用 'Z' 会让边界行被误判）
- time_filter_parts：SQLite 方言的 julianday() 条件（参数绑定）
- TimeContext：让连接器各自渲染本方言的时间条件"
```

---

### Task 2: Source.config 字段 + store 层解码/脱敏/kind 枚举

**Files:**
- Modify: `src/anomaly_lab/platform/models.py`
- Modify: `src/anomaly_lab/platform/store.py`
- Modify: `src/anomaly_lab/platform/validation.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Test: `tests/platform/test_store.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/platform/test_store.py`：

```python
def test_source_config_roundtrip(tmp_path):
    """config 存 JSON，读出来是 dict。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/query?q={sql}", "format": "csv"},
    )
    source = store.get_source_raw(1)
    assert source.config["url"] == "https://x/query?q={sql}"
    assert source.config["format"] == "csv"


def test_source_config_defaults_to_empty(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    assert source.config == {}


def test_sqlite_source_requires_path(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="数据源路径"):
        store.add_source("local", "", kind="sqlite")


def test_http_source_requires_url(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="url"):
        store.add_source("remote", "", kind="http", config={"format": "csv"})


def test_unknown_kind_rejected(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="不支持的数据源类型"):
        store.add_source("x", "a.db", kind="kafka")


def test_config_is_redacted_in_reads(tmp_path):
    """密钥不能出现在读出来的 source 里。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/query?q={sql}",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    assert "secret-token" not in str(store.get_source(1).config)
    assert "secret-token" not in str(store.list_sources()[0].config)


def test_redacted_url_is_unchanged_when_no_secret(tmp_path):
    """没有密钥参数时，url 不能被重新编码 —— `{sql}` 会被变成 %7Bsql%7D。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/query?q={sql}"},
    )
    assert store.get_source(1).config["url"] == "https://x/query?q={sql}"


def test_update_keeps_original_secret_when_redacted_value_submitted(tmp_path):
    """前端提交脱敏值时，不能把真值覆盖掉。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/query?q={sql}",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    store.update_source(1, config={
        "url": "https://x/query?q={sql}",
        "headers": {"Authorization": "Bearer ••••"},
    })
    assert (
        store.get_source_raw(1).config["headers"]["Authorization"]
        == "Bearer secret-token"
    )


def test_update_without_config_keeps_stored_secret(tmp_path):
    """⚠️ 只改名字不能把密钥冲掉 —— update 必须读**未脱敏**的当前值。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/query?q={sql}",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    store.update_source(1, name="renamed")
    assert (
        store.get_source_raw(1).config["headers"]["Authorization"]
        == "Bearer secret-token"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_store.py -q -p no:warnings`
Expected: FAIL —— `add_source() got an unexpected keyword argument 'config'`

- [ ] **Step 3: 改 `models.py`**

```python
@dataclass(frozen=True)
class Source:
    """一个数据源。

    ⚠️ `config` 存 kind 专属参数（JSON）—— SQLite 用 `path` 列，
       HTTP 源用 config 里的 url / method / headers / format 等。
    """

    id: int
    name: str
    kind: str
    path: str
    created_at: str
    config: dict = field(default_factory=dict)
```

⚠️ `config` **必须放最后**且带默认值 —— 现有字段全是必填。

- [ ] **Step 4: 改 `validation.py`**

追加：

```python
SUPPORTED_SOURCE_KINDS = ("sqlite", "http")


def validate_kind(value: str) -> str:
    """数据源类型。"""
    if value not in SUPPORTED_SOURCE_KINDS:
        raise ValueError(
            f"不支持的数据源类型: {value!r}（可选 {list(SUPPORTED_SOURCE_KINDS)}）"
        )
    return value


def validate_http_config(config: dict) -> dict:
    """HTTP 数据源的配置。"""
    if not isinstance(config, dict):
        raise ValueError("HTTP 数据源的 config 必须是对象")
    url = config.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("HTTP 数据源必须配置 url")
    method = str(config.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise ValueError(f"不支持的 method: {method}（可选 GET / POST）")
    fmt = str(config.get("format", "json"))
    if fmt not in {"json", "csv", "jsonl"}:
        raise ValueError(f"不支持的 format: {fmt}（可选 json / csv / jsonl）")
    timeout = config.get("timeout_seconds", 30)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("timeout_seconds 必须是正数")
    return config
```

- [ ] **Step 5: 改 `store.py`**

5.1 顶部加 `import json`（若还没有）与
`from dataclasses import replace`、`from anomaly_lab.platform.validation import validate_http_config, validate_kind`。

5.2 `_migrate` 里加列：

```python
        source_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sources)")
        }
        if "config" not in source_columns:
            conn.execute(
                "ALTER TABLE sources ADD COLUMN config TEXT NOT NULL DEFAULT '{}'"
            )
```

5.3 模块级辅助（放在 `PlatformStore` 类之前）：

```python
REDACTED = "••••"
_SECRET_KEYS = ("token", "key", "password", "secret", "authorization")


def _redact_url(url: str) -> str:
    """把 URL 里的 token/key/password 参数替换成哨兵值。

    ⚠️ **没有密钥参数时原样返回** —— 重新编码会把 `{sql}` 变成 `%7Bsql%7D`，
       模板就废了。
    """
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parts = urlparse(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    redacted = [
        (key, REDACTED if key.lower() in _SECRET_KEYS else value)
        for key, value in pairs
    ]
    if redacted == pairs:
        return url
    return urlunparse(parts._replace(query=urlencode(redacted)))


def _redact_config(config: dict) -> dict:
    """把 config 里的凭据替换成哨兵值。

    ⚠️ 脱敏在 store 层做 —— 前端拿不到原值，
       「保留原值」这类合并规则只能后端实现。
    """
    out = dict(config)
    headers = out.get("headers")
    if isinstance(headers, dict):
        out["headers"] = {
            key: (f"{str(value).split(' ', 1)[0]} {REDACTED}" if " " in str(value) else REDACTED)
            for key, value in headers.items()
        }
    body = out.get("body")
    if isinstance(body, dict):
        out["body"] = {
            key: (REDACTED if str(key).lower() in _SECRET_KEYS else value)
            for key, value in body.items()
        }
    url = out.get("url")
    if isinstance(url, str):
        out["url"] = _redact_url(url)
    return out


def _merge_config(old: dict, new: dict) -> dict:
    """合并配置：新值等于旧值的脱敏形式时，沿用旧值。

    ⚠️ 前端拿不到原值，只能把脱敏值原样传回来 ——
       这时必须识别出来，不能把真值覆盖成 '••••'。
    """
    redacted_old = _redact_config(old)
    merged = dict(new)
    for key in ("headers", "body"):
        old_map = old.get(key)
        new_map = new.get(key)
        if not isinstance(old_map, dict) or not isinstance(new_map, dict):
            continue
        combined = dict(old_map)
        for name, value in new_map.items():
            if name in old_map and value == redacted_old.get(key, {}).get(name):
                continue  # 脱敏值 → 保留原值
            combined[name] = value
        merged[key] = combined
    url = new.get("url")
    if isinstance(url, str) and url == redacted_old.get("url"):
        merged["url"] = old.get("url")
    return merged
```

5.4 `PlatformStore` 里加 `_to_source` 并替换三处 `Source(**dict(row))`：

```python
    @staticmethod
    def _to_source(row) -> Source:
        """行 → Source。config 列是 JSON 文本，这里解成 dict。"""
        data = dict(row)
        raw = data.pop("config", None) or "{}"
        data["config"] = json.loads(raw) if raw else {}
        return Source(**data)
```

5.5 `add_source`：

```python
    def add_source(
        self,
        name: str,
        path: str,
        kind: str = "sqlite",
        config: dict | None = None,
    ) -> Source:
        name = validate_name(name, "数据源名称")
        kind = validate_kind(kind)
        config = config or {}
        if kind == "sqlite":
            path = validate_name(path, "数据源路径")
        else:
            path = path.strip()
            validate_http_config(config)
        created_at = to_iso(utcnow())
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO sources (name, kind, path, created_at, config) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, kind, path, created_at, json.dumps(config, ensure_ascii=False)),
                )
                source_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"数据源名称已存在: {name}") from exc
        return self.get_source(source_id)
```

5.6 `update_source` —— ⚠️ **必须读未脱敏的当前值**：

```python
    def update_source(
        self,
        source_id: int,
        *,
        name: str | None = None,
        path: str | None = None,
        kind: str | None = None,
        config: dict | None = None,
    ) -> Source:
        """改数据源。只传要改的字段，其余保持原样。

        ⚠️ 已经跑过的运行记录不受影响 —— run 的结果早已落盘。
           改动只在**下一次**运行任务时生效。
        """
        current = self.get_source_raw(source_id)  # ⚠️ 未脱敏 —— 否则密钥会被冲掉
        new_name = validate_name(name if name is not None else current.name, "数据源名称")
        new_kind = validate_kind(kind if kind is not None else current.kind)
        new_path = path if path is not None else current.path
        if new_kind == "sqlite":
            new_path = validate_name(new_path, "数据源路径")
        else:
            new_path = new_path.strip()
        new_config = (
            current.config if config is None else _merge_config(current.config, config)
        )
        if new_kind == "http":
            validate_http_config(new_config)
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE sources SET name = ?, path = ?, kind = ?, config = ? WHERE id = ?",
                    (
                        new_name,
                        new_path,
                        new_kind,
                        json.dumps(new_config, ensure_ascii=False),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"数据源名称已存在: {new_name}") from exc
        return self.get_source(source_id)
```

5.7 读取方法 —— 公开的脱敏，内部的原值：

```python
    def get_source(self, source_id: int) -> Source:
        """取数据源（**已脱敏**）—— 给 API 用。"""
        source = self.get_source_raw(source_id)
        return replace(source, config=_redact_config(source.config))

    def get_source_raw(self, source_id: int) -> Source:
        """取数据源（**未脱敏**）—— 给内部逻辑用（取数、合并配置）。"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise ValueError(f"数据源不存在: {source_id}")
        return self._to_source(row)

    def list_sources(self) -> list[Source]:
        """列数据源（**已脱敏**）—— `catalog` 端点走这里。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        return [
            replace(self._to_source(row), config=_redact_config(self._to_source(row).config))
            for row in rows
        ]

    def find_source_by_name(self, name: str) -> Source | None:
        """按名字找（**已脱敏**）。"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        source = self._to_source(row)
        return replace(source, config=_redact_config(source.config))
```

⚠️ `list_sources` 里 `_to_source` 被调了两次 —— 改成先建列表再脱敏更清楚：

```python
    def list_sources(self) -> list[Source]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        sources = [self._to_source(row) for row in rows]
        return [replace(s, config=_redact_config(s.config)) for s in sources]
```

5.8 `runner.py` 里取源的地方改用 `get_source_raw`（Task 5 会大改，这里先改对）：

```python
        source = store.get_source_raw(metric.source_id)
```

- [ ] **Step 6: 改 `platform_routes.py` 的 SourceIn / SourcePatchIn**

```python
class SourceIn(BaseModel):
    name: str
    path: str = ""
    kind: str = "sqlite"
    config: dict | None = None


class SourcePatchIn(BaseModel):
    """数据源更新：**全部可选** —— 只传要改的字段。"""

    name: str | None = None
    path: str | None = None
    kind: str | None = None
    config: dict | None = None
```

⚠️ `path` 的默认值改成 `""` —— HTTP 源没有路径。
⚠️ `path` 的 `required` 校验由 store 按 kind 分支做（前端表单也按 kind 显示）。

并把 `create_source` / `patch_source` 改成转发 `config`：

```python
    @router.post("/api/platform/sources")
    def create_source(payload: SourceIn) -> dict:
        try:
            source = _store().add_source(
                payload.name, payload.path, payload.kind, payload.config or {}
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(source)
```

```python
    @router.patch("/api/platform/sources/{source_id}")
    def patch_source(source_id: int, payload: SourcePatchIn) -> dict:
        try:
            source = _store().update_source(
                source_id,
                name=payload.name,
                path=payload.path,
                kind=payload.kind,
                config=payload.config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(source)
```

⚠️ `update_source` 的 `config=None` 表示「不改」；若前端要清空 config，
传 `{}`（空 dict）—— `_merge_config(old, {})` 会得到 `{}` ✓。

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/platform/test_store.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 8: 跑全量 + lint**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint`
Expected: PASS + All checks passed!

⚠️ 若 `tests/web/` 里有测试断言 `POST /api/platform/sources` 必须带 `path`，
需要按新的「按 kind 分支」语义调整。

- [ ] **Step 9: 提交**

```bash
git add src/anomaly_lab/platform/models.py src/anomaly_lab/platform/store.py src/anomaly_lab/platform/validation.py src/anomaly_lab/platform/runner.py src/anomaly_lab/web/platform_routes.py tests/platform/test_store.py
git commit -m "feat(platform): 数据源支持 kind 专属的 config 配置

新增 HTTP 透传数据源需要存 url / method / headers / format 等参数，
但 sources 表只有 path 一个字段 —— 塞进去会与 SQLite 源的语义冲突。

- 新增 config 列（JSON），_migrate 里 ALTER TABLE 补老库
- Source.config 字段放最后且带默认值（现有字段全是必填）
- store 层解码 JSON（Source(**dict(row)) 直接用会拿到 str）
- kind 收敛为枚举（sqlite / http），非法 kind 被拒
- 校验按 kind 分支：sqlite 必须有 path，http 必须有 url
- 脱敏在 store 层：headers / body / url 里的凭据替换成哨兵值
  ⚠️ url 没有密钥参数时原样返回 —— 重新编码会把 {sql} 变成 %7Bsql%7D
- get_source / list_sources 脱敏，get_source_raw 给内部用
  ⚠️ update_source 必须读未脱敏的当前值，否则改个名字就把密钥冲掉了
- _merge_config：前端提交脱敏值 → 保留原值"
```

---

### Task 3: 校验拆分

**Files:**
- Modify: `src/anomaly_lab/platform/validation.py`
- Test: `tests/platform/test_sources.py`（追加）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/platform/test_sources.py`：

```python
from anomaly_lab.platform.validation import validate_query, validate_readonly_sql


def test_readonly_sql_does_not_require_timefilter():
    """浏览用的 SQL 不该强制带 $timefilter —— 那是指标的要求。"""
    assert validate_readonly_sql("SELECT ts, value FROM t LIMIT 10")


def test_readonly_sql_rejects_non_select():
    with pytest.raises(ValueError, match="SELECT 或 WITH"):
        validate_readonly_sql("DELETE FROM t")


def test_readonly_sql_rejects_multiple_statements():
    with pytest.raises(ValueError, match="单条语句"):
        validate_readonly_sql("SELECT 1; SELECT 2")


def test_readonly_sql_rejects_write_keywords():
    """⚠️ 输入必须以 SELECT 开头 —— 否则先撞上「必须以 SELECT 开头」那条。

    写关键字藏在 SELECT 里（子查询 / UNION）才是真正要拦的。
    """
    with pytest.raises(ValueError, match="写操作"):
        validate_readonly_sql("SELECT id FROM t WHERE id IN (SELECT id FROM drop)")


def test_metric_query_still_requires_exactly_one_timefilter():
    with pytest.raises(ValueError, match="timefilter"):
        validate_query("SELECT ts FROM t")
    with pytest.raises(ValueError, match="timefilter"):
        validate_query("SELECT ts FROM t WHERE $timefilter AND x = $timefilter")
    assert validate_query("SELECT ts FROM t WHERE $timefilter")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_sources.py -q -p no:warnings`
Expected: FAIL —— `ImportError: cannot import name 'validate_readonly_sql'`

- [ ] **Step 3: 实现拆分**

修改 `src/anomaly_lab/platform/validation.py`：

```python
def validate_readonly_sql(sql: str) -> str:
    """校验只读查询，返回去掉尾分号的查询文本。

    ⚠️ **不要求** `$timefilter` —— 那是指标 SQL 的要求，
       浏览用的 SQL 应该是自由的。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("查询不能为空")
    text = sql.strip().rstrip(";").strip()
    if not text.lower().startswith(("select", "with")):
        raise ValueError("查询必须以 SELECT 或 WITH 开头")
    if ";" in text:
        raise ValueError("查询只允许单条语句")
    clean = _LITERAL.sub("''", text)
    if _FORBIDDEN.search(clean):
        raise ValueError("查询包含不允许的写操作关键字")
    return text


def validate_query(query: str) -> str:
    """校验指标查询：只读 + 必须恰好一个 `$timefilter`。

    ⚠️ 语义与拆分前**完全一致** —— 现有调用方零改动。
    """
    text = validate_readonly_sql(query)
    if text.count("$timefilter") != 1:
        raise ValueError("查询必须且只能包含一个 $timefilter")
    return text
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/platform -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: 跑全量 + lint + 提交**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint`
Expected: PASS + All checks passed!

```bash
git add src/anomaly_lab/platform/validation.py tests/platform/test_sources.py
git commit -m "refactor(platform): 拆分 validate_query 的两档校验

浏览用的 SQL 不该被强制要求带 \$timefilter —— 那是指标 SQL 的要求。
拆成 validate_readonly_sql（只读）+ validate_query（只读 + \$timefilter），
validate_query 的语义完全不变，现有调用方零改动。"
```

---

## Chunk 2: HTTP 透传连接器

### Task 4: HTTP 连接器实现

**Files:**
- Create: `src/anomaly_lab/platform/sources/http_sql.py`
- Test: `tests/platform/test_http_source.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/platform/test_http_source.py`：

```python
"""HTTP 透传连接器。

⚠️ 这里的假端点只是**测试夹具** —— 不承担「持续产数」职责
   （那是 spec 2 的「假远端时序数据库」）。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import pytest

from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.http_sql import HttpSqlConnector, RemoteError


class _Handler(BaseHTTPRequestHandler):
    """按测试预设的响应回话。"""

    def log_message(self, *args):  # noqa: A002
        pass

    def _payload(self):
        if self.command == "GET":
            # ⚠️ 存**原始** query 串 —— parse_qs 会把 %20 解码掉，
            #    那样就测不到「URL 里的 SQL 有没有被编码」了
            return urlparse(self.path).query
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return raw.decode(errors="replace")

    def _respond(self):
        self.server.requests.append(self._payload())
        body = self.server.body
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        else:
            body = body.encode()
        self.send_response(self.server.status)
        self.send_header("Content-Type", self.server.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._respond()

    def do_POST(self):
        self._respond()


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.status = 200
    server.body = {"data": []}
    server.content_type = "application/json"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _source(server, **config) -> Source:
    base = {
        "url": f"http://127.0.0.1:{server.server_port}/query?q={{sql}}",
        "method": "GET",
        "format": "json",
    }
    base.update(config)
    return Source(
        id=1,
        name="remote",
        kind="http",
        path="",
        created_at="2026-10-30T00:00:00+00:00",
        config=base,
    )


def _metric(**overrides) -> Metric:
    base = dict(
        id=1,
        source_id=1,
        name="demo",
        query="SELECT ts, value FROM t WHERE $timefilter",
        time_column="ts",
        value_column="value",
        group_column=None,
        time_format="iso_utc",
        freq="5min",
        created_at="2026-10-30T00:00:00+00:00",
        source_timezone="UTC",
        missing_policy="drop",
    )
    base.update(overrides)
    return Metric(**base)


def test_url_template_encodes_sql(http_server):
    """URL 里的 SQL 要 URL 编码。"""
    http_server.body = {"data": []}
    HttpSqlConnector(_source(http_server)).execute_sql("SELECT 1")
    assert "SELECT%201" in http_server.requests[0]


def test_body_template_receives_raw_sql(http_server):
    """⚠️ body 里的 SQL **不能** URL 编码 —— 百分号编码会污染查询。"""
    http_server.body = {"data": []}
    source = _source(
        http_server,
        url=f"http://127.0.0.1:{http_server.server_port}/query",
        method="POST",
        body={"db": "demo", "q": "{sql}", "format": "csv"},
    )
    HttpSqlConnector(source).execute_sql("SELECT ts FROM t")
    assert http_server.requests[0]["q"] == "SELECT ts FROM t"
    assert http_server.requests[0]["db"] == "demo"


def test_json_response_is_parsed(http_server):
    """⚠️ 顶层是对象时要靠 rows_path 指到那个数组。"""
    http_server.body = {"data": [{"ts": "2026-10-30T09:00:00+00:00", "value": 3.5}]}
    source = _source(http_server, rows_path="data")
    frame = HttpSqlConnector(source).execute_sql("SELECT 1")
    assert list(frame.columns) == ["ts", "value"]
    assert frame["value"].tolist() == [3.5]


def test_json_array_response_is_parsed(http_server):
    http_server.body = [{"a": 1}, {"a": 2}]
    frame = HttpSqlConnector(_source(http_server)).execute_sql("SELECT 1")
    assert len(frame) == 2


def test_rows_path_extracts_array(http_server):
    http_server.body = {"data": {"items": [{"a": 1}, {"a": 2}]}}
    source = _source(http_server, rows_path="data.items")
    frame = HttpSqlConnector(source).execute_sql("SELECT 1")
    assert len(frame) == 2


def test_missing_rows_path_raises(http_server):
    http_server.body = {"data": [{"a": 1}]}
    source = _source(http_server, rows_path="nope")
    with pytest.raises(ValueError, match="rows_path"):
        HttpSqlConnector(source).execute_sql("SELECT 1")


def test_csv_response_is_parsed(http_server):
    http_server.content_type = "text/csv"
    http_server.body = "ts,value\n2026-10-30T09:00:00+00:00,7\n"
    source = _source(http_server, format="csv")
    frame = HttpSqlConnector(source).execute_sql("SELECT 1")
    assert list(frame.columns) == ["ts", "value"]
    assert frame["value"].tolist() == [7]


def test_remote_error_status_raises(http_server):
    http_server.status = 500
    http_server.body = {"error": "boom"}
    with pytest.raises(RemoteError) as exc:
        HttpSqlConnector(_source(http_server)).execute_sql("SELECT 1")
    assert "500" in str(exc.value)


def test_timefilter_replaced_with_iso_literal(http_server):
    http_server.body = {"data": []}
    connector = HttpSqlConnector(_source(http_server))
    connector.fetch(
        _metric(),
        datetime(2026, 10, 30, tzinfo=UTC),
        datetime(2026, 10, 31, tzinfo=UTC),
    )
    sql = http_server.requests[0]
    assert "$timefilter" not in sql
    assert "2026-10-30T00:00:00+00:00" in sql


def test_build_time_condition_is_iso_literal(http_server):
    """⚠️ HTTP 方言用字面量（不是 julianday）—— 那是 SQLite 专有的。"""
    connector = HttpSqlConnector(_source(http_server))
    condition, params = connector.build_time_condition(
        TimeContext(
            column="ts",
            fmt="iso_utc",
            timezone="UTC",
            start=datetime(2026, 10, 30, tzinfo=UTC),
            end=datetime(2026, 10, 31, tzinfo=UTC),
        )
    )
    assert "julianday" not in condition
    assert params == ()
    assert "'2026-10-30T00:00:00+00:00'" in condition
```

⚠️ 上面最后一个测试用到 `TimeContext` —— 在文件顶部补
`from anomaly_lab.platform.sources.base import TimeContext`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_http_source.py -q -p no:warnings`
Expected: FAIL —— `ModuleNotFoundError: No module named 'anomaly_lab.platform.sources.http_sql'`

- [ ] **Step 3: 实现 `sources/http_sql.py`**

```python
"""HTTP 透传连接器：把 SQL 原样发给远端 SQL 网关，取回表格。

对应的是 **SQL-over-HTTP** 的远端（InfluxDB 3 的 `/api/v3/query_sql`、
ClickHouse 的 `/?query=`、TDengine 的 `/rest/sql`…）——
它们自己执行 SQL，只返回结果集，平台不落地也不代算。

⚠️ 安全边界是**远端账号的权限**，不是平台的只读校验 ——
   `validate_readonly_sql` 的关键字黑名单可被绕过。UI 与文档必须讲明。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

import pandas as pd

from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.base import TimeContext, sql_literal
from anomaly_lab.platform.validation import validate_identifier


class RemoteError(RuntimeError):
    """远端返回了错误状态，或连接失败。"""


def _substitute(template: str, sql: str, *, encode: bool) -> str:
    """把 `{sql}` 占位符换成真实 SQL。

    ⚠️ URL 里的要 URL 编码，body 里的**不能** ——
       百分号编码会污染 SQL 本身。
    """
    value = urllib.parse.quote(sql) if encode else sql
    return template.replace("{sql}", value)


def _dig(payload: Any, path: str) -> Any:
    """按点号路径取值（`data.items`）。"""
    current = payload
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            raise ValueError(f"rows_path 在响应里找不到: {path}")
        if current is None:
            raise ValueError(f"rows_path 在响应里找不到: {path}")
    return current


def _parse_json(text: str, rows_path: str | None) -> pd.DataFrame:
    payload = json.loads(text)
    if rows_path:
        payload = _dig(payload, rows_path)
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValueError(f"JSON 响应不是对象数组: {type(payload).__name__}")
    return pd.DataFrame(payload)


def _parse_csv(text: str) -> pd.DataFrame:
    import io

    # ⚠️ 远端 CSV 约定带表头行（InfluxDB 的 csv format 带头）
    return pd.read_csv(io.StringIO(text))


def _parse_jsonl(text: str) -> pd.DataFrame:
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return pd.DataFrame(rows)


class HttpSqlConnector:
    """HTTP 透传连接器。"""

    kind = "http"

    def __init__(self, source: Source) -> None:
        self.source = source
        self.config = source.config or {}

    # ---------- 配置 ----------

    @property
    def _timeout(self) -> float:
        return float(self.config.get("timeout_seconds", 30) or 30)

    @property
    def _format(self) -> str:
        return str(self.config.get("format", "json") or "json")

    # ---------- 连接器协议 ----------

    def describe(self) -> str:
        return f"HTTP {self.config.get('method', 'GET')} {self.config.get('url', '')}"

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.execute_sql("SELECT 1")
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        return True, "连接正常"

    def build_time_condition(self, ctx: TimeContext) -> tuple[str, tuple]:
        """HTTP 方言的时间条件（字面量，无绑定参数）。

        ⚠️ 与 SQLite 的 `julianday()` 完全不同 —— 这是**故意的**：
           浏览预览与指标运行时都走这里，两边结果必然一致。
        """
        low = sql_literal(ctx.start, ctx.fmt, ctx.timezone)
        high = sql_literal(ctx.end, ctx.fmt, ctx.timezone)
        condition = f'"{ctx.column}" >= {low} AND "{ctx.column}" < {high}'
        return condition, ()

    def execute_sql(
        self, sql: str, *, limit: int | None = None, params: tuple = ()
    ) -> pd.DataFrame:
        """把 SQL 发给远端，返回表格。

        ⚠️ `params` 被忽略 —— HTTP 侧没有绑定参数的概念，
           条件里的值都是字面量。
        """
        text = sql
        if limit is not None:
            text = f"SELECT * FROM ({sql}) LIMIT {int(limit)}"
        payload = self._request(text)
        fmt = self._format
        if fmt == "csv":
            return _parse_csv(payload)
        if fmt == "jsonl":
            return _parse_jsonl(payload)
        return _parse_json(payload, self.config.get("rows_path"))

    def fetch(self, metric: Metric, start: datetime, end: datetime) -> pd.DataFrame:
        """取 [start, end) 的数据（做 `$timefilter` 替换）。"""
        validate_identifier(metric.time_column, "time_column")
        condition, _ = self.build_time_condition(
            TimeContext(
                column=metric.time_column,
                fmt=metric.time_format,
                timezone=metric.source_timezone,
                start=start,
                end=end,
            )
        )
        return self.execute_sql(metric.query.replace("$timefilter", condition))

    # ---------- HTTP ----------

    def _request(self, sql: str) -> str:
        url = _substitute(str(self.config.get("url", "")), sql, encode=True)
        method = str(self.config.get("method", "GET")).upper()
        headers = {str(k): str(v) for k, v in (self.config.get("headers") or {}).items()}
        body_template = self.config.get("body")

        data: bytes | None = None
        if method == "POST":
            if isinstance(body_template, dict):
                body = {
                    key: (
                        _substitute(str(value), sql, encode=False)
                        if isinstance(value, str)
                        else value
                    )
                    for key, value in body_template.items()
                }
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            else:
                data = sql.encode("utf-8")
                headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RemoteError(f"远端返回 {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise TimeoutError(f"请求远端超时（{self._timeout}s）") from exc
            raise RemoteError(f"无法连接远端: {reason}") from exc
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/platform/test_http_source.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: 跑全量 + lint + 提交**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint`
Expected: PASS + All checks passed!

```bash
git add src/anomaly_lab/platform/sources/http_sql.py tests/platform/test_http_source.py
git commit -m "feat(platform): HTTP 透传连接器

把 SQL 原样发给远端 SQL 网关（InfluxDB 3 / ClickHouse / TDengine 那种），
取回表格。零新依赖 —— HTTP 客户端用标准库 urllib.request。

- {sql} 占位符：URL 里做 URL 编码，body 里原样替换
  （body 编码会污染 SQL 本身）
- 响应解析用 pandas（read_csv / DataFrame）—— 标准库产出的全是字符串，
  dtype 恒为 object，类型推断就成了死代码
- build_time_condition 用 ISO 字面量（不是 julianday）——
  浏览预览与指标运行时走同一处，两边结果必然一致
- 远端错误分类：HTTP 4xx/5xx → RemoteError，超时 → TimeoutError

⚠️ 安全边界是远端账号权限，不是平台的只读校验（黑名单可绕过）。"
```

---

### Task 5: 注册表 + runner 接入连接器

**Files:**
- Modify: `src/anomaly_lab/platform/sources/__init__.py`
- Modify: `src/anomaly_lab/platform/runner.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Modify: `tests/platform/test_robustness.py`
- Test: `tests/platform/test_sources.py`（追加）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/platform/test_sources.py`：

```python
def test_get_connector_returns_sqlite_connector(tmp_path):
    from anomaly_lab.platform.sources import get_connector

    source = Source(
        id=1, name="local", kind="sqlite", path="platform/source.db",
        created_at="2026-10-30T00:00:00+00:00",
    )
    connector = get_connector(source, tmp_path)
    assert connector.kind == "sqlite"


def test_get_connector_returns_http_connector(tmp_path):
    from anomaly_lab.platform.sources import get_connector

    source = Source(
        id=2, name="remote", kind="http", path="",
        created_at="2026-10-30T00:00:00+00:00",
        config={"url": "https://x/q?q={sql}"},
    )
    connector = get_connector(source, tmp_path)
    assert connector.kind == "http"


def test_get_connector_rejects_unknown_kind(tmp_path):
    from anomaly_lab.platform.sources import get_connector

    source = Source(
        id=3, name="x", kind="kafka", path="",
        created_at="2026-10-30T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="不支持的数据源类型"):
        get_connector(source, tmp_path)
```

⚠️ 需要在文件顶部补 `from anomaly_lab.platform.models import Metric, Source`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_sources.py -q -p no:warnings`
Expected: FAIL —— `ImportError: cannot import name 'get_connector'`

- [ ] **Step 3: 实现注册表**

把 `src/anomaly_lab/platform/sources/__init__.py` 改成：

```python
"""连接器层：按数据源类型取数。

⚠️ 这里的注册表是**极简**的 —— 一个 kind → 构造函数的映射，
   不做插件动态加载（没有那个需求）。
"""

from __future__ import annotations

from pathlib import Path

from anomaly_lab.platform.models import Source
from anomaly_lab.platform.validation import validate_kind

__all__ = ["SUPPORTED_KINDS", "get_connector"]

SUPPORTED_KINDS = ("sqlite", "http")


def get_connector(source: Source, data_root: Path):
    """按数据源类型拿连接器。

    ⚠️ `source.config` 必须是**未脱敏**的原始值 —— 调用方拿到的应是
       `store.get_source_raw()` 的结果。
    """
    kind = validate_kind(source.kind)
    if kind == "sqlite":
        from anomaly_lab.platform.sources.sqlite import SqliteConnector

        return SqliteConnector(source, data_root)
    from anomaly_lab.platform.sources.http_sql import HttpSqlConnector

    return HttpSqlConnector(source)
```

- [ ] **Step 4: 改 `runner.py` 走连接器**

修改 `src/anomaly_lab/platform/runner.py`：

1. 删掉 `from anomaly_lab.platform.sqlite_source import load_series`
2. 改成：

```python
from anomaly_lab.platform.sources import get_connector
from anomaly_lab.platform.sources.base import series_from_frame
```

3. 新增模块级函数（**保留 `load_series` 这个名字** ——
   `tests/platform/test_robustness.py` monkeypatch 的就是它）：

```python
def load_series(
    store: PlatformStore,
    metric: Metric,
    data_root: Path,
    start: datetime,
    end: datetime,
) -> list[SeriesBundle]:
    """按指标所属数据源取数（走连接器层）。

    ⚠️ 模块级函数名保留 `load_series` —— 既有测试 monkeypatch 的目标就是它。
    """
    source = store.get_source_raw(metric.source_id)
    connector = get_connector(source, data_root)
    frame = connector.fetch(metric, start, end)
    return series_from_frame(frame, metric)
```

⚠️ `runner.py` 需要 `from anomaly_lab.contracts import SeriesBundle`、
`from anomaly_lab.platform.models import Metric`。

4. `_run_job` 里把

```python
        source_path = resolve_source_path(source.path, data_root)
        series_list = load_series(metric, source_path, start_time, end_time)
```

改成

```python
        series_list = load_series(store, metric, data_root, start_time, end_time)
```

并删掉已经不再需要的 `source = store.get_source(...)` 那一行
（`load_series` 内部会取）。`resolve_source_path` 保留（外部可能引用）。

- [ ] **Step 5: `platform_routes.py` 的 compare / suggestion 也走连接器**

`src/anomaly_lab/web/platform_routes.py` 里两处 `load_series(metric, source_path, start_time, end_time)`
（第 695、960 行附近）—— 改成：

```python
        series_list = runner_module.load_series(
            _store(), metric, get_data_root(), start_time, end_time
        )
```

⚠️ 否则 HTTP 数据源在这两个端点会因 `path` 为空而 `FileNotFoundError` → 500。

- [ ] **Step 6: 修 `test_robustness.py` 的 monkeypatch**

`tests/platform/test_robustness.py` 里：

```python
    real_load = load_series
```

改成

```python
    from anomaly_lab.platform import runner as runner_module

    real_load = runner_module.load_series
```

⚠️ 原因：runner 的 `load_series` 签名已变（多了 `store`），
原来导入的 `sqlite_source.load_series` 签名不匹配。

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/platform -q -p no:warnings`
Expected: PASS

- [ ] **Step 8: 跑全量 + lint + 提交**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint`
Expected: PASS + All checks passed!

```bash
git add src/anomaly_lab/platform/sources src/anomaly_lab/platform/runner.py src/anomaly_lab/web/platform_routes.py tests/platform/test_sources.py tests/platform/test_robustness.py
git commit -m "feat(platform): 注册表 + runner 走连接器取数

- sources/__init__.py 提供 get_connector(source, data_root)：
  kind → 构造函数的极简映射，不做插件动态加载
- runner.load_series 改为「按数据源类型取数」，
  ⚠️ 函数名保留 —— 既有测试 monkeypatch 的目标就是它
- runner 改用 store.get_source_raw()（不脱敏的原始配置）
- ⚠️ compare / feedback-suggestion 两处也改走连接器 ——
  否则 HTTP 源会因 path 为空而 500"
```

---

## Chunk 3: 数据浏览器（后端）

### Task 6: 浏览端点

**Files:**
- Create: `src/anomaly_lab/web/source_query_routes.py`
- Modify: `src/anomaly_lab/web/app.py`
- Test: `tests/web/test_source_query.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/web/test_source_query.py`：

```python
"""数据浏览器端点。"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: A002
        pass

    def do_GET(self):
        body = json.dumps(
            {"data": [{"ts": "2026-10-30T09:00:00+00:00", "value": 3.5}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def remote():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _client(tmp_path, remote):
    client = TestClient(create_app(platform_data_root=tmp_path))
    response = client.post(
        "/api/platform/sources",
        json={
            "name": "remote",
            "kind": "http",
            "config": {
                "url": f"http://127.0.0.1:{remote.server_port}/q?q={{sql}}",
                "rows_path": "data",
            },
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()


def test_query_returns_columns_and_rows(tmp_path, remote):
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts, value FROM t", "limit": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [col["name"] for col in body["columns"]] == ["ts", "value"]
    assert body["rows"] == [["2026-10-30T09:00:00+00:00", 3.5]]
    assert "elapsed_ms" in body
    assert body["total"] == 1
    assert body["truncated"] is False


def test_query_rejects_write_sql(tmp_path, remote):
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "DELETE FROM t"},
    )
    assert response.status_code == 400


def test_query_with_timefilter_without_time_column_is_400(tmp_path, remote):
    client, source = _client(tmp_path, remote)
    response = client.post(
        f"/api/platform/sources/{source['id']}/query",
        json={"sql": "SELECT ts FROM t WHERE $timefilter"},
    )
    assert response.status_code == 400
    assert "time_column" in response.json()["detail"]


def test_query_on_missing_source_is_404(tmp_path, remote):
    client, _ = _client(tmp_path, remote)
    response = client.post(
        "/api/platform/sources/999/query",
        json={"sql": "SELECT 1"},
    )
    assert response.status_code == 404


def test_query_on_remote_error_is_502(tmp_path):
    class _Boom(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: A002
            pass

        def do_GET(self):
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _Boom)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = TestClient(create_app(platform_data_root=tmp_path))
        source = client.post(
            "/api/platform/sources",
            json={
                "name": "boom",
                "kind": "http",
                "config": {"url": f"http://127.0.0.1:{server.server_port}/q?q={{sql}}"},
            },
        ).json()
        response = client.post(
            f"/api/platform/sources/{source['id']}/query",
            json={"sql": "SELECT 1"},
        )
        assert response.status_code == 502
    finally:
        server.shutdown()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/web/test_source_query.py -q -p no:warnings`
Expected: FAIL —— 404（端点不存在）

- [ ] **Step 3: 实现 `web/source_query_routes.py`**

```python
"""数据浏览端点：在数据源上执行一段只读 SQL，返回列结构与前 N 行。

⚠️ 单独一个文件 —— `platform_routes.py` 已经 1000+ 行了。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from anomaly_lab.platform.sources import get_connector
from anomaly_lab.platform.sources.base import TimeContext, sql_literal
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.validation import validate_readonly_sql

TimeFormat = Literal["iso_utc", "iso_naive", "epoch_s", "epoch_ms"]


class SourceQueryIn(BaseModel):
    """数据浏览器的一次查询。"""

    sql: str
    start: str | None = None
    end: str | None = None
    limit: int | None = 100
    # ⚠️ 仅当 SQL 含 $timefilter 时需要 —— 平台才知道替换成什么时间条件
    time_column: str | None = None
    time_format: TimeFormat | None = None
    source_timezone: str | None = None


def _parse_boundary(value: str | None, default: datetime) -> datetime:
    """解析时间边界；缺省时用一个极宽的默认值（不限制）。"""
    if not value:
        return default
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _column_type(series: pd.Series) -> str:
    """列类型（给前端做推断提示）。"""
    if pd.api.types.is_datetime64_any_dtype(series):
        return "TIMESTAMP"
    if pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        return "REAL"
    return "TEXT"


def _json_safe(value):
    """把 numpy 标量转成能 JSON 序列化的 Python 值。"""
    if value is None:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def build_source_query_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/platform/sources/{source_id}/query")
    def query_source(source_id: int, payload: SourceQueryIn) -> dict:
        """在数据源上执行一段只读 SQL，返回列结构与前 N 行。

        ⚠️ 这是**浏览**，不落库、不建指标 —— 只是让用户在定指标前
           先看到「查出来到底是什么结构」。
        """
        store = get_store()
        try:
            source = store.get_source_raw(source_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            sql = validate_readonly_sql(payload.sql)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        connector = get_connector(source, get_data_root())

        # ⚠️ 时间条件的渲染交给**连接器** —— 浏览与指标运行时必须一致，
        #    否则「预览看到的」≠「跑出来的」。
        try:
            sql = _apply_time_placeholders(sql, payload, connector)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        import time

        started = time.perf_counter()
        try:
            frame = connector.execute_sql(sql)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"执行失败: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        limit = payload.limit if payload.limit and payload.limit > 0 else 100
        total = len(frame)
        return {
            "columns": [
                {"name": str(name), "type": _column_type(frame[name])}
                for name in frame.columns
            ],
            "rows": [
                [_json_safe(value) for value in row]
                for row in frame.head(limit).itertuples(index=False)
            ],
            "total": total,
            "truncated": total > limit,
            "elapsed_ms": elapsed_ms,
        }

    return router


def _apply_time_placeholders(sql: str, payload: SourceQueryIn, connector) -> str:
    """替换浏览 SQL 里的时间占位符。

    - `$timefilter` → 由**连接器**渲染的时间条件（需要 time_column）
    - `{start}` / `{end}` → 共享的字面量（用户自己写列名）
    """
    fmt = payload.time_format or "iso_utc"
    tz = payload.source_timezone or "UTC"

    if "$timefilter" in sql:
        if not payload.time_column:
            raise ValueError("使用 $timefilter 需要指定时间列（time_column）")
        condition, _ = connector.build_time_condition(
            TimeContext(
                column=payload.time_column,
                fmt=fmt,
                timezone=tz,
                start=_parse_boundary(payload.start, datetime(1970, 1, 1, tzinfo=UTC)),
                end=_parse_boundary(payload.end, datetime(2100, 1, 1, tzinfo=UTC)),
            )
        )
        sql = sql.replace("$timefilter", condition)

    if "{start}" in sql or "{end}" in sql:
        sql = sql.replace(
            "{start}",
            sql_literal(
                _parse_boundary(payload.start, datetime(1970, 1, 1, tzinfo=UTC)), fmt, tz
            ),
        ).replace(
            "{end}",
            sql_literal(
                _parse_boundary(payload.end, datetime(2100, 1, 1, tzinfo=UTC)), fmt, tz
            ),
        )
    return sql
```

- [ ] **Step 4: 挂上 router**

`src/anomaly_lab/web/app.py`：

```python
from anomaly_lab.web.source_query_routes import build_source_query_router
```

并在 `app.include_router(build_router(get_store, lambda: data_root))` 旁边加：

```python
    app.include_router(
        build_source_query_router(get_store, lambda: data_root)
    )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/web/test_source_query.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 6: 跑全量 + lint + 提交**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint`
Expected: PASS + All checks passed!

```bash
git add src/anomaly_lab/web/source_query_routes.py src/anomaly_lab/web/app.py tests/web/test_source_query.py
git commit -m "feat(web): 数据浏览端点

POST /api/platform/sources/{id}/query —— 在数据源上执行只读 SQL，
返回列结构、前 N 行、总行数与耗时。这是「先看结构、再定指标」的第一步。

- ⚠️ 时间条件的渲染交给**连接器** —— 浏览与指标运行时走同一处，
  否则「预览看到的」≠「跑出来的」
- 错误分类：本地校验 400 / 执行失败 502 / 超时 504
- 单独一个文件 —— platform_routes.py 已经 1000+ 行"
```

---

## Chunk 4: 前端

### Task 7: 前端 API + 类型 + 数据源表单

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/platform.ts`
- Modify: `frontend/src/features/sources/SourceForm.tsx`
- Test: `frontend/src/features/sources/sourceEdit.test.tsx`

- [ ] **Step 1: 改类型**

`frontend/src/api/types.ts`：

```typescript
export interface SourceConfig {
  /** kind=http 时的请求 URL 模板，{sql} 是占位符 */
  url?: string
  method?: 'GET' | 'POST'
  body?: Record<string, unknown>
  headers?: Record<string, string>
  format?: 'json' | 'csv' | 'jsonl'
  rows_path?: string
  timeout_seconds?: number
}

export interface CatalogSource {
  id: number
  name: string
  kind: string
  path: string
  created_at: string
  /**
   * kind 专属配置（凭据已脱敏）。
   *
   * ⚠️ 可选 —— 既有测试里的 fixture 没这个字段，改成必填会一片红。
   */
  config?: SourceConfig
}
```

再加查询结果类型：

```typescript
// ─────────────────────────────────────────── 数据浏览器

export interface QueryColumn {
  name: string
  type: 'TIMESTAMP' | 'INTEGER' | 'REAL' | 'TEXT'
}

export interface QueryResult {
  columns: QueryColumn[]
  rows: unknown[][]
  /** 总行数（不只是返回的这些） */
  total: number
  truncated: boolean
  elapsed_ms: number
}
```

- [ ] **Step 2: 改 API 封装**

`frontend/src/api/platform.ts`：

```typescript
export const createSource = (payload: {
  name: string
  path?: string
  kind?: string
  config?: SourceConfig
}) => postJson<{ id: number }>('/api/platform/sources', payload)

export const updateSource = (
  sourceId: number,
  payload: { name?: string; path?: string; kind?: string; config?: SourceConfig },
) =>
  request<unknown>(`/api/platform/sources/${sourceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

/**
 * 在数据源上执行一段只读 SQL（数据浏览器）。
 *
 * ⚠️ 只是浏览 —— 不落库、不建指标。
 */
export const querySource = (sourceId: number, payload: {
  sql: string
  start?: string
  end?: string
  limit?: number
  time_column?: string
  time_format?: string
  source_timezone?: string
}) =>
  postJson<QueryResult>(`/api/platform/sources/${sourceId}/query`, payload)
```

⚠️ import 里加 `QueryResult` 与 `SourceConfig`。

- [ ] **Step 3: 改数据源表单**

`frontend/src/features/sources/SourceForm.tsx`：

- `SourceFormValues` 加 `config?: SourceConfig`
- `kind` 从 `Input` 改成 `Select`，选项
  `[{ value: 'sqlite', label: 'SQLite 文件' }, { value: 'http', label: 'HTTP SQL 网关' }]`
- `kind === 'http'` 时显示：URL（必填）、method（Select）、format（Select）、
  headers（JSON textarea）、body（JSON textarea）、rows_path
- `kind === 'sqlite'` 时显示 path（必填）
- 提交时：`kind === 'http'` → `path: ''`，config 从表单字段组装；
  `kind === 'sqlite'` → `config: {}`
- 编辑时：`initialValues.config` 来自 `editing.config ?? {}`

⚠️ headers/body 是 JSON 字符串，表单里用 textarea，提交前 `JSON.parse`；
解析失败要在表单里报错（用 `Form.Item` 的 `rules` validator），不要静默吞掉。

⚠️ 提交 config 时**要把脱敏值原样传回** —— 后端会识别哨兵值并保留原值。

- [ ] **Step 4: 跑前端测试 + 类型检查**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/features/sources`
Expected: 无类型错误；测试通过

⚠️ `sourceEdit.test.tsx` 里既有 fixture 没有 `config` 字段 —— 因为
`config` 是**可选**的，不用改 fixture。既有测试也没碰 `kind` 字段，
所以「kind 改成 Select」不会让它失败 —— 保留它原有的断言即可。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/types.ts frontend/src/api/platform.ts frontend/src/features/sources/SourceForm.tsx
git commit -m "feat(frontend): 数据源表单支持 HTTP SQL 网关

- kind 从自由文本改成 Select（sqlite / http）
- http 时显示 url / method / format / headers / body / rows_path
- 新增 querySource() API 封装与 QueryResult / SourceConfig 类型
- CatalogSource.config 设为可选 —— 既有 fixture 不必改"
```

---

### Task 8: 数据浏览器面板

**Files:**
- Create: `frontend/src/features/sources/DataBrowser.tsx`
- Create: `frontend/src/features/sources/DataBrowser.test.tsx`
- Modify: `frontend/src/pages/SourceDetailPage.tsx`

- [ ] **Step 1: 写失败的测试**

创建 `frontend/src/features/sources/DataBrowser.test.tsx`：

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataBrowser } from './DataBrowser'

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(
        JSON.stringify({
          columns: [
            { name: 'ts', type: 'TIMESTAMP' },
            { name: 'value', type: 'REAL' },
          ],
          rows: [['2026-10-30T09:00:00+00:00', 3.5]],
          total: 1,
          truncated: false,
          elapsed_ms: 7,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    ),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderBrowser() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <DataBrowser sourceId={1} onUseAsMetric={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('DataBrowser', () => {
  it('显示编辑器与执行按钮', () => {
    renderBrowser()
    // ⚠️ 面板里有多个 textbox（SQL 编辑器 + RangePicker 的两个 + 时间列输入），
    //    用 placeholder 精确定位，别用 getByRole('textbox')
    expect(screen.getByPlaceholderText(/SELECT/)).toBeTruthy()
    expect(screen.getByRole('button', { name: /执\s*行/ })).toBeTruthy()
  })

  it('执行后显示列名与行', async () => {
    const user = userEvent.setup()
    renderBrowser()
    await user.click(screen.getByRole('button', { name: /执\s*行/ }))
    expect(await screen.findByText('ts')).toBeTruthy()
    expect(await screen.findByText('value')).toBeTruthy()
    expect(await screen.findByText('3.5')).toBeTruthy()
  })
})
```

⚠️ 用 `@testing-library/user-event` 而不是裸 `.click()` —— 裸 click 会触发
React 的「not wrapped in act」警告。若仓库没装 user-event，
用 `npm i -D @testing-library/user-event` 装上。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/features/sources/DataBrowser.test.tsx`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现 `DataBrowser.tsx`**

```tsx
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button, Card, DatePicker, Input, Space, Table, Typography } from 'antd'
import { querySource } from '../../api/platform'
import type { QueryResult } from '../../api/types'

const { RangePicker } = DatePicker
const { TextArea } = Input

/**
 * 数据浏览器。
 *
 * ⚠️ 目的是「先看结构、再定指标」—— 用户不该闭着眼睛写 SQL。
 */
export function DataBrowser({
  sourceId,
  onUseAsMetric,
}: {
  sourceId: number
  onUseAsMetric: (payload: {
    sql: string
    columns: QueryResult['columns']
  }) => void
}) {
  const [sql, setSql] = useState('SELECT * FROM metrics LIMIT 100')
  const [range, setRange] = useState<[unknown, unknown] | null>(null)
  const [timeColumn, setTimeColumn] = useState<string>('')

  const run = useMutation({
    mutationFn: () =>
      querySource(sourceId, {
        sql,
        limit: 100,
        time_column: timeColumn || undefined,
        start: range?.[0] ? String(range[0]) : undefined,
        end: range?.[1] ? String(range[1]) : undefined,
      }),
  })

  const result = run.data

  return (
    <Card size="small" title="浏览数据" className="data-browser">
      <TextArea
        rows={5}
        value={sql}
        onChange={(e) => setSql(e.target.value)}
        spellCheck={false}
        placeholder="SELECT ts, value FROM metrics WHERE ts >= {start}"
      />
      <Space wrap style={{ margin: '12px 0' }}>
        <RangePicker onChange={(value) => setRange(value as [unknown, unknown] | null)} />
        <Input
          placeholder="时间列（SQL 含 $timefilter 时必填）"
          value={timeColumn}
          onChange={(e) => setTimeColumn(e.target.value)}
          style={{ width: 280 }}
        />
        <Button type="primary" loading={run.isPending} onClick={() => run.mutate()}>
          执行
        </Button>
      </Space>

      {run.error instanceof Error && <p className="form-error">{run.error.message}</p>}

      {result && (
        <>
          <Typography.Text type="secondary">
            {result.columns.length} 列 · 共 {result.total} 行（显示 {result.rows.length} 行）·
            {result.elapsed_ms} ms
          </Typography.Text>
          <Table
            size="small"
            rowKey={(_row, index) => String(index)}
            dataSource={result.rows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            columns={result.columns.map((col) => ({
              title: (
                <Space direction="vertical" size={0}>
                  <span>{col.name}</span>
                  <span className="muted mono">{col.type}</span>
                </Space>
              ),
              dataIndex: col.name,
              key: col.name,
              render: (value: unknown) => <span className="mono">{String(value)}</span>,
            }))}
          />
          <Button onClick={() => onUseAsMetric({ sql, columns: result.columns })}>
            用这个结果建指标
          </Button>
        </>
      )}
    </Card>
  )
}
```

- [ ] **Step 4: 挂到数据源详情页**

`frontend/src/pages/SourceDetailPage.tsx`：

- import `DataBrowser`
- 在指标列表下方加 `<DataBrowser sourceId={sourceId} onUseAsMetric={handleUseAsMetric} />`
- `handleUseAsMetric` 先占位（Task 9 完成联动）

- [ ] **Step 5: 跑测试 + 类型检查 + 构建**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/features/sources && npm test`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add frontend/src/features/sources/DataBrowser.tsx frontend/src/features/sources/DataBrowser.test.tsx frontend/src/pages/SourceDetailPage.tsx
git commit -m "feat(frontend): 数据浏览器面板

SQL 编辑器 + 时间范围 + 执行 → 列结构与前 N 行。
目的是「先看结构、再定指标」—— 用户不该闭着眼睛写 SQL。"
```

---

### Task 9: 「用结果建指标」联动

**Files:**
- Modify: `frontend/src/features/metrics/MetricForm.tsx`
- Modify: `frontend/src/pages/SourceDetailPage.tsx`

- [ ] **Step 1: 让 MetricForm 支持外部传入的初始值**

`frontend/src/features/metrics/MetricForm.tsx`：

1. 抽出 `editingToValues`（当前那段 inline 的映射）：

```typescript
/** 编辑态 → 表单初值。 */
function editingToValues(editing: CatalogMetric): MetricFormValues {
  return {
    source_id: editing.source_id,
    name: editing.name,
    query: editing.query,
    time_column: editing.time_column,
    value_column: editing.value_column,
    group_column: editing.group_column ?? '',
    time_format: editing.time_format,
    source_timezone: editing.source_timezone,
    missing_policy: editing.missing_policy,
    freq: editing.freq,
  }
}
```

2. 加 prop：

```typescript
  /** 外部预填（从数据浏览器的结果建指标时用）。 */
  initialValues?: Partial<MetricFormValues>
```

3. `initialValues` 改成合并：

```typescript
        initialValues={
          editing
            ? { ...editingToValues(editing), ...initialValues }
            : {
                source_id: defaultSourceId,
                time_column: 'ts',
                value_column: 'value',
                time_format: 'iso_utc',
                source_timezone: 'UTC',
                missing_policy: 'drop',
                freq: '5min',
                query: DEFAULT_METRIC_QUERY,
                ...initialValues,
              }
        }
```

- [ ] **Step 2: 在 SourceDetailPage 里接上联动**

`frontend/src/pages/SourceDetailPage.tsx`：

```typescript
  const [browserResult, setBrowserResult] = useState<{
    sql: string
    columns: QueryColumn[]
    time_column?: string
    value_column?: string
    time_format?: string
  } | null>(null)
```

```typescript
  const handleUseAsMetric = (payload: { sql: string; columns: QueryColumn[] }) => {
    const time = payload.columns.find((c) => c.type === 'TIMESTAMP')
    const numeric = payload.columns.find(
      (c) => c.type === 'REAL' || c.type === 'INTEGER',
    )
    setBrowserResult({
      sql: payload.sql,
      columns: payload.columns,
      time_column: time?.name,
      value_column: numeric?.name,
      time_format: time ? 'iso_utc' : undefined,
    })
    setFormOpen(true)
  }
```

指标弹窗的 `initialValues`：

```typescript
  initialValues={
    browserResult
      ? {
          // ⚠️ 只有 SQL 里带 $timefilter 才预填 query ——
          //    指标要求恰好一个 $timefilter，预填非法 SQL 会让用户白填一遍
          ...(browserResult.sql.includes('$timefilter') ? { query: browserResult.sql } : {}),
          time_column: browserResult.time_column ?? '',
          value_column: browserResult.value_column ?? '',
          time_format: browserResult.time_format ?? 'iso_utc',
        }
      : undefined
  }
```

⚠️ 同时给 `MetricForm` 传 `defaultSourceId={sourceId}` —— 否则从浏览器建的指标
「数据源」字段是空的。

- [ ] **Step 3: 跑测试 + 构建**

Run: `cd frontend && npx tsc --noEmit && npm test && npm run build`
Expected: 全部通过

- [ ] **Step 4: 浏览器验证**

```bash
make dev
```

用 agent-browser 验证：
1. 打开 `/sources/1` → 应看到「浏览数据」面板
2. 点「执行」→ 应看到列名与行
3. 点「用这个结果建指标」→ 指标弹窗应预填列名与数据源

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/metrics/MetricForm.tsx frontend/src/pages/SourceDetailPage.tsx
git commit -m "feat(frontend): 浏览结果一键生成指标

数据浏览器执行完 → 点「用这个结果建指标」→ 指标弹窗预填列名、时间格式与数据源。

⚠️ 浏览的 SQL 不含 \$timefilter 时**不预填 query** ——
   指标要求恰好一个 \$timefilter，预填非法 SQL 会让用户白填一遍。"
```

---

## Chunk 5: 契约、文档与收尾

### Task 10: 端点契约 + 文档

**Files:**
- Modify: `frontend/src/api/endpoints.test.ts`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PLATFORM.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-11-01-data-source-connectors-design.md`

- [ ] **Step 1: 同步端点契约**

`frontend/src/api/endpoints.test.ts`：在 `EXPECTED_PATHS` 加
`'/api/platform/sources/{id}/query'`，并在调用列表里加
`await querySource(1, { sql: 'SELECT 1' })`。

⚠️ 该文件与 `tests/web/test_api_contract.py::test_frontend_covers_all_backend_endpoints`
是**双向守卫** —— 两边必须同时更新，否则测试失败。
⚠️ 后端守卫会把 `{source_id}` 归一化成 `{id}`，前端清单要用 `{id}`。

- [ ] **Step 2: 修正 spec 里的时间字面量格式**

`docs/superpowers/specs/2026-11-01-data-source-connectors-design.md` §4.2 的
`time_literal` 片段用的是 `isoformat(sep=" ")`（空格分隔）——
**与实现不一致**（实现用 T 分隔，与 `to_iso()` 一致）。改成：

```python
    if fmt == "iso_utc":
        return value.astimezone(UTC).isoformat(timespec="seconds")
```

并补一句「⚠️ 必须与平台的 `to_iso()` 完全一致（T 分隔 + `+00:00`）」。

- [ ] **Step 3: 更新文档**

`docs/ARCHITECTURE.md`：mermaid 里把「SQLite 数据源 → 指标 SQL」改成
「数据源（SQLite / HTTP SQL 网关）→ 指标 SQL」；正文里提到
`sqlite_source.load_series` 的地方改成「连接器层」。

`docs/PLATFORM.md`：
- 「只支持 SQLite 一种数据源」→ 「支持 SQLite 文件与 HTTP SQL 网关两种」
- 新增「HTTP 数据源」小节：配置字段、`{sql}` 模板、`format`、安全边界警告
- 新增「数据浏览器」小节：端点、用法、错误码（400 / 502 / 504）

`docs/ROADMAP.md`：数据源插件化条目 → 标记「SQL 型（透传）已完成；专有型待做」

- [ ] **Step 4: 跑全量验证**

Run: `.venv/bin/python -m pytest -q -p no:warnings && make lint && cd frontend && npx tsc --noEmit && npm test && npm run build`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/endpoints.test.ts docs/ARCHITECTURE.md docs/PLATFORM.md docs/ROADMAP.md docs/superpowers/specs/2026-11-01-data-source-connectors-design.md
git commit -m "docs: 同步连接器层与数据浏览器

- ARCHITECTURE：mermaid 与正文改成「连接器层」
- PLATFORM：HTTP 数据源的配置、{sql} 模板、format、安全边界；数据浏览器端点与错误码
- ROADMAP：数据源插件化 → SQL 型已完成
- spec §4.2：time_literal 改成 T 分隔（与 to_iso() 一致，与实现对齐）
- 端点契约双向守卫同步"
```

---

## 验收标准

- [ ] `.venv/bin/python -m pytest -q` 全绿
- [ ] `make lint` 无告警
- [ ] `cd frontend && npx tsc --noEmit && npm test && npm run build` 全绿
- [ ] 浏览器验证：数据源详情页能浏览数据、能从结果建指标
- [ ] 浏览器验证：新建一个 HTTP 数据源能保存、能浏览
- [ ] SQLite 源的行为**完全不变**（既有测试除 monkeypatch 目标名外零改动通过）
- [ ] `docs/my-thought.md` 未被提交（用户的文件）

## 与后续 spec 的衔接

- **spec 2**（假远端时序数据库）：照 InfluxDB 3 的形状实现
  `POST /api/v3/query_sql`；写入 `data/platform/source.db` 时**必须自己开 WAL**
  （平台侧 store 的 WAL 是 `data/platform.db`，与它无关）。
- **spec 3**（检测记录筛选分页）：独立，不依赖本轮。
- **spec 4**（保留清理）：要覆盖 spec 2 持续写入的数据，但**不能清掉模拟源的当前窗口**。
