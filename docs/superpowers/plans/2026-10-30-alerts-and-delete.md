# 告警中心与删除功能 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 ROADMAP 剩余两项 —— 跨任务告警事件列表页（只读）与任务/指标/数据源的级联删除。

**Architecture:**
- 告警中心**不改 schema**：告警明细在 run 目录的 npz 里，新增纯逻辑模块 `platform/alert_events.py` 把逐点 `severity` 合并成区间，端点 `GET /api/platform/alerts` 在**查询期**聚合每个任务的最新一次成功运行。
- 删除功能**不改 schema**：`ON DELETE CASCADE` + `PRAGMA foreign_keys=ON` 已就绪，补 store 方法 + `DELETE` 端点；额外清理 run 目录文件（数据库外键管不到的那一半）。

**Tech Stack:** Python 3.12 + FastAPI + SQLite + numpy / React 18 + TypeScript + Vite + AntD v5 + TanStack Query + vitest

**设计依据：** `docs/superpowers/specs/2026-10-30-alerts-and-delete-design.md`

---

## 文件结构

### 后端（新建 / 修改）

| 文件 | 责任 |
|---|---|
| `src/anomaly_lab/platform/alert_events.py` | **新建**。`AlertEvent` 数据类 + 区间合并纯函数 + 跨任务聚合。纯逻辑，不碰 HTTP |
| `src/anomaly_lab/platform/store.py` | **修改**。加 `delete_job` / `delete_metric` / `delete_source` 三个方法 |
| `src/anomaly_lab/platform/runner.py` | **修改**。加 `is_running(job_id)` —— 暴露 `_INFLIGHT` 的只读视图给删除端点 |
| `src/anomaly_lab/web/platform_routes.py` | **修改**。加 `GET /api/platform/alerts` 与三个 `DELETE` 端点 |
| `tests/platform/test_alert_events.py` | **新建**。区间合并纯函数的单测 |
| `tests/web/test_alerts_endpoint.py` | **新建**。端点 + 筛选 + skipped |
| `tests/web/test_delete_endpoints.py` | **新建**。级联删除 + 文件清理 + 409 |
| `tests/web/test_api_contract.py` | **修改**。加 `/api/platform/alerts` 字段守卫 |

### 前端（新建 / 修改）

| 文件 | 责任 |
|---|---|
| `frontend/src/api/types.ts` | **修改**。加 `AlertEvent` / `AlertListResponse` / `DeleteStats` |
| `frontend/src/api/platform.ts` | **修改**。加 `getAlerts` / `deleteJob` / `deleteMetric` / `deleteSource` |
| `frontend/src/features/alerts/queries.ts` | **新建**。`useAlerts` |
| `frontend/src/features/alerts/AlertList.tsx` | **新建**。告警事件表格 + 筛选栏 |
| `frontend/src/pages/AlertsPage.tsx` | **新建**。页面装配 |
| `frontend/src/features/alerts/alerts.test.tsx` | **新建**。渲染 / 筛选 / 空态 |
| `frontend/src/features/delete/queries.ts` | **新建**。三个删除 mutation |
| `frontend/src/features/delete/DeleteButton.tsx` | **新建**。Popconfirm 包装的删除按钮 |
| `frontend/src/features/delete/DeleteButton.test.tsx` | **新建**。确认文案带连带数量 |
| `frontend/src/features/delete/impact.ts` | **新建**。从 catalog 算依赖数量（纯函数，可测） |
| `frontend/src/router.tsx` | **修改**。加 `/alerts` 路由 |
| `frontend/src/components/AppLayout.tsx` | **修改**。侧边栏加「告警中心」 |
| `frontend/src/features/sources/SourceList.tsx` | **修改**。加删除列 |
| `frontend/src/features/metrics/MetricList.tsx` | **修改**。加删除列 |
| `frontend/src/features/jobs/JobList.tsx` | **修改**。操作列加删除按钮 |
| `frontend/src/pages/SourcesPage.tsx` | **修改**。接删除 mutation |
| `frontend/src/pages/MetricsPage.tsx` | **修改**。接删除 mutation |
| `frontend/src/pages/JobsPage.tsx` | **修改**。接删除 mutation |

---

# Chunk 1: 告警中心

## Task 1: 告警事件的数据结构与区间合并

**Files:**
- Create: `src/anomaly_lab/platform/alert_events.py`
- Test: `tests/platform/test_alert_events.py`

- [ ] **Step 1: 写失败的测试**

`tests/platform/test_alert_events.py`：

```python
"""告警事件：把逐点 severity 合并成连续区间。"""

from __future__ import annotations

import numpy as np
import pytest

from anomaly_lab.platform.alert_events import merge_alert_intervals


def test_single_alert_point_becomes_one_interval():
    intervals = merge_alert_intervals(np.array([0, 0, 1, 0, 0]))
    assert intervals == [(2, 2, 1)]


def test_consecutive_alert_points_merge_into_one_interval():
    intervals = merge_alert_intervals(np.array([0, 1, 1, 1, 0]))
    assert intervals == [(1, 3, 1)]


def test_normal_point_between_alerts_splits_intervals():
    intervals = merge_alert_intervals(np.array([1, 1, 0, 1, 1]))
    assert intervals == [(0, 1, 1), (3, 4, 1)]


def test_interval_level_is_the_maximum_severity_inside_it():
    intervals = merge_alert_intervals(np.array([1, 2, 1, 0]))
    assert intervals == [(0, 2, 2)]


def test_no_alert_yields_no_interval():
    assert merge_alert_intervals(np.array([0, 0, 0])) == []


def test_severity_zero_is_normal_not_alert():
    # severity 是 int16，0 = 正常；负数不存在但也不该被当成告警
    assert merge_alert_intervals(np.array([0, -1, 0])) == []


def test_empty_input_yields_no_interval():
    assert merge_alert_intervals(np.array([], dtype="int16")) == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/platform/test_alert_events.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'anomaly_lab.platform.alert_events'`

- [ ] **Step 3: 写最小实现**

`src/anomaly_lab/platform/alert_events.py`：

```python
"""把一次运行的检测结果汇总成「告警事件」。

定位：告警事件的**读侧模型**。告警明细不在数据库里 —— 它躺在每次运行的
npz 里（逐点的 `severity` 数组），本模块负责把它读出来、聚合成区间。

⚠️ **以任务的最新一次运行为准**：平台任务是滚动窗口，同一段异常会被
连续多次运行重复报出。扫全部历史 run 会让同一个异常区间出现很多遍，
所以只取最新一次 —— 语义是「当前各任务处于什么告警状态」。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from anomaly_lab.platform.alerts import SEVERITY_NORMAL
from anomaly_lab.platform.runner import run_dir


@dataclass(frozen=True)
class AlertEvent:
    """一条告警事件：一段连续告警点合并成的区间。"""

    job_id: int
    job_name: str
    metric_id: int
    metric_name: str
    series_id: str
    group: str | None
    #: 档位名（来自任务的规则表，可能是 P0/P1，也可能是自定义的「注意」）
    level: str
    #: 档位序号，越大越严重（1 = 最低档）
    level_index: int
    start_ts: str
    end_ts: str
    #: 区间内的告警点数
    n_points: int
    #: 区间内的峰值分数
    max_score: float
    detector: str
    score_type: str
    run_id: int


def merge_alert_intervals(severity: np.ndarray) -> list[tuple[int, int, int]]:
    """把逐点 severity 合并成连续区间。

    返回 `[(起始下标, 结束下标, 区间内最高档位序号), ...]`（闭区间）。

    - `severity > 0` 的点算告警；`0` 是正常。
    - 连续的告警点合成一个区间；中间隔着正常点就断开。
    - 区间里的档位取**最大值**（最严重的那一档代表这个区间）。
    """
    severity = np.asarray(severity)
    if severity.size == 0:
        return []
    intervals: list[tuple[int, int, int]] = []
    start: int | None = None
    for index in range(len(severity)):
        if severity[index] > SEVERITY_NORMAL:
            if start is None:
                start = index
        elif start is not None:
            intervals.append((start, index - 1, int(severity[start:index].max())))
            start = None
    if start is not None:
        intervals.append((start, len(severity) - 1, int(severity[start:].max())))
    return intervals
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/platform/test_alert_events.py -q
```

Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
cd ~/Project/anomaly-lab && git add src/anomaly_lab/platform/alert_events.py tests/platform/test_alert_events.py && git commit -m "feat(platform): 告警事件的数据结构与区间合并"
```

---

## Task 2: 从一次运行产出事件 + 跨任务聚合

**Files:**
- Modify: `src/anomaly_lab/platform/alert_events.py`
- Modify: `tests/platform/test_alert_events.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/platform/test_alert_events.py`：

```python
from anomaly_lab.platform.alert_events import events_from_series


