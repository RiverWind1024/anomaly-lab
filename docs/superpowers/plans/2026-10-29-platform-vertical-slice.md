# 平台垂直切片 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 anomaly-lab 上增加一条可运行的平台链路：SQLite 数据源 → SQL + `$timefilter` → 按 group by 拆序列 → 双向基线/上下界 → P1/P0 分级 → 内置定时调度 → Web 配置与预览。

**Architecture:** 新增 `anomaly_lab.platform` 包，按职责拆成 `store`（SQLite 元数据与任务）、`sqlite_source`（只读查询与拆序列）、`runner`（检测并落盘）、`scheduler`（单进程定时调度）。Web 只调用 platform 服务，不直接拼 SQL。预处理第一版为进程内模块，保留 Loader → Preprocessor → Detector 边界，不引入 RPC/队列。

**Tech Stack:** Python 3.12、SQLite（标准库）、numpy、pandas、FastAPI、ECharts、pytest。

---

## 设计边界（已与用户确认）

- 数据源：第一版只做 SQLite，但保留 `kind` 字段，后续可加 InfluxDB/Prometheus。
- 查询：指标保存一条带 `$timefilter` 的 SQL；加载时替换时间条件，查询后按 `group_column` 拆成独立序列。
- 调度：进程内定时调度；任务与 `last_run_at/next_run_at` 落 SQLite；重启后错过窗口只补跑一次。
- 基线：双向基线 + 上下界；上下界 = 基线 ± 告警阈值 × 鲁棒尺度。暂不做未来多步预测。
- 告警：任务配置 `alert_threshold`（P1）和 `critical_threshold`（P0），分数严格大于阈值才升级。
- 前端：单算法预览，展示实际值、基线、上下界、P1/P0 异常点。
- 预处理隔离：第一版进程内，不做独立服务；这是有意的范围控制，写入 ROADMAP 开放项。
- 非目标：认证/多租户、分布式调度、Prometheus/InfluxDB、未来预测曲线、GPU 批处理。

## 数据模型

`data/platform.db`：

```sql
CREATE TABLE sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'sqlite',
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  query TEXT NOT NULL,
  time_column TEXT NOT NULL,
  value_column TEXT NOT NULL,
  group_column TEXT,
  time_format TEXT NOT NULL DEFAULT 'iso',
  freq TEXT NOT NULL DEFAULT '5min',
  created_at TEXT NOT NULL,
  UNIQUE(source_id, name)
);
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  metric_id INTEGER NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
  name TEXT NOT NULL UNIQUE,
  detector TEXT NOT NULL,
  alert_threshold REAL NOT NULL,
  critical_threshold REAL NOT NULL,
  window_points INTEGER NOT NULL,
  interval_seconds INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  next_run_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  n_series INTEGER NOT NULL DEFAULT 0,
  n_alerts INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
```

运行结果落 `data/cache/platform/runs/<run_id>/index.json` + 每条序列一个 npz。npz 包含 `timestamps`（int64 ns）、`values`、`scores`、`baseline/lower/upper`、`severity`（0 normal / 1 P1 / 2 P0）、阈值与元信息。

## File Structure

- Create: `src/anomaly_lab/detectors/bands.py` — 基线/上下界统一结构，避免平台层重复公式。
- Modify: `src/anomaly_lab/detectors/statistical.py` — 为 IQR/MAD/ZScore/Seasonal/STL/DeseasonalizedIQR 增加 `bands()`。
- Create: `src/anomaly_lab/platform/__init__.py`
- Create: `src/anomaly_lab/platform/timeutil.py` — UTC 时间与 freq 解析。
- Create: `src/anomaly_lab/platform/validation.py` — 名称、阈值、SQL 标识符与只读查询校验。
- Create: `src/anomaly_lab/platform/models.py` — Source/Metric/Job/Run 记录与输入校验。
- Create: `src/anomaly_lab/platform/store.py` — SQLite schema + CRUD + 调度状态。
- Create: `src/anomaly_lab/platform/sqlite_source.py` — 只读执行、时间过滤、按 group 拆序列。
- Create: `src/anomaly_lab/platform/detectors.py` — 支持基线的检测器注册表。
- Create: `src/anomaly_lab/platform/runner.py` — 执行任务、分级、写 npz/index。
- Create: `src/anomaly_lab/platform/scheduler.py` — reconcile + tick + 后台线程。
- Create: `src/anomaly_lab/platform/demo.py` — 生成可立即运行的 SQLite demo。
- Create: `src/anomaly_lab/web/platform_routes.py` — platform API 与页面路由。
- Create: `src/anomaly_lab/web/templates/platform.html`
- Create: `src/anomaly_lab/web/static/platform.js`
- Modify: `src/anomaly_lab/web/app.py` — include router、可选启动调度器。
- Modify: `src/anomaly_lab/web/templates/base.html` — 导航入口。
- Modify: `src/anomaly_lab/web/static/style.css` — 表单/状态样式。
- Modify: `src/anomaly_lab/cli.py` — `platform-demo`、`serve --no-scheduler`。
- Modify: `Makefile` — `platform-demo`。
- Create: `docs/PLATFORM.md` — 使用说明与边界。
- Modify: `README.md`、`docs/ARCHITECTURE.md`、`docs/ROADMAP.md`。
- Test: `tests/detectors/test_bands.py`
- Test: `tests/platform/test_store.py`
- Test: `tests/platform/test_sqlite_source.py`
- Test: `tests/platform/test_runner.py`
- Test: `tests/platform/test_scheduler.py`
- Test: `tests/web/test_platform.py`

---

## Chunk 1: 基线与平台存储

### Task 1: 双向基线/上下界

**Files:**
- Create: `src/anomaly_lab/detectors/bands.py`
- Modify: `src/anomaly_lab/detectors/statistical.py`
- Test: `tests/detectors/test_bands.py`

- [x] **Step 1: 写失败测试**

```python
import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.bands import compute_bands
from anomaly_lab.detectors.statistical import ChangePointDetector, IQRDetector, SeasonalDetector


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(len(values)).astype("datetime64[m]"),
        freq="1min",
    )


def test_iqr_bands_are_baseline_plus_minus_k_iqr():
    values = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    bands = compute_bands(IQRDetector(k=2.5), _series(values), threshold=2.5)
    assert bands is not None
    assert bands.baseline.shape == values.shape
    assert np.allclose(bands.baseline, np.median(values))
    assert np.all(bands.upper > bands.baseline)
    assert np.all(bands.lower < bands.baseline)


def test_seasonal_bands_follow_phase_centers():
    t = np.arange(48 * 3)
    values = 10 + np.sin(2 * np.pi * t / 48)
    bands = compute_bands(SeasonalDetector(period=48), _series(values), threshold=2.0)
    assert bands is not None
    assert bands.baseline.shape == values.shape
    assert np.allclose(bands.upper + bands.lower, 2 * bands.baseline)


def test_detector_without_bands_returns_none():
    values = np.arange(100, dtype=float)
    assert compute_bands(ChangePointDetector(), _series(values), threshold=0.99) is None
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/detectors/test_bands.py -v`
Expected: FAIL，`ModuleNotFoundError: anomaly_lab.detectors.bands`

- [x] **Step 3: 实现 `bands.py`**

```python
"""检测器的可解释输出：中心基线 + 双向上下界。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.contracts import SeriesBundle


@dataclass(frozen=True, eq=False)
class Bands:
    baseline: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    detector: str
    threshold: float

    def __post_init__(self) -> None:
        n = len(self.baseline)
        if len(self.lower) != n or len(self.upper) != n:
            raise ValueError("baseline/lower/upper 长度必须一致")


def compute_bands(detector: object, series: SeriesBundle, threshold: float) -> Bands | None:
    """检测器可选实现 `bands(series, threshold)`；没有则返回 None。"""
    method = getattr(detector, "bands", None)
    if not callable(method):
        return None
    result = method(series, float(threshold))
    if result is None:
        return None
    if not isinstance(result, Bands):
        raise TypeError("detector.bands 必须返回 Bands 或 None")
    return result
```

- [x] **Step 4: 在统计检测器中实现 `bands()`**

`_WindowedDetector` 增加：

```python
    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._center_scale(values)
        return Bands(
            baseline=center,
            lower=center - float(threshold) * scale,
            upper=center + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )
```

`SeasonalDetector` 把相位中心/尺度抽成 `_phase_center_scale(values)`，`score()` 与 `bands()` 共用：

```python
    def _phase_center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = len(values)
        center = np.full(n, np.nan)
        scale = np.full(n, np.nan)
        phases = np.arange(n) % self.period
        for phase in range(self.period):
            mask = phases == phase
            if mask.sum() < 2:
                continue
            group = values[mask]
            med = float(np.median(group))
            mad = float(np.median(np.abs(group - med))) * 1.4826
            if mad <= 0:
                mad = float(np.std(group))
            if mad <= 0:
                continue
            center[mask] = med
            scale[mask] = mad
        return center, scale

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._phase_center_scale(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(values - center) / scale
        return np.where(np.isfinite(scores), scores, 0.0)

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._phase_center_scale(values)
        return Bands(
            baseline=center,
            lower=center - float(threshold) * scale,
            upper=center + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )
```

`STLResidualDetector` 抽出 `_residual_parts(values)` 返回 `(fitted, abs_resid, scale)`；`score()` 与 `bands()` 共用：

```python
    def _residual_parts(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        from statsmodels.tsa.seasonal import STL

        fit = STL(values, period=self.period, robust=True).fit()
        fitted = np.asarray(fit.trend + fit.seasonal, dtype=float)
        abs_resid = np.abs(values - fitted)
        mad = float(np.median(np.abs(abs_resid - np.median(abs_resid)))) * 1.4826
        if mad <= 0:
            mad = float(np.std(abs_resid))
        return fitted, abs_resid, mad

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, abs_resid, mad = self._residual_parts(values)
        if mad <= 0:
            return np.zeros_like(values)
        return abs_resid / mad

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        values = np.asarray(series.values, dtype=float)
        fitted, _, mad = self._residual_parts(values)
        scale = np.full_like(values, mad)
        return Bands(
            baseline=fitted,
            lower=fitted - float(threshold) * scale,
            upper=fitted + float(threshold) * scale,
            detector=self.name,
            threshold=float(threshold),
        )
```

`DeseasonalizedIQRDetector` 抽出 `_trend_and_residual(values)`；`bands()` 返回 `trend + center ± k*scale`。

- [x] **Step 5: 跑测试**

Run: `.venv/bin/python -m pytest tests/detectors -v`
Expected: 全部 PASS。

- [x] **Step 6: 提交**