def _events(severity, scores, levels=("正常", "P1", "P0")):
    return events_from_series(
        severity=np.asarray(severity, dtype="int16"),
        timestamps=np.arange(len(severity)).astype("datetime64[m]"),
        scores=np.asarray(scores, dtype=float),
        levels=list(levels),
        job_id=1,
        job_name="demo-job",
        metric_id=2,
        metric_name="demo-metric",
        series_id="demo-metric:web-api",
        group="web-api",
        detector="iqr",
        score_type="zscore",
        run_id=7,
    )


def test_event_carries_interval_bounds_and_peak_score():
    events = _events([0, 1, 1, 0, 2], [0.1, 0.5, 0.9, 0.2, 1.5])
    assert len(events) == 2
    first = events[0]
    assert first.start_ts == "1970-01-01T00:01:00"
    assert first.end_ts == "1970-01-01T00:02:00"
    assert first.n_points == 2
    assert first.max_score == 0.9
    assert first.level_index == 1
    assert first.level == "P1"


def test_event_level_name_comes_from_levels_table():
    events = _events([0, 2], [0.1, 1.0])
    assert events[0].level_index == 2
    assert events[0].level == "P0"


def test_event_level_falls_back_when_index_out_of_range():
    """档位表比实际严重度短时不能崩 —— 退回「未知」而不是 IndexError。"""
    events = _events([0, 2], [0.1, 1.0], levels=("正常", "P1"))
    assert events[0].level == "未知"
    assert events[0].level_index == 2
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/platform/test_alert_events.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'events_from_series'`

- [ ] **Step 3: 写实现**

在 `src/anomaly_lab/platform/alert_events.py` 追加：

```python
def _iso(ts: np.datetime64) -> str:
    """时间戳 → ISO 秒精度字符串（与 preview 端点的格式一致）。"""
    return str(np.datetime64(ts).astype("datetime64[s]"))


def events_from_series(
    *,
    severity: np.ndarray,
    timestamps: np.ndarray,
    scores: np.ndarray,
    levels: list[str],
    job_id: int,
    job_name: str,
    metric_id: int,
    metric_name: str,
    series_id: str,
    group: str | None,
    detector: str,
    score_type: str,
    run_id: int,
) -> list[AlertEvent]:
    """把一条序列的逐点 severity 转成告警事件列表。"""
    events: list[AlertEvent] = []
    for start, end, level_index in merge_alert_intervals(severity, timestamps):
        level = levels[level_index] if 0 < level_index < len(levels) else "未知"
        window = scores[start : end + 1]
        events.append(
            AlertEvent(
                job_id=job_id,
                job_name=job_name,
                metric_id=metric_id,
                metric_name=metric_name,
                series_id=series_id,
                group=group,
                level=level,
                level_index=level_index,
                start_ts=_iso(timestamps[start]),
                end_ts=_iso(timestamps[end]),
                n_points=end - start + 1,
                max_score=float(window.max()) if window.size else 0.0,
                detector=detector,
                score_type=score_type,
                run_id=run_id,
            )
        )
    return events
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/platform/test_alert_events.py -q
```

Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
cd ~/Project/anomaly-lab && git add src/anomaly_lab/platform/alert_events.py tests/platform/test_alert_events.py && git commit -m "feat(platform): 从单条序列的 severity 产出告警事件"
```

---

## Task 3: 跨任务聚合 + `GET /api/platform/alerts` 端点