```bash
git add src/anomaly_lab/detectors/bands.py src/anomaly_lab/detectors/statistical.py tests/detectors/test_bands.py
git commit -m "feat: explainable baseline bands for statistical detectors"
```

### Task 2: 时间工具、校验与 SQLite 元数据存储

**Files:**
- Create: `src/anomaly_lab/platform/__init__.py`
- Create: `src/anomaly_lab/platform/timeutil.py`
- Create: `src/anomaly_lab/platform/validation.py`
- Create: `src/anomaly_lab/platform/models.py`
- Create: `src/anomaly_lab/platform/store.py`
- Test: `tests/platform/test_store.py`

- [x] **Step 1: 写失败测试**

```python
from datetime import UTC, datetime, timedelta

import pytest

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow


def _source(store):
    return store.add_source("local", "platform/source.db")


def _metric(store, source_id):
    return store.add_metric(
        source_id=source_id,
        name="cpu",
        query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="host",
        time_format="iso",
        freq="5min",
    )


def test_add_list_and_get_source(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    assert source.id == 1
    assert store.get_source(source.id).name == "local"
    assert store.list_sources()[0].path == "platform/source.db"


def test_duplicate_source_name_is_rejected(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source("local", "a.db")
    with pytest.raises(ValueError, match="已存在"):
        store.add_source("local", "b.db")


def test_add_job_defaults_schedule_to_now(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    before = utcnow()
    job = store.add_job(
        metric_id=metric.id,
        name="cpu-job",
        detector="seasonal",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=500,
        interval_seconds=300,
    )
    assert job.enabled is True
    assert job.next_run_at is not None
    assert datetime.fromisoformat(job.next_run_at) >= before - timedelta(seconds=1)


def test_job_rejects_critical_not_above_alert(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    with pytest.raises(ValueError, match="critical_threshold"):
        store.add_job(
            metric_id=metric.id,
            name="bad",
            detector="seasonal",
            alert_threshold=4.0,
            critical_threshold=4.0,
            window_points=500,
            interval_seconds=300,
        )


def test_due_jobs_reconcile_and_schedule_update(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="seasonal",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=500,
        interval_seconds=300,
    )
    past = to_iso(datetime(2000, 1, 1, tzinfo=UTC))
    store.set_job_next_run(job.id, past)
    assert [item.id for item in store.due_jobs(to_iso(utcnow()))] == [job.id]
    store.reconcile_missed(to_iso(utcnow()))
    due = store.due_jobs(to_iso(utcnow()))
    assert [item.id for item in due] == [job.id]
    assert due[0].next_run_at != past
    store.update_job_schedule(job.id, to_iso(utcnow()), to_iso(utcnow() + timedelta(seconds=300)))
    assert store.due_jobs(to_iso(utcnow())) == []


def test_run_lifecycle(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    job = store.add_job(metric_id=metric.id, name="job", detector="seasonal", alert_threshold=2.5,
                        critical_threshold=4.0, window_points=500, interval_seconds=300)
    run = store.create_run(job.id)
    assert run.status == "running"
    store.finish_run(run.id, "success", n_series=2, n_alerts=3)
    latest = store.latest_run(job.id)
    assert latest.status == "success"
    assert latest.n_alerts == 3
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_store.py -v`
Expected: FAIL，`ModuleNotFoundError: anomaly_lab.platform`

- [x] **Step 3: 实现时间与校验**

`timeutil.py`：

```python
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_FREQ = re.compile(r"^(\d+)(s|min|m|h|d)$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def freq_delta(freq: str) -> timedelta:
    match = _FREQ.fullmatch(freq.strip().lower())
    if not match:
        raise ValueError(f"不支持的频率: {freq!r}（示例：5min、1h、1d）")
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {"s": 1, "min": 60, "m": 60, "h": 3600, "d": 86400}[unit]
    return timedelta(seconds=amount * seconds)
```

`validation.py` 至少包含：

```python
import numpy as np

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)
_LITERAL = re.compile(r"'(?:''|[^'])*'")


def validate_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} 必须是合法 SQL 标识符")


def validate_query(query: str) -> str:
    text = query.strip().rstrip(";").strip()
    if not text.lower().startswith(("select", "with")):
        raise ValueError("查询必须以 SELECT 或 WITH 开头")
    if ";" in text:
        raise ValueError("查询只允许单条语句")
    if text.count("$timefilter") != 1:
        raise ValueError("查询必须且只能包含一个 $timefilter")
    clean = _LITERAL.sub("''", text)
    if _FORBIDDEN.search(clean):
        raise ValueError("查询包含不允许的写操作关键字")
    return text


def validate_thresholds(alert: float, critical: float) -> None:
    if not np.isfinite(alert) or not np.isfinite(critical):
        raise ValueError("阈值必须是有限数字")
    if critical <= alert:
        raise ValueError("critical_threshold 必须大于 alert_threshold")
```

- [x] **Step 4: 实现 `models.py` 与 `store.py`**

模型用 frozen dataclass：`Source`、`Metric`、`Job`、`Run`，字段与上面的 SQL 表一一对应。`store.py` 每次操作新建连接，`sqlite3.Row` 映射到 dataclass；建表时执行 `PRAGMA foreign_keys=ON` 与 `PRAGMA journal_mode=WAL`。`add_job` 将 `next_run_at` 默认设为创建时刻（首次运行立即到期）。名称重复时捕获 `sqlite3.IntegrityError` 并抛出中文 `ValueError`。

`PlatformStore` 公开方法清单（后续任务的调用契约）：

- 数据源：`add_source(name, path, kind="sqlite")`、`get_source(id)`、`list_sources()`、`find_source_by_name(name)`
- 指标：`add_metric(source_id, name, query, time_column, value_column, group_column, time_format, freq)`、`get_metric(id)`、`list_metrics()`、`find_metric_by_name(source_id, name)`
- 任务：`add_job(metric_id, name, detector, alert_threshold, critical_threshold, window_points, interval_seconds, enabled=True)`、`get_job(id)`、`list_jobs()`、`find_job_by_name(name)`、`set_job_enabled(id, enabled)`、`set_job_next_run(id, next_run_at)`、`update_job_schedule(id, last_run_at, next_run_at)`、`due_jobs(now_iso)`、`reconcile_missed(now_iso)`
- 运行：`create_run(job_id)`、`finish_run(id, status, n_series=0, n_alerts=0, error=None)`、`get_run(id)`、`list_runs(job_id, limit=20)`、`latest_run(job_id)`


- [x] **Step 5: 跑测试**

Run: `.venv/bin/python -m pytest tests/platform/test_store.py -v`
Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add src/anomaly_lab/platform tests/platform/test_store.py
git commit -m "feat: platform metadata store and scheduling state"
```

### Task 3: SQLite 只读加载与 group by 拆序列

**Files:**
- Create: `src/anomaly_lab/platform/sqlite_source.py`
- Test: `tests/platform/test_sqlite_source.py`

- [x] **Step 1: 写失败测试**

```python
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


def _metric():
    return Metric(id=1, source_id=1, name="demo", query=(
        "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts"
    ), time_column="ts", value_column="value", group_column="host",
        time_format="iso", freq="1min", created_at="")


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


def test_timefilter_limits_rows(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    start = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    end = datetime(2026, 1, 1, 0, 20, tzinfo=UTC)
    series = load_series(_metric(), path, start, end)
    assert all(s.n == 10 for s in series)


def test_rejects_non_select_query(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    metric = _metric()
    metric = Metric(**{**metric.__dict__, "query": "DELETE FROM metrics WHERE $timefilter"})
    with pytest.raises(ValueError, match="SELECT"):
        load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))