**Files:**
- Modify: `src/anomaly_lab/platform/alert_events.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Test: `tests/web/test_alerts_endpoint.py`

- [ ] **Step 1: 写失败的测试**

`tests/web/test_alerts_endpoint.py`：

```python
"""告警中心端点：跨任务汇总 + 筛选 + skipped 诚实报告。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(platform_data_root=tmp_path))


def _seed_source_metric_job(client) -> int:
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    ).json()
    job = client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric["id"],
            "name": "demo-job",
            "detector": "iqr",
            "alert_rules": [{"multiplier": 2.5, "level": "P1"}],
        },
    ).json()
    return job["id"]


def test_alerts_endpoint_returns_empty_list_when_no_job(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/platform/alerts").json()
    assert body["events"] == []
    assert body["jobs"] == []


def test_job_without_run_is_reported_as_skipped(tmp_path):
    """⚠️ 没跑过的任务不能静默消失 —— 必须进 skipped 并说明原因。"""
    client = _client(tmp_path)
    _seed_source_metric_job(client)
    body = client.get("/api/platform/alerts").json()
    assert body["events"] == []
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["name"] == "demo-job"
    assert "运行记录" in body["skipped"][0]["reason"]


def test_alerts_contract_fields(tmp_path):
    client = _client(tmp_path)
    body = client.get("/api/platform/alerts").json()
    for key in ("events", "levels", "jobs", "skipped"):
        assert key in body
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/web/test_alerts_endpoint.py -q
```

Expected: FAIL —— 404（端点不存在）

- [ ] **Step 3: 写聚合实现**

在 `src/anomaly_lab/platform/alert_events.py` 追加：

```python
def collect_alert_events(
    store, data_root: Path
) -> tuple[list[AlertEvent], list[dict]]:
    """汇总所有任务的告警事件。

    返回 `(events, skipped)`：
    - `events` 按开始时间**倒序**（新的在前）
    - `skipped` 列出没被纳入统计的任务与原因
    """
    events: list[AlertEvent] = []
    skipped: list[dict] = []
    for job in store.list_jobs():
        try:
            metric = store.get_metric(job.metric_id)
        except ValueError:
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "指标已不存在"}
            )
            continue
        run = store.latest_run(job.id)
        if run is None:
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "还没有运行记录"}
            )
            continue
        if run.status == "failed":
            skipped.append(
                {
                    "job_id": job.id,
                    "name": job.name,
                    "reason": f"最近一次运行失败：{run.error or '未知原因'}",
                }
            )
            continue
        if run.status == "running":
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "最近一次运行尚未结束"}
            )
            continue
        try:
            index = read_run_index(data_root, run.id)
        except (FileNotFoundError, OSError):
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "运行结果文件缺失"}
            )
            continue
        for entry in index.get("series", []):
            file_name = entry.get("file")
            if file_name is None:
                continue  # 数据不足的序列没有检测结果 —— 不是告警
            path = run_dir(data_root, run.id) / file_name
            if not path.exists():
                skipped.append(
                    {
                        "job_id": job.id,
                        "name": job.name,
                        "reason": f"序列结果文件缺失：{entry.get('series_id')}",
                    }
                )
                continue
            with np.load(path, allow_pickle=False) as payload:
                events.extend(
                    events_from_series(
                        severity=payload["severity"],
                        timestamps=payload["timestamps"].astype("datetime64[ns]"),
                        scores=payload["scores"],
                        levels=json.loads(str(payload["levels"])),
                        job_id=job.id,
                        job_name=job.name,
                        metric_id=metric.id,
                        metric_name=metric.name,
                        series_id=str(payload["series_id"]),
                        group=entry.get("group"),
                        detector=str(payload["detector"]),
                        score_type=str(payload["score_type"]),
                        run_id=run.id,
                    )
                )
    events.sort(key=lambda item: (item.start_ts, item.job_id), reverse=True)
    return events, skipped
```

同时把 import 改成：

```python
from anomaly_lab.platform.alerts import SEVERITY_NORMAL
from anomaly_lab.platform.runner import read_run_index, run_dir
```

> ⚠️ 循环导入风险：`runner.py` 不 import `alert_events.py`，所以安全。

- [ ] **Step 4: 写端点**

在 `src/anomaly_lab/web/platform_routes.py` 的 `build_router` 里（catalog 端点之后）加：

```python
    @router.get("/api/platform/alerts")
    def alerts(
        job_id: int | None = None,
        level: str | None = None,
        series_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        """跨任务汇总告警事件。

        ⚠️ 以每个任务的**最新一次运行**为准 —— 滚动窗口下同一段异常会被
        连续多次运行重复报出，扫全部历史 run 会刷屏。
        """
        store = _store()
        events, skipped = collect_alert_events(store, get_data_root())
        if job_id is not None:
            events = [item for item in events if item.job_id == job_id]
        if level:
            events = [item for item in events if item.level == level]
        if series_id:
            events = [item for item in events if item.series_id == series_id]
        if since:
            events = [item for item in events if item.start_ts >= since]
        if until:
            events = [item for item in events if item.start_ts <= until]
        return {
            "events": [asdict(item) for item in events],
            "levels": sorted({item.level for item in events}),
            "jobs": [
                {"id": job.id, "name": job.name} for job in store.list_jobs()
            ],
            "skipped": skipped,
        }
```

import 补上：

```python
from anomaly_lab.platform.alert_events import collect_alert_events
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/web/test_alerts_endpoint.py -q
```

Expected: 3 passed

- [ ] **Step 6: 跑全量测试确认没打破别的**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest -q 2>&1 | tail -3
```

Expected: 全绿（原有 306 + 新增 13）

- [ ] **Step 7: 提交**

```bash
cd ~/Project/anomaly-lab && git add src/anomaly_lab/platform/alert_events.py src/anomaly_lab/web/platform_routes.py tests/web/test_alerts_endpoint.py && git commit -m "feat(platform): 告警中心端点（跨任务汇总 + 筛选 + skipped 报告）"
```

---

## Task 4: 前端 API 封装与类型

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/platform.ts`

- [ ] **Step 1: 加类型**

在 `frontend/src/api/types.ts` 追加：

```ts
// ─────────────────────────────────────────── 告警中心 /api/platform/alerts

/**
 * 一条告警事件 = 一段连续告警点合并成的区间。
 *
 * ⚠️ `level` 是**档位名**，来自任务的规则表，不一定是 P0/P1（可自定义如「注意」）。
 *    `level_index` 才是严重度序（越大越严重）—— 排序、筛选用它。
 */
export interface AlertEvent {
  job_id: number
  job_name: string
  metric_id: number
  metric_name: string
  series_id: string
  group: string | null
  level: string
  level_index: number
  start_ts: string
  end_ts: string
  n_points: number
  max_score: number
  detector: string
  score_type: string
  run_id: number
}

/** 没被纳入统计的任务 —— 必须说清为什么，不能静默消失。 */
export interface SkippedJob {
  job_id: number
  name: string
  reason: string
}

export interface AlertListResponse {
  events: AlertEvent[]
  levels: string[]
  jobs: { id: number; name: string }[]
  skipped: SkippedJob[]
}
```

- [ ] **Step 2: 加 API 封装**

在 `frontend/src/api/platform.ts` 追加：

```ts
/**
 * 跨任务汇总告警事件。
 *
 * ⚠️ 以每个任务的**最新一次运行**为准 —— 滚动窗口下同一段异常会被
 *    连续多次运行重复报出。
 */
export const getAlerts = (opts: {
  jobId?: number
  level?: string
  seriesId?: string
  since?: string
  until?: string
} = {}) => {
  const params = new URLSearchParams()
  if (opts.jobId !== undefined) params.set('job_id', String(opts.jobId))
  if (opts.level) params.set('level', opts.level)
  if (opts.seriesId) params.set('series_id', opts.seriesId)
  if (opts.since) params.set('since', opts.since)
  if (opts.until) params.set('until', opts.until)
  const qs = params.toString()
  return request<AlertListResponse>(`/api/platform/alerts${qs ? `?${qs}` : ''}`)
}
```

import 补 `AlertListResponse`。

- [ ] **Step 3: 跑类型检查与现有测试**

```bash
cd ~/Project/anomaly-lab/frontend && npx tsc --noEmit && npm test 2>&1 | grep -E "Test Files|Tests "
```

Expected: tsc 无错误；测试仍全绿

- [ ] **Step 4: 提交**

```bash
cd ~/Project/anomaly-lab && git add frontend/src/api/types.ts frontend/src/api/platform.ts && git commit -m "feat(frontend): 告警中心的 API 封装与类型"
```

---

## Task 5: 告警中心页面

**Files:**
- Create: `frontend/src/features/alerts/queries.ts`
- Create: `frontend/src/features/alerts/AlertList.tsx`
- Create: `frontend/src/pages/AlertsPage.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`
- Test: `frontend/src/features/alerts/alerts.test.tsx`

- [ ] **Step 1: 写失败的测试**

`frontend/src/features/alerts/alerts.test.tsx`：

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AlertEvent } from '../../api/types'
import { AlertList } from './AlertList'

const event: AlertEvent = {
  job_id: 1,
  job_name: 'demo-job',
  metric_id: 2,
  metric_name: 'demo-metric',
  series_id: 'demo-metric:web-api',
  group: 'web-api',
  level: 'P0',
  level_index: 2,
  start_ts: '2026-10-30T10:00:00',
  end_ts: '2026-10-30T10:05:00',
  n_points: 3,
  max_score: 4.2,
  detector: 'iqr',
  score_type: 'zscore',
  run_id: 7,
}

describe('AlertList', () => {
  it('渲染事件的等级与时间区间', () => {
    render(
      <AlertList
        isLoading={false}
        error={null}
        data={{ events: [event], levels: ['P0'], jobs: [], skipped: [] }}
        filters={{ jobId: undefined, level: undefined }}
        onFiltersChange={() => {}}
      />,
    )
    expect(screen.getByText('P0')).toBeTruthy()
    expect(screen.getByText(/2026-10-30 10:00/)).toBeTruthy()
  })

  it('任务名渲染成链接指向任务详情', () => {
    render(
      <AlertList
        isLoading={false}
        error={null}
        data={{ events: [event], levels: ['P0'], jobs: [], skipped: [] }}
        filters={{ jobId: undefined, level: undefined }}
        onFiltersChange={() => {}}
      />,
    )
    const link = screen.getByRole('link', { name: 'demo-job' })
    expect(link.getAttribute('href')).toBe('/jobs/1')
  })

  it('有事件但事件为空时显示「当前没有告警」', () => {
    render(
      <AlertList
        isLoading={false}
        error={null}
        data={{ events: [], levels: [], jobs: [{ id: 1, name: 'demo-job' }], skipped: [] }}
        filters={{ jobId: undefined, level: undefined }}
        onFiltersChange={() => {}}
      />,
    )
    expect(screen.getByText('当前没有告警')).toBeTruthy()
  })

  it('一个任务都没有时显示「还没有检测任务」', () => {
    render(
      <AlertList
        isLoading={false}
        error={null}
        data={{ events: [], levels: [], jobs: [], skipped: [] }}
        filters={{ jobId: undefined, level: undefined }}
        onFiltersChange={() => {}}
      />,
    )
    expect(screen.getByText('还没有检测任务')).toBeTruthy()
  })

  it('跳过的任务如实展示原因', () => {
    render(
      <AlertList
        isLoading={false}
        error={null}
        data={{
          events: [],
          levels: [],
          jobs: [{ id: 1, name: 'demo-job' }],
          skipped: [{ job_id: 1, name: 'demo-job', reason: '还没有运行记录' }],
        }}
        filters={{ jobId: undefined, level: undefined }}
        onFiltersChange={() => {}}
      />,
    )
    expect(screen.getByText(/还没有运行记录/)).toBeTruthy()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Project/anomaly-lab/frontend && npx vitest run src/features/alerts/alerts.test.tsx
```

Expected: FAIL —— `Cannot find module './AlertList'`

- [ ] **Step 3: 写 queries.ts**

`frontend/src/features/alerts/queries.ts`：

```ts
import { useQuery } from '@tanstack/react-query'
import { getAlerts } from '../../api/platform'

export interface AlertFilters {
  jobId?: number
  level?: string
  since?: string
  until?: string
}

export const alertsKey = ['alerts'] as const

export function useAlerts(filters: AlertFilters) {
  return useQuery({
    queryKey: [...alertsKey, filters],
    queryFn: () => getAlerts(filters),
  })
}
```

- [ ] **Step 4: 写 AlertList.tsx**

`frontend/src/features/alerts/AlertList.tsx`：

```tsx
import { Alert, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import { StateBoundary } from '../../components/StateBoundary'
import type { AlertEvent, AlertListResponse } from '../../api/types'
import type { AlertFilters } from './queries'

export interface AlertListProps {
  isLoading: boolean
  error: unknown
  data: AlertListResponse | undefined
  filters: AlertFilters
  onFiltersChange: (next: AlertFilters) => void
}

/** 档位越严重颜色越重。索引 0 是「正常」，这里只处理 ≥1 的档位。 */
function levelColor(levelIndex: number): string {
  if (levelIndex >= 3) return 'red'
  if (levelIndex === 2) return 'orange'
  return 'gold'
}

function fmtTime(value: string): string {
  return value.replace('T', ' ').slice(0, 16)
}

export function AlertList({ isLoading, error, data, filters, onFiltersChange }: AlertListProps) {
  const columns: ColumnsType<AlertEvent> = [
    {
      title: '等级',
      dataIndex: 'level',
      key: 'level',
      width: 90,
      render: (value: string, row) => (
        <Tag color={levelColor(row.level_index)}>{value}</Tag>
      ),
    },
    {
      title: '时间',
      key: 'time',
      width: 260,
      render: (_v, row) => (
        <span className="mono">
          {fmtTime(row.start_ts)} ~ {fmtTime(row.end_ts)}
        </span>
      ),
    },
    {
      title: '点数',
      dataIndex: 'n_points',
      key: 'n_points',
      width: 80,
      align: 'right',
      render: (value: number) => <span className="mono">{value}</span>,
    },
    {
      title: '峰值分数',
      dataIndex: 'max_score',
      key: 'max_score',
      width: 110,
      align: 'right',
      render: (value: number) => <span className="mono">{value.toFixed(2)}</span>,
    },
    {
      title: '任务',
      dataIndex: 'job_name',
      key: 'job_name',
      width: 180,
      render: (value: string, row) => <Link to={`/jobs/${row.job_id}`}>{value}</Link>,
    },
    {
      title: '序列',
      dataIndex: 'series_id',
      key: 'series_id',
      render: (value: string) => <span className="mono">{value}</span>,
    },
    {
      title: '算法',
      dataIndex: 'detector',
      key: 'detector',
      width: 130,
      render: (value: string) => <span className="mono">{value}</span>,
    },
  ]

  return (
    <StateBoundary
      isLoading={isLoading}
      error={error}
      data={data}
      isEmpty={(d) => d.events.length === 0 && d.jobs.length === 0}
      emptyTitle="还没有检测任务"
      emptyHint="先建一个数据源与指标，再创建任务"
    >
      {(d) => (
        <>
          <div className="alert-list__toolbar">
            <Space>
              <Select
                allowClear
                placeholder="全部任务"
                style={{ width: 200 }}
                value={filters.jobId}
                onChange={(value) => onFiltersChange({ ...filters, jobId: value })}
                options={d.jobs.map((job) => ({ value: job.id, label: job.name }))}
              />
              <Select
                allowClear
                placeholder="全部等级"
                style={{ width: 140 }}
                value={filters.level}
                onChange={(value) => onFiltersChange({ ...filters, level: value })}
                options={d.levels.map((level) => ({ value: level, label: level }))}
              />
            </Space>
            {d.events.length === 0 ? (
              <Alert
                type="success"
                showIcon
                message="当前没有告警"
                description="所有任务在最近一次运行里都没有触发告警条件"
              />
            ) : null}
            {d.skipped.length > 0 ? (
              <Alert
                type="warning"
                showIcon
                message={`${d.skipped.length} 个任务未纳入统计`}
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {d.skipped.map((item) => (
                      <li key={item.job_id}>
                        {item.name}：{item.reason}
                      </li>
                    ))}
                  </ul>
                }
              />
            ) : null}
          </div>
          <Table<AlertEvent>
            rowKey={(row) => `${row.job_id}-${row.series_id}-${row.start_ts}`}
            columns={columns}
            dataSource={d.events}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: true }}
            scroll={{ x: 'max-content' }}
          />
        </>
      )}
    </StateBoundary>
  )
}
```

> ⚠️ `StateBoundary` 的 `isEmpty` 判定：「一个任务都没有」是真空；
>    「有任务但没告警」不是空 —— 要显示「当前没有告警」。

- [ ] **Step 5: 写 AlertsPage.tsx**

`frontend/src/pages/AlertsPage.tsx`：

```tsx
import { useState } from 'react'
import { AlertList } from '../features/alerts/AlertList'
import { useAlerts, type AlertFilters } from '../features/alerts/queries'

/** 告警中心：跨任务汇总的告警事件列表。 */
export function AlertsPage() {
  const [filters, setFilters] = useState<AlertFilters>({})
  const alerts = useAlerts(filters)

  return (
    <div className="page">
      <header className="page__header">
        <h1 className="page__title">告警中心</h1>
        <p className="page__subtitle">
          {alerts.data
            ? `${alerts.data.events.length} 条告警事件（取各任务最近一次运行）`
            : '加载中…'}
        </p>
      </header>
      <AlertList
        isLoading={alerts.isPending}
        error={alerts.error}
        data={alerts.data}
        filters={filters}
        onFiltersChange={setFilters}
      />
    </div>
  )
}
```

- [ ] **Step 6: 接路由与导航**

`frontend/src/router.tsx` —— 在 lazy import 区加：

```tsx
const AlertsPage = lazy(() =>
  import('./pages/AlertsPage').then((m) => ({ default: m.AlertsPage })),
)
```

在 `<Routes>` 里加（放在 `/jobs` 之后）：

```tsx
<Route path="/alerts" element={<AlertsPage />} />
```

`frontend/src/components/AppLayout.tsx` —— `NAV_ITEMS` 加：

```tsx
{ key: '/alerts', label: '告警中心' },
```

> ⚠️ 顺序很重要：`AppLayout` 用 `location.pathname.startsWith(item.key)` 选高亮，
>    `/alerts` 与其它路径不冲突，但**必须**放在 `/jobs` 之前还是之后？
>    不冲突 —— `/alerts` 不以 `/jobs` 开头。但 `startsWith` 是**前缀**匹配，
>    若将来有 `/alerts-xxx` 会误命中，先不管。

- [ ] **Step 7: 运行测试确认通过**

```bash
cd ~/Project/anomaly-lab/frontend && npx vitest run src/features/alerts/alerts.test.tsx
```

Expected: 5 passed

> ⚠️ antd 测试坑：中文两字按钮会自动插空格 → 用正则 `/创\s*建/`；
>    `Select` 不是原生 select → 用 `click` + `findByTitle`。

- [ ] **Step 8: 全量验证**

```bash
cd ~/Project/anomaly-lab/frontend && npx tsc --noEmit && npm test 2>&1 | grep -E "Test Files|Tests " && npm run build 2>&1 | tail -2
```

Expected: tsc 无错误；测试全绿；build 通过

- [ ] **Step 9: 提交**

```bash
cd ~/Project/anomaly-lab && git add frontend/src/features/alerts frontend/src/pages/AlertsPage.tsx frontend/src/router.tsx frontend/src/components/AppLayout.tsx && git commit -m "feat(frontend): 告警中心页面（跨任务事件列表 + 筛选 + skipped 展示）"
```

---

## Task 6: 告警中心的契约守卫

**Files:**
- Modify: `tests/web/test_api_contract.py`

- [ ] **Step 1: 加守卫**

追加到 `tests/web/test_api_contract.py`：

```python
def test_alerts_contract():
    """告警中心的事件字段 —— 前端 types.ts 是手写的，这里防漂移。"""
    client = TestClient(create_app())
    body = client.get("/api/platform/alerts").json()
    for key in ("events", "levels", "jobs", "skipped"):
        assert key in body
    if body["events"]:
        for key in (
            "job_id",
            "job_name",
            "metric_id",
            "metric_name",
            "series_id",
            "group",
            "level",
            "level_index",
            "start_ts",
            "end_ts",
            "n_points",
            "max_score",
            "detector",
            "score_type",
            "run_id",
        ):
            assert key in body["events"][0]
```

- [ ] **Step 2: 运行测试**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/web/test_api_contract.py -q
```

Expected: 全绿

- [ ] **Step 3: 提交**

```bash
cd ~/Project/anomaly-lab && git add tests/web/test_api_contract.py && git commit -m "test(web): 告警中心的字段契约守卫"
```

---

# Chunk 2: 删除功能

## Task 7: store 的删除方法

**Files:**
- Modify: `src/anomaly_lab/platform/store.py`
- Test: `tests/web/test_delete_endpoints.py`

- [ ] **Step 1: 写失败的测试**

`tests/web/test_delete_endpoints.py`（先只测 store 层能删干净）：

```python
"""删除：级联清理与 run 目录文件清理。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app