def test_missing_group_column_returns_error(tmp_path):
    path = tmp_path / "source.db"
    _db(path)
    metric = Metric(**{** _metric().__dict__, "group_column": "missing"})
    with pytest.raises(ValueError, match="group_column"):
        load_series(metric, path, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_sqlite_source.py -v`
Expected: FAIL，模块不存在。

- [x] **Step 3: 实现只读加载**

关键点：

```python
MAX_ROWS = 100_000


def _connect(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _time_value(value: datetime, time_format: str):
    if time_format == "iso":
        return value.astimezone(UTC).isoformat()
    stamp = value.timestamp()
    if time_format == "epoch_s":
        return int(stamp)
    if time_format == "epoch_ms":
        return int(stamp * 1000)
    raise ValueError(f"不支持的 time_format: {time_format}")


def load_series(metric: Metric, source_path: Path, start: datetime, end: datetime) -> list[SeriesBundle]:
    query = validate_query(metric.query)
    validate_identifier(metric.time_column, "time_column")
    validate_identifier(metric.value_column, "value_column")
    if metric.group_column:
        validate_identifier(metric.group_column, "group_column")
    if not Path(source_path).exists():
        raise FileNotFoundError(f"数据源不存在: {source_path}")

    clause = f'"{metric.time_column}" >= ? AND "{metric.time_column}" < ?'
    sql = f"SELECT * FROM ({query.replace('$timefilter', clause)}) LIMIT ?"
    params = (_time_value(start, metric.time_format), _time_value(end, metric.time_format), MAX_ROWS + 1)
    with _connect(Path(source_path)) as conn:
        cursor = conn.execute(sql, params)
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    if len(rows) > MAX_ROWS:
        raise ValueError(f"单次查询超过 {MAX_ROWS} 行，请缩小窗口或增加聚合")
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return []
    if metric.group_column and metric.group_column not in frame.columns:
        raise ValueError(f"查询结果缺少 group_column: {metric.group_column}")
    if metric.time_format == "iso":
        frame[metric.time_column] = pd.to_datetime(frame[metric.time_column], utc=True)
    elif metric.time_format in {"epoch_s", "epoch_ms"}:
        unit = "s" if metric.time_format == "epoch_s" else "ms"
        numeric = pd.to_numeric(frame[metric.time_column], errors="raise")
        frame[metric.time_column] = pd.to_datetime(numeric, unit=unit, utc=True)
    else:
        raise ValueError(f"不支持的 time_format: {metric.time_format}")
    frame = frame.sort_values(metric.time_column)
    groups = [(None, frame)] if not metric.group_column else frame.groupby(metric.group_column, dropna=False)
    result = []
    for raw_group, part in groups:
        group = "null" if raw_group is None else str(raw_group)
        values = pd.to_numeric(part[metric.value_column], errors="raise").to_numpy(dtype=float)
        timestamps = part[metric.time_column].dt.tz_convert(None).to_numpy(dtype="datetime64[ns]")
        series_id = metric.name if raw_group is None else f"{metric.name}:{group}"
        result.append(SeriesBundle(series_id=series_id, values=values, timestamps=timestamps,
            freq=metric.freq, meta={"metric_id": metric.id, "metric_name": metric.name,
            "group": None if raw_group is None else group, "source_id": metric.source_id}))
    return sorted(result, key=lambda item: item.series_id)
```

`iso` 用 `pd.to_datetime(..., utc=True)`；`epoch_s/ms` 用 `unit="s"/"ms"`。禁止用 f-string 拼用户值，只有已校验的列名可插入 SQL；时间范围用参数绑定。

- [x] **Step 4: 跑测试**

Run: `.venv/bin/python -m pytest tests/platform/test_sqlite_source.py -v`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add src/anomaly_lab/platform/sqlite_source.py tests/platform/test_sqlite_source.py
git commit -m "feat: read-only sqlite source with group-by splitting"
```

---

## Chunk 2: 执行与调度

### Task 4: 检测器注册、任务执行与结果落盘

**Files:**
- Create: `src/anomaly_lab/platform/detectors.py`
- Create: `src/anomaly_lab/platform/runner.py`
- Test: `tests/platform/test_runner.py`

- [x] **Step 1: 写失败测试**

```python
import json
import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np

from anomaly_lab.platform.runner import execute_job, run_dir
from anomaly_lab.platform.store import PlatformStore


def _seed(tmp_path):
    data = tmp_path
    db = data / "platform" / "source.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(60):
        rows.append(((start + timedelta(minutes=5 * i)).isoformat(), "a", float(i % 10)))
        rows.append(((start + timedelta(minutes=5 * i)).isoformat(), "b", float(i % 5)))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    store = PlatformStore(data / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(source_id=source.id, name="demo", query=(
        "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts"),
        time_column="ts", value_column="value", group_column="host", time_format="iso", freq="5min")
    job = store.add_job(metric_id=metric.id, name="job", detector="seasonal",
        alert_threshold=1.0, critical_threshold=2.0, window_points=60, interval_seconds=300)
    return store, job, start


def test_execute_job_writes_index_and_arrays(tmp_path):
    store, job, start = _seed(tmp_path)
    run_id = execute_job(store, job.id, data_root=tmp_path, start=start,
                         end=start + timedelta(minutes=300))
    run = store.get_run(run_id)
    assert run.status == "success"
    assert run.n_series == 2
    index = json.loads((run_dir(tmp_path, run_id) / "index.json").read_text())
    assert len(index["series"]) == 2
    entry = index["series"][0]
    payload = np.load(run_dir(tmp_path, run_id) / entry["file"])
    for key in ("timestamps", "values", "scores", "baseline", "lower", "upper", "severity"):
        assert key in payload
    assert payload["severity"].max() <= 2


def test_execute_job_records_failure(tmp_path):
    store, job, start = _seed(tmp_path)
    (tmp_path / "platform" / "source.db").unlink()
    try:
        execute_job(store, job.id, data_root=tmp_path, start=start, end=start + timedelta(hours=1))
    except FileNotFoundError:
        pass
    runs = store.list_runs(job.id)
    assert runs[0].status == "failed"
    assert "不存在" in runs[0].error
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_runner.py -v`
Expected: FAIL，模块不存在。

- [x] **Step 3: 实现检测器注册表**

```python
DETECTOR_FACTORIES = {
    "iqr": IQRDetector,
    "mad": MADDetector,
    "zscore": ZScoreDetector,
    "seasonal": SeasonalDetector,
    "stl_residual": lambda: STLResidualDetector(period=24),
    "deseasonalized_iqr": DeseasonalizedIQRDetector,
}


def create_detector(name: str):
    try:
        return DETECTOR_FACTORIES[name]()
    except KeyError as exc:
        raise ValueError(f"不支持的检测器: {name}") from exc


def detector_catalog() -> list[dict]:
    rows = []
    for name, factory in DETECTOR_FACTORIES.items():
        detector = factory()
        rows.append({"name": name, "default_threshold": detector.default_threshold})
    return rows
```

- [x] **Step 4: 实现 `runner.py`**

```python
def run_dir(data_root: Path, run_id: int) -> Path:
    return Path(data_root) / "cache" / "platform" / "runs" / str(run_id)


def _severity(scores: np.ndarray, alert: float, critical: float) -> np.ndarray:
    result = np.zeros(len(scores), dtype=np.int8)
    result[scores > alert] = 1
    result[scores > critical] = 2
    return result


def execute_job(store, job_id, *, data_root, start=None, end=None, now=None) -> int:
    job = store.get_job(job_id)
    run = store.create_run(job.id)
    try:
        metric = store.get_metric(job.metric_id)
        source = store.get_source(metric.source_id)
        end = end or now or utcnow()
        start = start or (end - freq_delta(metric.freq) * job.window_points)
        source_path = Path(source.path)
        if not source_path.is_absolute():
            source_path = Path(data_root) / source_path
        series_list = load_series(metric, source_path, start, end)

        target = run_dir(data_root, run.id)
        target.mkdir(parents=True, exist_ok=True)
        entries = []
        total_alerts = 0
        for series in series_list:
            detector = create_detector(job.detector).fit(series)
            result = detector.detect(series, threshold=job.alert_threshold)
            bands = compute_bands(detector, series, job.alert_threshold)
            severity = _severity(result.scores, job.alert_threshold, job.critical_threshold)
            filename = hashlib.sha1(series.series_id.encode()).hexdigest()[:16] + ".npz"
            np.savez_compressed(
                target / filename,
                timestamps=series.timestamps.astype("datetime64[ns]").astype(np.int64),
                values=series.values,
                scores=result.scores,
                baseline=np.asarray(bands.baseline if bands else []),
                lower=np.asarray(bands.lower if bands else []),
                upper=np.asarray(bands.upper if bands else []),
                severity=severity,
                alert_threshold=np.array(job.alert_threshold),
                critical_threshold=np.array(job.critical_threshold),
                detector=np.array(result.detector),
                score_type=np.array(result.score_type),
                series_id=np.array(series.series_id),
                group=np.array(str(series.meta.get("group", ""))),
            )
            n_alerts = int((severity > 0).sum())
            total_alerts += n_alerts
            entries.append({"series_id": series.series_id, "group": series.meta.get("group"),
                            "n": series.n, "n_alerts": n_alerts,
                            "n_p0": int((severity == 2).sum()), "file": filename})
        index = {"run_id": run.id, "job_id": job.id, "generated_at": to_iso(utcnow()),
                 "series": entries}
        (target / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        store.finish_run(run.id, "success", n_series=len(entries), n_alerts=total_alerts)
        return run.id
    except Exception as exc:
        store.finish_run(run.id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise
```

消息中的错误 text 要包含原始异常；`FileNotFoundError` 的文本由 loader 给出。

- [x] **Step 5: 跑测试**

Run: `.venv/bin/python -m pytest tests/platform/test_runner.py -v`
Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add src/anomaly_lab/platform/detectors.py src/anomaly_lab/platform/runner.py tests/platform/test_runner.py
git commit -m "feat: run detection jobs with bands and severity"
```

### Task 5: 重启恢复的内置调度器

**Files:**
- Create: `src/anomaly_lab/platform/scheduler.py`
- Test: `tests/platform/test_scheduler.py`

- [x] **Step 1: 写失败测试**

```python
from datetime import UTC, datetime, timedelta

from anomaly_lab.platform.scheduler import Scheduler
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow


def _job(store, name="job"):
    source = store.add_source(f"src-{name}", "platform/source.db")
    metric = store.add_metric(source_id=source.id, name=f"m-{name}",
        query="SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts", value_column="value", group_column=None, time_format="iso", freq="5min")
    return store.add_job(metric_id=metric.id, name=name, detector="iqr",
        alert_threshold=2.5, critical_threshold=4.0, window_points=10, interval_seconds=300)


def test_tick_runs_due_job_once_and_advances_schedule(tmp_path, monkeypatch):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    calls = []
    scheduler = Scheduler(store, tmp_path, runner=lambda *args, **kwargs: calls.append(kwargs) or 1)
    now = utcnow()
    assert scheduler.tick(now=now) == [1]
    assert len(calls) == 1
    assert scheduler.tick(now=now) == []
    assert store.get_job(job.id).next_run_at > to_iso(now)


def test_reconcile_missed_only_runs_once(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    store.set_job_next_run(job.id, to_iso(datetime(2000, 1, 1, tzinfo=UTC)))
    calls = []
    scheduler = Scheduler(store, tmp_path, runner=lambda *args, **kwargs: calls.append(kwargs) or 1)
    scheduler.reconcile(now=utcnow())
    assert scheduler.tick(now=utcnow()) == [1]
    assert scheduler.tick(now=utcnow()) == []
    assert len(calls) == 1


def test_disabled_job_is_skipped(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    store.set_job_enabled(job.id, False)
    calls = []
    scheduler = Scheduler(store, tmp_path, runner=lambda *args, **kwargs: calls.append(kwargs) or 1)
    assert scheduler.tick(now=utcnow()) == []
    assert calls == []
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/platform/test_scheduler.py -v`
Expected: FAIL，模块不存在。

- [x] **Step 3: 实现调度器**

```python
class Scheduler:
    def __init__(self, store, data_root, poll_seconds=2.0, runner=None):
        self.store = store
        self.data_root = Path(data_root)
        self.poll_seconds = float(poll_seconds)
        self.runner = runner or execute_job
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    def reconcile(self, now=None):
        self.store.reconcile_missed(to_iso(now or utcnow()))

    def tick(self, now=None):
        now = now or utcnow()
        run_ids = []
        with self._lock:
            for job in self.store.due_jobs(to_iso(now)):
                try:
                    run_ids.append(self.runner(self.store, job.id, data_root=self.data_root, now=now))
                except Exception:
                    pass
                next_run = now + timedelta(seconds=job.interval_seconds)
                self.store.update_job_schedule(job.id, to_iso(now), to_iso(next_run))
        return run_ids

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.reconcile()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="anomaly-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            self.tick()
```

一个重要语义：`tick` 无论成功失败都推进 `next_run_at = now + interval`，所以失败任务不会每个轮询周期重试风暴；失败详情在 `runs` 表可见。

- [x] **Step 4: 跑测试**

Run: `.venv/bin/python -m pytest tests/platform/test_scheduler.py -v`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add src/anomaly_lab/platform/scheduler.py tests/platform/test_scheduler.py
git commit -m "feat: restart-safe in-process job scheduler"
```

---

## Chunk 3: Web、Demo 与文档

### Task 6: Platform API 与预览页

**Files:**
- Create: `src/anomaly_lab/web/platform_routes.py`
- Create: `src/anomaly_lab/web/templates/platform.html`
- Create: `src/anomaly_lab/web/static/platform.js`
- Modify: `src/anomaly_lab/web/app.py`
- Modify: `src/anomaly_lab/web/templates/base.html`
- Modify: `src/anomaly_lab/web/static/style.css`
- Test: `tests/web/test_platform.py`

- [x] **Step 1: 写失败测试**

```python
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _client(tmp_path):
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = utcnow() - timedelta(minutes=5 * 60)
    for i in range(60):
        ts = to_iso(start + timedelta(minutes=5 * i))
        conn.execute("INSERT INTO metrics VALUES (?, ?, ?)", (ts, "a", float(i % 10)))
    conn.commit()
    conn.close()
    store = PlatformStore(tmp_path / "platform.db")
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    return TestClient(app), store


def test_create_source_metric_job_run_and_preview(tmp_path):
    client, store = _client(tmp_path)
    source = client.post("/api/platform/sources", json={"name": "local", "path": "platform/source.db"})
    assert source.status_code == 200
    source_id = source.json()["id"]
    metric = client.post("/api/platform/metrics", json={
        "source_id": source_id, "name": "demo",
        "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        "time_column": "ts", "value_column": "value", "group_column": "host",
        "time_format": "iso", "freq": "5min",
    })
    assert metric.status_code == 200
    job = client.post("/api/platform/jobs", json={
        "metric_id": metric.json()["id"], "name": "job", "detector": "seasonal",
        "alert_threshold": 1.0, "critical_threshold": 2.0,
        "window_points": 60, "interval_seconds": 300,
    })
    assert job.status_code == 200
    job_id = job.json()["id"]

    run = client.post(f"/api/platform/jobs/{job_id}/run")
    assert run.status_code == 200
    run_id = run.json()["run_id"]
    preview = client.get(f"/api/platform/jobs/{job_id}/preview?run_id={run_id}")
    assert preview.status_code == 200
    body = preview.json()
    assert body["series_id"] == "demo:a"
    assert len(body["values"]) == 60
    assert len(body["baseline"]) == 60
    assert set(body["severity"]) <= {0, 1, 2}


def test_platform_page_and_catalog(tmp_path):
    client, _ = _client(tmp_path)
    page = client.get("/platform")
    assert page.status_code == 200
    assert "定时检测" in page.text
    catalog = client.get("/api/platform/catalog").json()
    assert "seasonal" in [item["name"] for item in catalog["detectors"]]
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/web/test_platform.py -v`
Expected: FAIL，没有 `/platform` 路由。

- [x] **Step 3: 实现路由**

`platform_routes.py` 使用 `APIRouter`，工厂：

```python
def build_router(get_store, get_data_root):
    router = APIRouter()

    @router.get("/platform", response_class=HTMLResponse)
    def page(request: Request):
        return templates.TemplateResponse(request, "platform.html", {})

    @router.get("/api/platform/catalog")
    def catalog():
        store = get_store()
        return {
            "sources": [_asdict(item) for item in store.list_sources()],
            "metrics": [_asdict(item) for item in store.list_metrics()],
            "jobs": [_asdict(item) for item in store.list_jobs()],
            "detectors": detector_catalog(),
        }

    @router.post("/api/platform/sources")
    def create_source(payload: SourceIn):
        return _asdict(get_store().add_source(payload.name, payload.path))

    # metrics/jobs 同理；ValueError/sqlite3.DatabaseError -> HTTPException(400)

    @router.post("/api/platform/jobs/{job_id}/run")
    def run_job(job_id: int):
        run_id = execute_job(get_store(), job_id, data_root=get_data_root())
        return {"run_id": run_id, "status": get_store().get_run(run_id).status}

    @router.get("/api/platform/jobs/{job_id}/preview")
    def preview(job_id: int, run_id: int | None = None, series_id: str | None = None):
        # 校验 job/run，读 run_dir/index.json，选择第一条或指定 series_id
        # 返回 timestamps/values/scores/baseline/lower/upper/severity/thresholds
```

模型输入用 pydantic：`SourceIn(name,path)`、`MetricIn(...)`、`JobIn(...)`。`JobIn` 的阈值可为 `None`，服务端用 `create_detector(name).default_threshold` 补默认值，`critical` 默认 `alert*1.5`。`baseline/lower/upper` 为空数组时返回 `None`，前端显示“该算法无上下界”。

`app.py` 的修改：

```python
from contextlib import asynccontextmanager

def create_app(platform_store=None, platform_data_root=None, start_scheduler=False):
    data_root = Path(platform_data_root or _data_root())
    store = platform_store

    def get_store():
        nonlocal store
        if store is None:
            store = PlatformStore(data_root / "platform.db")
        return store

    scheduler = Scheduler(get_store(), data_root) if start_scheduler else None

    @asynccontextmanager
    async def lifespan(app):
        if scheduler is not None:
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.stop()

    app = FastAPI(title="anomaly-lab", lifespan=lifespan)
    app.include_router(build_router(get_store, lambda: data_root))
    # 其余既有路由保持不变
```

其中 `get_store()` 是闭包，首次调用才创建 `PlatformStore(data_root / "platform.db")`，避免只访问首页时创建数据库。保留现有 `create_app()` 的无参兼容；测试不启动线程。

- [x] **Step 4: 实现页面**

`platform.html` 包含四块：数据源、指标、检测任务、预览。`platform.js` 用 fetch 完成：

- 页面加载：`GET /api/platform/catalog`，填三个列表和检测器下拉。
- 新建数据源/指标/任务后刷新 catalog。
- 任务表“立即运行” → POST run → 刷新 runs → 自动预览。
- 预览图：`series` 数组包含实际值、baseline（虚线）、upper/lower（细线）；`P1` 用橙色 scatter，`P0` 用红色 scatter；x 轴为 timestamps；tooltip 显示 score/severity。
- 表单里检测器切换时自动填入默认阈值，用户可改。

`base.html` 导航加 `<a href="/platform">定时检测</a>`。

- [x] **Step 5: 跑测试**

Run: `.venv/bin/python -m pytest tests/web -v`
Expected: 新旧 Web 测试全部 PASS。

- [x] **Step 6: 提交**

```bash
git add src/anomaly_lab/web tests/web/test_platform.py
git commit -m "feat: platform config and baseline preview UI"
```

### Task 7: Demo、CLI、Makefile 与文档

**Files:**
- Create: `src/anomaly_lab/platform/demo.py`
- Modify: `src/anomaly_lab/cli.py`
- Modify: `Makefile`
- Create: `docs/PLATFORM.md`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Test: `tests/test_cli.py`

- [x] **Step 1: 写失败测试**

```python
def test_platform_demo_command_creates_source_metric_job(tmp_path, capsys):
    from anomaly_lab.cli import main
    from anomaly_lab.platform.store import PlatformStore

    rc = main(["platform-demo", "--data", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "platform" / "source.db").exists()
    store = PlatformStore(tmp_path / "platform.db")
    assert len(store.list_sources()) == 1
    assert len(store.list_metrics()) == 1
    assert len(store.list_jobs()) == 1
    assert "platform" in capsys.readouterr().out
```

- [x] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_platform_demo_command_creates_source_metric_job -v`
Expected: FAIL，未知命令。

- [x] **Step 3: 实现 demo 与 CLI**

`demo.py` 使用现有 `generate_series` 生成 `periodic` 和 `stationary`，把时间戳平移到“当前时刻往前 500 个 5 分钟点”，写入 `data/platform/source.db` 的 `metrics(ts, series, value)`。SQLite 文件路径存为相对 `platform/source.db`，这样数据目录可整体搬移。

默认查询：

```sql
SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts
```

默认任务：`seasonal`、`alert=2.5`、`critical=4.0`、`window_points=500`、`interval_seconds=300`。

CLI：

- `platform-demo --data <dir>`：幂等；已存在则打印现有 ID。
- `serve --no-scheduler`：默认启动调度器，`--no-scheduler` 用于只跑 Web/调试。

`_cmd_serve`：

```python
uvicorn.run(create_app(start_scheduler=not args.no_scheduler), host=args.host, port=args.port)
```

Makefile 增加：

```make
platform-demo:
	$(PY) -m anomaly_lab.cli platform-demo --data data
```

- [x] **Step 4: 写文档**

`docs/PLATFORM.md` 必须包含：快速体验步骤、数据源/指标/任务字段解释、`$timefilter` 与 group by 示例、基线/上下界/P1/P0 语义、调度重启语义、已知限制（进程内预处理、单 SQLite 源、无认证、多 worker 会重复调度、未做未来预测）。

README 快速开始末尾增加：

```bash
make platform-demo
make serve
# 打开 http://127.0.0.1:8000/platform
```

ARCHITECTURE 增加平台分层图；ROADMAP 增加开放项：数据源插件、预处理独立 worker、预测区间校准、多 worker 调度锁、认证。

- [x] **Step 5: 跑测试与 lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests`
Expected: 全部通过。

- [x] **Step 6: 提交**

```bash
git add src/anomaly_lab/platform/demo.py src/anomaly_lab/cli.py Makefile docs/PLATFORM.md README.md docs/ARCHITECTURE.md docs/ROADMAP.md tests/test_cli.py
git commit -m "feat: platform demo command and docs"
```

### Task 8: 最终验收

- [x] **Step 1: 全量测试与 lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m ruff check src tests`
Expected: 0 failed，ruff 全绿。

- [x] **Step 2: 重跑原有 smoke**

Run: `make smoke`
Expected: 分类、检测、评估、compliance-check 全部成功。

- [x] **Step 3: 平台冒烟**

```bash
rm -rf /tmp/anomaly-platform-smoke
make platform-demo --data /tmp/anomaly-platform-smoke
.venv/bin/python - <<'PY'
from pathlib import Path
from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore

root = Path("/tmp/anomaly-platform-smoke")
store = PlatformStore(root / "platform.db")
job = store.list_jobs()[0]
run_id = execute_job(store, job.id, data_root=root)
print("run", run_id, store.get_run(run_id))
PY
```

Expected: `status='success'`，`n_series=2`，`n_alerts>0`。

- [x] **Step 4: 浏览器/接口人工检查**

Run: `.venv/bin/python -m anomaly_lab.cli serve --no-scheduler`
打开 `/platform`，确认：
- 能看到 demo 数据源、指标、任务。
- 点击“立即运行”后出现 run。
- 预览图有实际值、基线、上下界、橙色 P1/红色 P0 点。
- 切换序列后图更新。

- [x] **Step 5: 检查未提交文件**

Run: `git status --short`
Expected: 只有用户自己的 `docs/DESIGN.md` 和 `docs/my-thought.md` 保持未提交；不要 `git add -A` 误提交。

- [x] **Step 6: 最终提交**

```bash
git add src tests docs/PLATFORM.md README.md docs/ARCHITECTURE.md docs/ROADMAP.md Makefile
git commit -m "docs: platform vertical slice acceptance"
```