def _client(tmp_path):
    return TestClient(create_app(platform_data_root=tmp_path))


def _seed(client):
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "demo",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
        },
    ).json()
    job = client.post(
        "/api/platform/jobs",
        json={"metric_id": metric["id"], "name": "demo-job", "detector": "iqr"},
    ).json()
    return source["id"], metric["id"], job["id"]


def test_delete_source_cascades_to_metrics_and_jobs(tmp_path):
    client = _client(tmp_path)
    source_id, metric_id, job_id = _seed(client)
    response = client.delete(f"/api/platform/sources/{source_id}")
    assert response.status_code == 200
    catalog = client.get("/api/platform/catalog").json()
    assert catalog["sources"] == []
    assert catalog["metrics"] == []
    assert catalog["jobs"] == []


def test_delete_metric_cascades_to_jobs(tmp_path):
    client = _client(tmp_path)
    _, metric_id, job_id = _seed(client)
    response = client.delete(f"/api/platform/metrics/{metric_id}")
    assert response.status_code == 200
    catalog = client.get("/api/platform/catalog").json()
    assert catalog["metrics"] == []
    assert catalog["jobs"] == []


def test_delete_job_removes_only_that_job(tmp_path):
    client = _client(tmp_path)
    _, _, job_id = _seed(client)
    response = client.delete(f"/api/platform/jobs/{job_id}")
    assert response.status_code == 200
    catalog = client.get("/api/platform/catalog").json()
    assert catalog["jobs"] == []
    assert len(catalog["metrics"]) == 1


def test_delete_missing_object_returns_404(tmp_path):
    client = _client(tmp_path)
    for path in ("/api/platform/sources/999", "/api/platform/metrics/999", "/api/platform/jobs/999"):
        response = client.delete(path)
        assert response.status_code == 404, path


def test_delete_response_reports_cascade_counts(tmp_path):
    client = _client(tmp_path)
    source_id, _, job_id = _seed(client)
    body = client.delete(f"/api/platform/sources/{source_id}").json()
    assert body["deleted"]["sources"] == 1
    assert body["deleted"]["metrics"] == 1
    assert body["deleted"]["jobs"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/web/test_delete_endpoints.py -q
```

Expected: FAIL —— 405（DELETE 方法不允许）

- [ ] **Step 3: 写 store 方法**

在 `src/anomaly_lab/platform/store.py` 追加：

```python
    # ---------- 删除 ----------

    def delete_job(self, job_id: int) -> dict:
        """删一个任务（连带 runs / feedback），返回删除统计。

        ⚠️ 返回值里的 `run_ids` 是**内部用**的（路由层要据此删 run 目录文件），
        路由层在构造响应前要把它 pop 掉。
        """
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError(f"任务不存在: {job_id}")
            run_ids = [
                item["id"]
                for item in conn.execute(
                    "SELECT id FROM runs WHERE job_id=?", (job_id,)
                )
            ]
            feedback = conn.execute(
                "SELECT COUNT(*) AS c FROM feedback WHERE job_id=?", (job_id,)
            ).fetchone()["c"]
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        return {
            "jobs": 1,
            "runs": len(run_ids),
            "feedback": feedback,
            "run_ids": run_ids,
        }

    def delete_metric(self, metric_id: int) -> dict:
        """删一个指标（连带它下面的任务、运行、反馈）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM metrics WHERE id=?", (metric_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"指标不存在: {metric_id}")
            job_ids = [
                item["id"]
                for item in conn.execute(
                    "SELECT id FROM jobs WHERE metric_id=?", (metric_id,)
                )
            ]
            stats = self._cascade_stats(conn, job_ids)
            conn.execute("DELETE FROM metrics WHERE id=?", (metric_id,))
        stats["metrics"] = 1
        return stats

    def delete_source(self, source_id: int) -> dict:
        """删一个数据源（连带它下面的指标、任务、运行、反馈）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM sources WHERE id=?", (source_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"数据源不存在: {source_id}")
            metric_ids = [
                item["id"]
                for item in conn.execute(
                    "SELECT id FROM metrics WHERE source_id=?", (source_id,)
                )
            ]
            job_ids: list[int] = []
            if metric_ids:
                placeholders = ",".join("?" * len(metric_ids))
                job_ids = [
                    item["id"]
                    for item in conn.execute(
                        f"SELECT id FROM jobs WHERE metric_id IN ({placeholders})",
                        metric_ids,
                    )
                ]
            stats = self._cascade_stats(conn, job_ids)
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        stats["metrics"] = len(metric_ids)
        stats["sources"] = 1
        return stats

    @staticmethod
    def _cascade_stats(conn: sqlite3.Connection, job_ids: list[int]) -> dict:
        """统计要连带删掉多少任务 / 运行 / 反馈，并收集 run_id。"""
        if not job_ids:
            return {"jobs": 0, "runs": 0, "feedback": 0, "run_ids": []}
        placeholders = ",".join("?" * len(job_ids))
        run_ids = [
            item["id"]
            for item in conn.execute(
                f"SELECT id FROM runs WHERE job_id IN ({placeholders})", job_ids
            )
        ]
        feedback = conn.execute(
            f"SELECT COUNT(*) AS c FROM feedback WHERE job_id IN ({placeholders})",
            job_ids,
        ).fetchone()["c"]
        return {
            "jobs": len(job_ids),
            "runs": len(run_ids),
            "feedback": feedback,
            "run_ids": run_ids,
        }
```

> ⚠️ `run_ids` 会随级联删掉 —— 但 `runs` 表有 `ON DELETE CASCADE`，
>    所以统计必须在删除**之前**查。

- [ ] **Step 4: 写端点**

在 `src/anomaly_lab/web/platform_routes.py` 里加（放在 feedback 端点之前）：

```python
    def _delete_run_dirs(data_root: Path, run_ids: list[int]) -> None:
        """删掉 run 目录 —— 数据库外键管不到文件系统。"""
        for run_id in run_ids:
            directory = runner_module.run_dir(data_root, run_id)
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

    @router.delete("/api/platform/jobs/{job_id}")
    def delete_job(job_id: int) -> dict:
        store = _store()
        if runner_module.is_running(job_id):
            raise HTTPException(
                status_code=409, detail="任务正在运行中，请等本次运行结束后再删除"
            )
        try:
            stats = store.delete_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        run_ids = stats.pop("run_ids", [])
        _delete_run_dirs(get_data_root(), run_ids)
        return {"deleted": stats}

    @router.delete("/api/platform/metrics/{metric_id}")
    def delete_metric(metric_id: int) -> dict:
        store = _store()
        try:
            stats = store.delete_metric(metric_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        run_ids = stats.pop("run_ids", [])
        _delete_run_dirs(get_data_root(), run_ids)
        return {"deleted": stats}

    @router.delete("/api/platform/sources/{source_id}")
    def delete_source(source_id: int) -> dict:
        store = _store()
        try:
            stats = store.delete_source(source_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        run_ids = stats.pop("run_ids", [])
        _delete_run_dirs(get_data_root(), run_ids)
        return {"deleted": stats}
```

import 补 `import shutil`。

- [ ] **Step 5: 加 `is_running`**

在 `src/anomaly_lab/platform/runner.py` 加：

```python
def is_running(job_id: int) -> bool:
    """任务是不是正在跑（手动触发或调度到点都算）。"""
    with _INFLIGHT_LOCK:
        return job_id in _INFLIGHT
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/web/test_delete_endpoints.py -q
```

Expected: 5 passed

- [ ] **Step 7: 提交**

```bash
cd ~/Project/anomaly-lab && git add src/anomaly_lab/platform/store.py src/anomaly_lab/platform/runner.py src/anomaly_lab/web/platform_routes.py tests/web/test_delete_endpoints.py && git commit -m "feat(platform): 任务/指标/数据源的级联删除端点"
```

---

## Task 8: 删除时清理 run 目录文件 + 运行中返回 409

**Files:**
- Modify: `tests/web/test_delete_endpoints.py`
- Modify: `src/anomaly_lab/platform/store.py`（可能需要微调）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/web/test_delete_endpoints.py`：

```python
def test_deleting_job_removes_run_directory_files(tmp_path):
    """⚠️ 数据库外键管不到文件系统 —— run 目录必须跟着删，否则留垃圾。"""
    client = _client(tmp_path)
    _, _, job_id = _seed(client)
    # 造一个假的 run 目录
    run_root = tmp_path / "cache" / "platform" / "runs" / "42"
    run_root.mkdir(parents=True)
    (run_root / "index.json").write_text("{}", encoding="utf-8")
    (run_root / "abc.npz").write_bytes(b"x")

    # 让 store 知道这个 run 属于该任务
    store = PlatformStore(tmp_path / "platform.db")
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO runs (id, job_id, status, started_at, n_series, n_alerts)"
            " VALUES (42, ?, 'success', '2026-10-30T00:00:00+00:00', 1, 0)",
            (job_id,),
        )

    client.delete(f"/api/platform/jobs/{job_id}")
    assert not run_root.exists()


def test_deleting_running_job_returns_409(tmp_path):
    """运行中的任务不能删 —— 否则 run 还在写、文件已被删掉。"""
    from anomaly_lab.platform import runner as runner_module

    client = _client(tmp_path)
    _, _, job_id = _seed(client)
    runner_module._INFLIGHT[job_id] = 99
    try:
        response = client.delete(f"/api/platform/jobs/{job_id}")
    finally:
        runner_module._INFLIGHT.pop(job_id, None)
    assert response.status_code == 409
    assert "运行" in response.json()["detail"]
```

- [ ] **Step 2: 运行测试**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest tests/web/test_delete_endpoints.py -q
```

Expected: 第一个测试可能已通过（`_delete_run_dirs` 已实现）；第二个应通过（`is_running` 已实现）

- [ ] **Step 3: 若有失败，逐个修**

- 第一个失败 → 检查 `_delete_run_dirs` 是否用了 `runner_module.run_dir`
- 第二个失败 → 检查 `is_running` 是否在路由里被调用

- [ ] **Step 4: 运行全量测试**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest -q 2>&1 | tail -3 && .venv/bin/python -m ruff check src tests
```

Expected: 全绿

- [ ] **Step 5: 提交**

```bash
cd ~/Project/anomaly-lab && git add tests/web/test_delete_endpoints.py src/anomaly_lab/platform && git commit -m "test(platform): 删除时清理 run 目录文件；运行中的任务返回 409"
```

---

## Task 9: 前端删除按钮与影响预览

**Files:**
- Create: `frontend/src/features/delete/impact.ts`
- Create: `frontend/src/features/delete/queries.ts`
- Create: `frontend/src/features/delete/DeleteButton.tsx`
- Test: `frontend/src/features/delete/DeleteButton.test.tsx`

- [ ] **Step 1: 写失败��测试**

`frontend/src/features/delete/DeleteButton.test.tsx`：

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { impactText } from './impact'
import type { Catalog } from '../../api/types'

const catalog: Catalog = {
  sources: [
    { id: 1, name: 'local', kind: 'sqlite', path: 'p.db', created_at: '2026-10-30T00:00:00+00:00' },
  ],
  metrics: [
    {
      id: 10,
      source_id: 1,
      name: 'm1',
      query: 'q',
      time_column: 'ts',
      value_column: 'value',
      group_column: null,
      time_format: 'iso_utc',
      freq: '5min',
      source_timezone: 'UTC',
      missing_policy: 'drop',
      created_at: '2026-10-30T00:00:00+00:00',
    },
  ],
  jobs: [
    {
      id: 100,
      metric_id: 10,
      name: 'j1',
      detector: 'iqr',
      alert_threshold: 2.5,
      critical_threshold: 3.75,
      window_points: 300,
      interval_seconds: 300,
      enabled: true,
      last_run_at: null,
      next_run_at: null,
      created_at: '2026-10-30T00:00:00+00:00',
      alert_rules: [],
    },
  ],
  detectors: [],
}

describe('impactText', () => {
  it('数据源要说明会连带删多少指标与任务', () => {
    expect(impactText('source', 1, catalog)).toBe('将连带删除 1 个指标、1 个任务')
  })

  it('指标要说明会连带删多少任务', () => {
    expect(impactText('metric', 10, catalog)).toBe('将连带删除 1 个任务')
  })

  it('任务没有依赖时只说删任务本身', () => {
    expect(impactText('job', 100, catalog)).toBe('将删除该任务')
  })

  it('没有依赖时不提数字', () => {
    const empty: Catalog = { ...catalog, metrics: [], jobs: [] }
    expect(impactText('source', 1, empty)).toBe('将删除该数据源')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Project/anomaly-lab/frontend && npx vitest run src/features/delete/DeleteButton.test.tsx
```

Expected: FAIL —— `Cannot find module './impact'`

- [ ] **Step 3: 写 impact.ts**

`frontend/src/features/delete/impact.ts`：

```ts
import type { Catalog } from '../../api/types'

export type DeleteTarget = 'source' | 'metric' | 'job'

/**
 * 删除影响的文案。
 *
 * ⚠️ 影响范围**从 catalog 自己算** —— catalog 已经带了全量
 *    sources/metrics/jobs，不值得为了一句提示再开一个端点。
 */
export function impactText(target: DeleteTarget, id: number, catalog: Catalog): string {
  if (target === 'job') {
    return '将删除该任务'
  }
  const metrics =
    target === 'source'
      ? catalog.metrics.filter((m) => m.source_id === id)
      : catalog.metrics.filter((m) => m.id === id)
  const metricIds = new Set(metrics.map((m) => m.id))
  const jobs = catalog.jobs.filter((j) => metricIds.has(j.metric_id))

  const parts: string[] = []
  if (target === 'source' && metrics.length > 0) {
    parts.push(`${metrics.length} 个指标`)
  }
  if (jobs.length > 0) {
    parts.push(`${jobs.length} 个任务`)
  }
  if (parts.length === 0) {
    return target === 'source' ? '将删除该数据源' : '将删除该指标'
  }
  return `将连带删除 ${parts.join('、')}`
}
```

- [ ] **Step 4: 写 API 封装**

在 `frontend/src/api/platform.ts` 追加：

```ts
/** 删除的统计（级联删掉了多少东西）。 */
export interface DeleteStats {
  sources?: number
  metrics: number
  jobs: number
  runs: number
  feedback: number
}

export const deleteJob = (jobId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/jobs/${jobId}`, { method: 'DELETE' })

export const deleteMetric = (metricId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/metrics/${metricId}`, { method: 'DELETE' })

export const deleteSource = (sourceId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/sources/${sourceId}`, { method: 'DELETE' })
```

- [ ] **Step 5: 写 queries.ts**

`frontend/src/features/delete/queries.ts`：

```ts
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { deleteJob, deleteMetric, deleteSource } from '../../api/platform'
import { catalogKey } from '../jobs/queries'

function useDeleteMutation<TVars>(
  fn: (vars: TVars) => Promise<unknown>,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      // 列表数据全在 catalog 里 —— 失效它就够了
      void qc.invalidateQueries({ queryKey: catalogKey })
    },
  })
}

export const useDeleteJob = () =>
  useDeleteMutation((jobId: number) => deleteJob(jobId))

export const useDeleteMetric = () =>
  useDeleteMutation((metricId: number) => deleteMetric(metricId))

export const useDeleteSource = () =>
  useDeleteMutation((sourceId: number) => deleteSource(sourceId))
```

- [ ] **Step 6: 写 DeleteButton.tsx**

`frontend/src/features/delete/DeleteButton.tsx`：

```tsx
import { Button, Popconfirm } from 'antd'
import type { Catalog } from '../../api/types'
import { impactText, type DeleteTarget } from './impact'

export interface DeleteButtonProps {
  target: DeleteTarget
  id: number
  name: string
  catalog: Catalog | undefined
  onConfirm: () => void
  loading?: boolean
}

/**
 * 删除按钮。
 *
 * ⚠️ 确认文案必须**具体**（「将连带删除 2 个指标、3 个任务」）——
 *    笼统的「确定吗」会让用户误判影响范围。
 */
export function DeleteButton({
  target,
  id,
  name,
  catalog,
  onConfirm,
  loading,
}: DeleteButtonProps) {
  const impact = catalog ? impactText(target, id, catalog) : '将删除该对象'
  const noun = target === 'source' ? '数据源' : target === 'metric' ? '指标' : '任务'
  return (
    <Popconfirm
      title={`确定删除${noun}「${name}」？`}
      description={impact}
      okText="删除"
      cancelText="取消"
      okButtonProps={{ danger: true }}
      onConfirm={onConfirm}
    >
      <Button size="small" danger loading={loading}>
        删除
      </Button>
    </Popconfirm>
  )
}
```

- [ ] **Step 7: 运行测试确认通过**

```bash
cd ~/Project/anomaly-lab/frontend && npx vitest run src/features/delete/DeleteButton.test.tsx
```

Expected: 4 passed

- [ ] **Step 8: 提交**

```bash
cd ~/Project/anomaly-lab && git add frontend/src/features/delete frontend/src/api/platform.ts && git commit -m "feat(frontend): 删除按钮 + 影响范围文案"
```

---

## Task 10: 三个列表页接上删除

**Files:**
- Modify: `frontend/src/features/sources/SourceList.tsx`
- Modify: `frontend/src/features/metrics/MetricList.tsx`
- Modify: `frontend/src/features/jobs/JobList.tsx`
- Modify: `frontend/src/pages/SourcesPage.tsx`
- Modify: `frontend/src/pages/MetricsPage.tsx`
- Modify: `frontend/src/pages/JobsPage.tsx`

- [ ] **Step 1: SourceList 加删除列**

在 `frontend/src/features/sources/SourceList.tsx`：

- import 补 `import { DeleteButton } from '../delete/DeleteButton'`
- props 加：

```tsx
  catalog: Catalog | undefined
  onDelete: (sourceId: number) => void
  deletingId: number | null
```

- columns 末尾加：

```tsx
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_value, row) => (
        <DeleteButton
          target="source"
          id={row.id}
          name={row.name}
          catalog={catalog}
          loading={deletingId === row.id}
          onConfirm={() => onDelete(row.id)}
        />
      ),
    },
```

- `<Table>` 之前把 `sources` 传进 StateBoundary 的 children 里已经有 `data`，
  直接在 Table 上方不需要额外结构。

- [ ] **Step 2: SourcesPage 接上 mutation**

`frontend/src/pages/SourcesPage.tsx`：

```tsx
import { useDeleteSource } from '../features/delete/queries'
```

```tsx
  const deleteSource = useDeleteSource()
  const handleDelete = (sourceId: number) => {
    deleteSource.mutate(sourceId, {
      onSuccess: () => message.success('数据源已删除'),
      onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
    })
  }
```

传给 `<SourceList>`：

```tsx
    catalog={catalog.data}
    onDelete={handleDelete}
    deletingId={deleteSource.isPending ? deleteSource.variables ?? null : null}
```

> ⚠️ `useMutation` 的 `variables` 在 idle 时是 `undefined` —— 用 `?? null`。

- [ ] **Step 3: MetricList 同样加删除列**

`frontend/src/features/metrics/MetricList.tsx`：

- import 补 `import { DeleteButton } from '../delete/DeleteButton'`
- props 加 `catalog: Catalog | undefined`、`onDelete: (metricId: number) => void`、`deletingId: number | null`
- columns 末尾加同构的「操作」列（`target="metric"`）

`frontend/src/pages/MetricsPage.tsx` 同样接 `useDeleteMetric`。

- [ ] **Step 4: JobList 加删除按钮**

`frontend/src/features/jobs/JobList.tsx`：

- import 补 `import { DeleteButton } from '../delete/DeleteButton'`
- props 加 `onDelete: (jobId: number) => void`、`deletingId: number | null`
- 已有「操作」列的 `<Space>` 里追加：

```tsx
          <DeleteButton
            target="job"
            id={row.id}
            name={row.name}
            catalog={catalog}
            loading={deletingId === row.id}
            onConfirm={() => onDelete(row.id)}
          />
```

`frontend/src/pages/JobsPage.tsx` 接 `useDeleteJob`：

```tsx
  const deleteJob = useDeleteJob()
  const handleDelete = (jobId: number) => {
    deleteJob.mutate(jobId, {
      onSuccess: () => message.success('任务已删除'),
      onError: (err) => message.error(err instanceof Error ? err.message : '删除失败'),
    })
  }
```

- [ ] **Step 5: 全量验证**

```bash
cd ~/Project/anomaly-lab/frontend && npx tsc --noEmit && npm test 2>&1 | grep -E "Test Files|Tests " && npm run build 2>&1 | tail -2
```

Expected: tsc 无错误；测试全绿；build 通过

- [ ] **Step 6: 提交**

```bash
cd ~/Project/anomaly-lab && git add frontend/src && git commit -m "feat(frontend): 三个列表页接上删除入口"
```

---

## Task 11: 端到端实测

**Files:** 无（验证任务）

- [ ] **Step 1: 起一个临时实例**

```bash
cd ~/Project/anomaly-lab && \
ANOMALY_LAB_DATA_DIR=/tmp/opencode/deltest/work \
  .venv/bin/python -m anomaly_lab.cli serve --port 8018 --no-scheduler &
sleep 8
```

> ⚠️ 用临时目录，别碰真实的 `data/platform.db`。

- [ ] **Step 2: 造数据并验证告警中心**

```bash
cd /tmp/opencode/deltest/work && \
~/Project/anomaly-lab/.venv/bin/python -m anomaly_lab.cli demo --force 2>/dev/null || \
~/Project/anomaly-lab/.venv/bin/python -c "
from pathlib import Path
from anomaly_lab.platform.demo import seed_demo
print(seed_demo(Path('/tmp/opencode/deltest/work')))
"
```

然后跑任务：

```bash
curl -s -X POST http://127.0.0.1:8018/api/platform/jobs/1/run | head -c 200; echo
curl -s http://127.0.0.1:8018/api/platform/alerts | python3 -m json.tool | head -40
```

Expected: `events` 非空（或至少 `skipped` 给出原因）

- [ ] **Step 3: 验证删除**

```bash
curl -s -X DELETE http://127.0.0.1:8018/api/platform/jobs/1; echo
curl -s http://127.0.0.1:8018/api/platform/catalog | python3 -c "
import json,sys; d=json.load(sys.stdin); print('jobs:', len(d['jobs']), 'metrics:', len(d['metrics']))"
```

Expected: `{"deleted": {...}}`；`jobs: 0`

- [ ] **Step 4: 验证 run 目录被清理**

```bash
ls -la /tmp/opencode/deltest/work/cache/platform/runs/ 2>/dev/null
```

Expected: 空（或目录不存在）

- [ ] **Step 5: 停掉临时实例**

```bash
pkill -f "cli serve --port 8018"
```

- [ ] **Step 6: 跑一次完整验证**

```bash
cd ~/Project/anomaly-lab && .venv/bin/python -m pytest -q 2>&1 | tail -3 && \
.venv/bin/python -m ruff check src tests && \
cd frontend && npx tsc --noEmit && npm test 2>&1 | grep -E "Test Files|Tests " && npm run build 2>&1 | tail -2
```

Expected: 全绿

---

## Task 12: 文档同步

**Files:**
- Modify: `docs/PLATFORM.md`
- Modify: `docs/ROADMAP.md`
- Modify: `README.md`

- [ ] **Step 1: PLATFORM.md 加「告警中心」节 + 删除端点**

在 `docs/PLATFORM.md` 的合适位置加：

```markdown
## 告警中心

`GET /api/platform/alerts` 跨任务汇总告警事件。

- **一条事件 = 一段连续告警点**（severity > 0 的连续点合并成区间，
  中间隔着正常点就断开）。区间里的档位取**最高**的那一档。
- **以每个任务的最新一次运行为准** —— 平台任务是滚动窗口，同一段异常会被
  连续多次运行重复报出；扫全部历史 run 会让同一个异常出现很多遍。
  语义是「当前各任务处于什么告警状态」。
- 筛选参数：`job_id` / `level`（档位名）/ `series_id` / `since` / `until`。
- **没被纳入统计的任务会出现在 `skipped` 里并说明原因**
  （还没跑过 / 运行失败 / 运行中 / 结果文件缺失），不会静默消失。

事件里的 `level` 是**档位名**，来自任务的规则表 —— 可能是 P0/P1，
也可能是自定义的「注意」。`level_index` 才是严重度序（越大越严重）。

## 删除

`DELETE /api/platform/jobs/{id}` / `metrics/{id}` / `sources/{id}`

- **级联删除**：删数据源会连带删掉它下面的指标、任务、运行记录与人工反馈。
  （数据库层靠 `ON DELETE CASCADE` + `PRAGMA foreign_keys=ON`。）
- **run 目录文件会一并清理** —— 数据库外键管不到文件系统，
  不清的话 `cache/platform/runs/{run_id}/` 会变成孤儿垃圾。
- **运行中的任务删不掉**：返回 409「任务正在运行中，请等本次运行结束后再删除」。
- 响应体 `{"deleted": {"jobs": 1, "metrics": 2, "runs": 5, "feedback": 3}}`
  给出连带删除的统计。
```

- [ ] **Step 2: ROADMAP.md 勾掉这两项**

把「以后做」里的两项改成已完成，并新增小节：

```markdown
## 告警中心与删除功能（2026-10-30）

- **告警中心**：跨任务汇总告警事件（只读）。一条事件 = 一段连续告警点；
  以每个任务的**最新一次运行**为准（滚动窗口下同一段异常会被重复报出）；
  没被纳入统计的任务在 `skipped` 里给出原因，不静默消失。
- **删除功能**：任务 / 指标 / 数据源的级联删除。数据库层靠 `ON DELETE CASCADE`，
  另外补上数据库管不到的一环 —— **run 目录文件清理**；运行中的任务返回 409。
- 前端新增 `/alerts` 页面；三个列表页加删除入口，确认弹窗写明连带删除的数量。
```

- [ ] **Step 3: README.md 更新平台切片**

在平台相关段落加：

```markdown
- **告警中心**：跨任务汇总告警事件（连续告警点合并成区间），可按任务/档位/时间筛选。
- **删除**：任务 / 指标 / 数据源支持级联删除，run 目录文件一并清理。
```

- [ ] **Step 4: 提交**

```bash
cd ~/Project/anomaly-lab && \
git reset -q HEAD docs/my-thought.md 2>/dev/null; \
git add docs/PLATFORM.md docs/ROADMAP.md README.md && \
git commit -m "docs: 告警中心与删除功能的说明"
```

> ⚠️ `git add -A docs` 会误加 `docs/my-thought.md`（用户文件）——
>    提交前务必 `git reset HEAD docs/my-thought.md`。

---

## 完成检查清单

- [ ] `GET /api/platform/alerts` 跨任务返回事件，字段完整，契约守卫绿
- [ ] 事件按连续区间聚合，档位为区间内最高档
- [ ] 跳过的任务在 `skipped` 里给出原因
- [ ] 前端 `/alerts` 页面能按任务/档位筛选，空态区分「没有任务」与「没有告警」
- [ ] 删除任务/指标/数据源后 DB 无孤儿记录，run 目录文件被清理
- [ ] 运行中的任务删除返回 409
- [ ] pytest / vitest / ruff 全绿，`npm run build` 通过
- [ ] `docs/PLATFORM.md` / `docs/ROADMAP.md` / `README.md` 已同步
- [ ] `docs/my-thought.md` 未被提交
