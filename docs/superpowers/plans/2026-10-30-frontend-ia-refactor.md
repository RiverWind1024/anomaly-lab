# 前端信息架构重构 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端从「平铺的只读表格」改成「可操作、可下钻、按职责分层的监控平台」：序列与告警可点开看图、数据源/指标可编辑、任务详情按职责拆成独立路由、评估报告支持时间筛选与维度聚合。

**Architecture:** 后端只补**真正缺的能力**（编辑端点、评估维度字段、评估排除记录），前端负责信息架构 —— 抽屉下钻、路由拆分、筛选与聚合。两侧契约由既有的双向端点覆盖守卫（`frontend/src/api/endpoints.test.ts` + `tests/web/test_api_contract.py::test_frontend_covers_all_backend_endpoints`）保证。

**Tech Stack:** FastAPI + SQLite（平台侧）/ JSON 报告文件（回测侧）、React 19 + antd 5 + TanStack Query + ECharts、pytest / vitest。

---

## 背景：用户的 6 条意见 → 技术缺口

| # | 意见 | 现状 | 本计划做什么 |
|---|---|---|---|
| 1 | 序列总览的列表不可交互 | `/api/series` 只有 4 列纯文本 | 序列可点开 → **抽屉**看序列图 + 检测分数 |
| 2 | 数据源不可编辑 | 只有 `POST /sources` + `DELETE` | 新增 `PATCH /api/platform/sources/{id}` + 编辑弹窗 |
| 3 | 指标不可编辑 | 只有 `POST /metrics` + `DELETE` | 新增 `PATCH /api/platform/metrics/{id}` + 编辑弹窗 |
| 4 | 检测任务详情太乱 | `/jobs/:id` 塞了 6 块内容 | 拆成 `/jobs/:id`、`/runs`、`/detections`、`/feedback` 四个独立路由 |
| 5 | 告警中心筛选少、无详情 | 前端只露了任务/等级；后端**已支持** `series_id/since/until` | 加序列 + 时间筛选；加**详情抽屉**看序列图 |
| 6 | 评估报告缺筛选/聚合/删除，Bad Case 命名不对 | `/api/summary` 读 `report.json`，每行无时间/来源维度 | 回测行补时间范围与来源维度；加筛选、聚合、排除记录；`/badcases` → `/detections` |

### 已确认的决策

- **D39** 评估仍跑在 synthetic 合成数据上，但**回测行补齐维度**（时间范围 + 数据来源），前端据此筛选与聚合。
- **D40** 「删除评估记录」= 排除该条检测记录，**不删 report.json**（`make evaluate` 重跑会复活删掉的行）。排除项存盘，可恢复。
- **D41** 任务详情页拆成**独立路由**（不是 Tabs）。
- **D42** 下钻一律用**抽屉**（Drawer），不离开当前列表页。
- **D43** 告警规则的**自由编辑仍不做**（spec §8.3 的约束），任务配置页只读展示规则表。

### 两条数据宇宙（不要混）

| | 平台侧 | 回测侧 |
|---|---|---|
| 端点前缀 | `/api/platform/*` | `/api/series*`、`/api/summary`、`/api/badcases`、`/api/annotate/*` |
| 数据 | `data/platform.db`（用户配的源/指标/任务） | `data/synthetic/`（合成数据 + `make evaluate` 产物） |
| 序列 id | `<metric>:<group>` | `<metric_class>-<seed>-<n>` |

序列总览、检测记录、评估报告属于**回测侧**；数据源、指标、任务、告警属于**平台侧**。

---

## Chunk 1: 序列可交互 + 「检测记录」正名

### Task 1: `/api/series` 带上时间范围与来源维度

**Files:**
- Modify: `src/anomaly_lab/web/app.py`（`list_series`）
- Test: `tests/web/test_api_contract.py`

- [ ] **Step 1: 写失败测试**

在 `tests/web/test_api_contract.py` 加：

```python
def test_series_list_carries_time_range(client):
    """序列列表要带时间范围 —— 前端要按时间筛序列。"""
    resp = client.get("/api/series")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "至少要有一条序列"
    for row in rows:
        assert "start_ts" in row
        assert "end_ts" in row
        assert row["source"], "要标明数据来源维度"
```

> ⚠️ 若测试库里没有 synthetic 数据集，这个测试会空断言失败。先确认 `tests/` 里有造数据的 fixture；没有就改成「有数据时才断言」。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py::test_series_list_carries_time_range -v`
Expected: FAIL —— `KeyError: 'start_ts'`

- [ ] **Step 3: 实现**

`src/anomaly_lab/web/app.py` 的 `list_series` 改成：

```python
    @app.get("/api/series")
    def list_series() -> list[dict]:
        rows = []
        for s in _series_map().values():
            stamps = s.timestamps
            rows.append(
                {
                    "series_id": s.series_id,
                    "metric_class": s.meta.get("metric_class", "unknown"),
                    "n": len(s.values),
                    "n_anomalies": int(s.labels.sum()) if s.labels is not None else 0,
                    # 时间范围 —— 前端要按时间筛序列
                    "start_ts": str(stamps[0]) if len(stamps) else None,
                    "end_ts": str(stamps[-1]) if len(stamps) else None,
                    # 数据来源维度 —— 评估报告按它聚合
                    "source": s.meta.get("source", "synthetic"),
                }
            )
        return rows
```

> ⚠️ `s.labels` 可能是 `None`（`label_source == "none"`），原来直接 `.sum()` 会崩 —— 顺手修掉。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/anomaly_lab/web/app.py tests/web/test_api_contract.py
git commit -m "feat(api): 序列列表带上时间范围与数据来源维度"
```

---

### Task 2: 抽出检测图组件

**Files:**
- Create: `frontend/src/features/detections/DetectionChart.tsx`
- Create: `frontend/src/features/detections/detectionChart.ts`
- Modify: `frontend/src/features/evaluation/BadcasesPage.tsx`
- Test: `frontend/src/features/detections/detectionChart.test.ts`

- [ ] **Step 1: 写失败测试**

`frontend/src/features/detections/detectionChart.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { buildDetectionOption } from './detectionChart'

const DATA = {
  series_id: 's1',
  detector: 'iqr',
  threshold: 2.5,
  score_type: 'z',
  timestamps: ['2026-01-01T00:00:00', '2026-01-01T00:05:00', '2026-01-01T00:10:00'],
  values: [1, 2, 3],
  scores: [0.1, 5, 0.2],
  badcases: [{ kind: 'false_positive', group: 'g', reason: 'r', indices: [1] }],
}

describe('buildDetectionOption', () => {
  it('把误报区间画成 markArea', () => {
    const option = buildDetectionOption(DATA, 'p0', 'p1')
    const series = option.series as Array<{ markArea?: { data?: unknown[] } }>
    const marked = series.find((s) => s.markArea?.data?.length)
    expect(marked).toBeTruthy()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/features/detections/detectionChart.test.ts`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现**

把 `BadcasesPage.tsx` 里的 `toRanges` / `badcaseLabel` / `badcaseColor` / `buildBadcaseOption` 搬到 `frontend/src/features/detections/detectionChart.ts`，函数改名 `buildDetectionOption`（语义更准：里面不只有 bad case，还有分数线）。

`frontend/src/features/detections/DetectionChart.tsx`：

```tsx
import ReactECharts from 'echarts-for-react'
import { useThemeModeValue } from '../../theme/ThemeModeContext'
import { cssVar, cssVarAlpha, invalidateCssVarCache, withAlpha } from '../../theme/cssVar'
import { buildDetectionOption } from './detectionChart'
import type { Badcases } from '../../api/types'

/** 检测详情图：序列值 + 分数 + 误报/漏报区间。 */
export function DetectionChart({ data }: { data: Badcases }) {
  const themeMode = useThemeModeValue()
  invalidateCssVarCache()
  const p0 = cssVar('--color-p0')
  const p1 = cssVar('--color-p1')
  const option = buildDetectionOption(data, p0, p1)
  return (
    <ReactECharts
      option={option}
      style={{ height: 360, width: '100%' }}
      notMerge
      key={themeMode}
    />
  )
}
```

- [ ] **Step 4: 让 BadcasesPage 改用新组件，跑测试**

Run: `cd frontend && npx vitest run src/features/detections/detectionChart.test.ts src/features/evaluation/evaluation.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/detections frontend/src/features/evaluation/BadcasesPage.tsx
git commit -m "refactor(frontend): 抽出检测图组件，供序列抽屉与检测记录页共用"
```

---

### Task 3: 序列总览可点开（抽屉）

**Files:**
- Modify: `frontend/src/api/types.ts`（`SeriesMeta` 加字段）
- Modify: `frontend/src/features/series/SeriesOverview.tsx`
- Create: `frontend/src/features/series/SeriesDetailDrawer.tsx`
- Modify: `frontend/src/pages/SeriesOverviewPage.tsx`
- Test: `frontend/src/features/series/seriesOverview.test.tsx`

- [ ] **Step 1: 写失败测试**

`frontend/src/features/series/seriesOverview.test.tsx`：

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SeriesOverview } from './SeriesOverview'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200 })))
})
afterEach(() => vi.unstubAllGlobals())

const SERIES = [{
  series_id: 'periodic-1-100', metric_class: 'periodic', n: 100, n_anomalies: 3,
  start_ts: '2026-01-01T00:00:00', end_ts: '2026-01-02T00:00:00', source: 'synthetic',
}]

describe('SeriesOverview', () => {
  it('序列名可点击 —— 点开看详情', () => {
    const onOpen = vi.fn()
    render(
      <SeriesOverview
        isLoading={false}
        error={null}
        series={SERIES}
        onOpenSeries={onOpen}
      />,
    )
    screen.getByText('periodic-1-100').click()
    expect(onOpen).toHaveBeenCalledWith('periodic-1-100')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/features/series/seriesOverview.test.tsx`
Expected: FAIL —— `onOpenSeries` 不存在

- [ ] **Step 3: 实现**

`types.ts` 的 `SeriesMeta` 加：

```ts
export interface SeriesMeta {
  series_id: string
  metric_class: string
  n: number
  n_anomalies: number
  /** 序列时间范围（ISO 字符串）—— 前端按它筛时间。 */
  start_ts: string | null
  end_ts: string | null
  /** 数据来源维度 —— 评估报告按它聚合。 */
  source: string
}
```

`SeriesOverview.tsx`：序列列渲染成 `<Button type="link" onClick={() => onOpenSeries(row.series_id)}>`，新增 `onOpenSeries` prop；「点数」列右边加「时间范围」列（`start_ts ~ end_ts`，只显示日期）。

`SeriesDetailDrawer.tsx`：抽屉内容 = 序列元信息 + `DetectionChart`（用 `/api/badcases?series_id=` 的数据）；该端点 404（有 `no_result` 业务态头）时显示「该序列还没有检测结果」。

`SeriesOverviewPage.tsx`：持有 `selectedSeries` state，渲染抽屉。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/features/series/seriesOverview.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/types.ts frontend/src/features/series frontend/src/pages/SeriesOverviewPage.tsx
git commit -m "feat(frontend): 序列总览可点开，看序列图与检测结果"
```

---

### Task 4: 「Bad Case」→「检测记录」

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`
- Rename: `frontend/src/features/evaluation/BadcasesPage.tsx` → `frontend/src/features/detections/DetectionsPage.tsx`
- Modify: `docs/PLATFORM.md`

- [ ] **Step 1: 改路由**

`router.tsx`：

```tsx
const DetectionsPage = lazy(() =>
  import('./features/detections/DetectionsPage').then((m) => ({ default: m.DetectionsPage })),
)
```

路由表：

```tsx
<Route path="/detections" element={<DetectionsPage />} />
<Route path="/badcases" element={<Navigate to="/detections" replace />} />
```

- [ ] **Step 2: 改导航**

`AppLayout.tsx` 的 `NAV_ITEMS`：`{ key: '/detections', label: '检测记录' }`。

- [ ] **Step 3: 页面标题与文案**

`DetectionsPage.tsx`：标题「检测记录」，副标题「序列上的检测结果与误报/漏报区间」。

- [ ] **Step 4: 验证**

Run: `cd frontend && npx tsc --noEmit && npm test`
Expected: 全绿（注意 `evaluation.test.tsx` 里引用旧路径的 import 要一起改）

- [ ] **Step 5: 提交**

```bash
git add -A frontend/src docs/PLATFORM.md
git commit -m "refactor(frontend): Bad Case 页正名为「检测记录」"
```

> ⚠️ 提交前务必 `git reset HEAD docs/my-thought.md`（用户文件，不提交）。

---

## Chunk 2: 数据源与指标可编辑

### Task 5: 后端 `PATCH /api/platform/sources/{id}`

**Files:**
- Modify: `src/anomaly_lab/platform/store.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Test: `tests/web/test_api_contract.py`

- [ ] **Step 1: 写失败测试**

```python
def test_patch_source_updates_fields(store_with_job):
    client = TestClient(create_app(platform_store=store_with_job))
    source_id = store_with_job.list_sources()[0].id
    resp = client.patch(f"/api/platform/sources/{source_id}", json={"name": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    # 只传 name 时其他字段不动
    assert resp.json()["path"] == store_with_job.get_source(source_id).path


def test_patch_source_rejects_duplicate_name(store_with_job):
    client = TestClient(create_app(platform_store=store_with_job))
    sources = store_with_job.list_sources()
    resp = client.patch(f"/api/platform/sources/{sources[0].id}", json={"name": sources[1].name})
    assert resp.status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -k patch_source -v`
Expected: FAIL —— 405 Method Not Allowed

- [ ] **Step 3: 实现 store 方法**

`store.py`：

```python
    def update_source(
        self, source_id: int, *, name: str | None = None, path: str | None = None,
        kind: str | None = None,
    ) -> Source:
        """改数据源。只传要改的字段，其余不动。"""
        current = self.get_source(source_id)
        new_name = validate_name(name if name is not None else current.name, "数据源名称")
        new_path = validate_name(path if path is not None else current.path, "数据源路径")
        new_kind = kind if kind is not None else current.kind
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE sources SET name = ?, path = ?, kind = ? WHERE id = ?",
                    (new_name, new_path, new_kind, source_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"数据源名称已存在: {new_name}") from exc
        return self.get_source(source_id)
```

- [ ] **Step 4: 实现端点**

`platform_routes.py`：

```python
    @router.patch("/api/platform/sources/{source_id}")
    def patch_source(source_id: int, payload: SourceIn) -> dict:
        try:
            source = _store().update_source(
                source_id, name=payload.name, path=payload.path, kind=payload.kind
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(source)
```

> ⚠️ `SourceIn` 的字段都是必填的话，PATCH 就必须全传。前端编辑弹窗会带全量字段提交 —— 可以接受。但更稳妥的是新建一个**全可选**的 `SourcePatchIn`。用后者：

```python
class SourcePatchIn(BaseModel):
    name: str | None = None
    path: str | None = None
    kind: str | None = None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/anomaly_lab/platform/store.py src/anomaly_lab/web/platform_routes.py tests/web/test_api_contract.py
git commit -m "feat(api): 支持编辑数据源"
```

---

### Task 6: 后端 `PATCH /api/platform/metrics/{id}`

**Files:**
- Modify: `src/anomaly_lab/platform/store.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Test: `tests/web/test_api_contract.py`

- [ ] **Step 1: 写失败测试**

```python
def test_patch_metric_updates_query(store_with_job):
    client = TestClient(create_app(platform_store=store_with_job))
    metric_id = store_with_job.list_metrics()[0].id
    resp = client.patch(
        f"/api/platform/metrics/{metric_id}",
        json={"query": "SELECT ts, value FROM metrics WHERE $timefilter"},
    )
    assert resp.status_code == 200
    assert "SELECT ts, value" in resp.json()["query"]
    # 名字没传就不该被清空
    assert resp.json()["name"] == store_with_job.get_metric(metric_id).name
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -k patch_metric -v`
Expected: FAIL —— 405

- [ ] **Step 3: 实现**

`store.py`：

```python
    def update_metric(self, metric_id: int, **fields) -> Metric:
        """改指标。只传要改的字段，其余不动。

        校验复用 add_metric 的那套（列名/时间格式/时区/频率）——
        非法配置在保存时就该被拦下，而不是等任务运行时才失败。
        """
        current = self.get_metric(metric_id)
        name = validate_name(fields.get("name") or current.name, "指标名称")
        query = validate_query(fields.get("query") or current.query)
        time_column = fields.get("time_column") or current.time_column
        value_column = fields.get("value_column") or current.value_column
        group_column = fields.get("group_column", current.group_column)
        time_format = fields.get("time_format") or current.time_format
        freq = fields.get("freq") or current.freq
        source_timezone = fields.get("source_timezone") or current.source_timezone
        missing_policy = fields.get("missing_policy") or current.missing_policy
        validate_identifier(time_column, "time_column")
        validate_identifier(value_column, "value_column")
        if group_column:
            validate_identifier(group_column, "group_column")
        validate_time_format(time_format)
        validate_missing_policy(missing_policy)
        validate_timezone(source_timezone)
        freq_delta(freq)
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE metrics SET name = ?, query = ?, time_column = ?, value_column = ?,"
                    " group_column = ?, time_format = ?, freq = ?, source_timezone = ?,"
                    " missing_policy = ? WHERE id = ?",
                    (name, query, time_column, value_column, group_column or None,
                     time_format, freq, source_timezone, missing_policy, metric_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该数据源下指标名称已存在") from exc
        return self.get_metric(metric_id)
```

端点：

```python
class MetricPatchIn(BaseModel):
    name: str | None = None
    query: str | None = None
    time_column: str | None = None
    value_column: str | None = None
    group_column: str | None = None
    time_format: str | None = None
    freq: str | None = None
    source_timezone: str | None = None
    missing_policy: str | None = None

    @router.patch("/api/platform/metrics/{metric_id}")
    def patch_metric(metric_id: int, payload: MetricPatchIn) -> dict:
        try:
            metric = _store().update_metric(metric_id, **payload.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(metric)
```

> ⚠️ `group_column` 用 `exclude_none=True` 会导致「清空分组列」传不上去 —— 本期不做「清空」操作（前端编辑框留空即不传），可接受。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/anomaly_lab/platform/store.py src/anomaly_lab/web/platform_routes.py tests/web/test_api_contract.py
git commit -m "feat(api): 支持编辑指标"
```

---

### Task 7: 前端封装 + 端点清单

**Files:**
- Modify: `frontend/src/api/platform.ts`
- Modify: `frontend/src/api/endpoints.test.ts`

- [ ] **Step 1: 加封装**

```ts
export const updateSource = (sourceId: number, payload: { name?: string; path?: string; kind?: string }) =>
  request<unknown>(`/api/platform/sources/${sourceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const updateMetric = (metricId: number, payload: Partial<Parameters<typeof createMetric>[0]>) =>
  request<unknown>(`/api/platform/metrics/${metricId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
```

- [ ] **Step 2: 更新端点清单**

`EXPECTED_PATHS` 加 `'/api/platform/sources/{id}'`、`'/api/platform/metrics/{id}'`（这两个已经在清单里了 —— 确认没重复）。

`endpoints.test.ts` 的测试体加：

```ts
await updateSource(1, { name: 'x' })
await updateMetric(1, { query: 'q' })
```

- [ ] **Step 3: 跑测试**

Run: `cd frontend && npx vitest run src/api/endpoints.test.ts`
Expected: PASS

- [ ] **Step 4: 后端反向守卫也要过**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py::test_frontend_covers_all_backend_endpoints -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api
git commit -m "feat(frontend): 封装数据源/指标的编辑端点"
```

---

### Task 8: 数据源/指标列表加编辑

**Files:**
- Modify: `frontend/src/features/sources/SourceForm.tsx`
- Modify: `frontend/src/features/sources/SourceList.tsx`
- Modify: `frontend/src/features/metrics/MetricForm.tsx`
- Modify: `frontend/src/features/metrics/MetricList.tsx`
- Modify: `frontend/src/pages/SourcesPage.tsx`
- Modify: `frontend/src/pages/MetricsPage.tsx`
- Modify: `frontend/src/features/delete/queries.ts`（若 mutation 缓存失效逻辑要复用）
- Test: `frontend/src/features/sources/sourceEdit.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// 断言：点「编辑」后弹窗里带出原值；改完保存会打 PATCH
```

用 `fetch` stub 记录 URL 与 method，断言出现 `PATCH /api/platform/sources/1`。

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

`SourceForm` 加 `editing?: CatalogSource` prop：
- 有 `editing` 时标题「编辑数据源」、okText「保存」、`initialValues` 取原值
- mutation 按 `editing` 分流：`editing ? updateSource(editing.id, payload) : createSource(payload)`

`SourceList` 加「编辑」列 → `onEdit(row)`；页面持有 `editingSource` state。

`MetricForm` 同理，`editing?: CatalogMetric`。

- [ ] **Step 4: 跑测试 + 全量**

Run: `cd frontend && npx vitest run src/features && npx tsc --noEmit && npm test`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add frontend/src
git commit -m "feat(frontend): 数据源与指标支持编辑"
```

---

## Chunk 3: 任务详情拆独立路由

### Task 9: `PATCH /api/platform/jobs/{id}` 支持改配置

**Files:**
- Modify: `src/anomaly_lab/platform/store.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Test: `tests/web/test_api_contract.py`

- [ ] **Step 1: 写失败测试**

```python
def test_patch_job_updates_window_points(store_with_job):
    client = TestClient(create_app(platform_store=store_with_job))
    job_id = store_with_job.list_jobs()[0].id
    resp = client.patch(f"/api/platform/jobs/{job_id}", json={"window_points": 120})
    assert resp.status_code == 200
    assert resp.json()["window_points"] == 120
    # 没传的字段不动
    assert resp.json()["detector"] == store_with_job.get_job(job_id).detector
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL —— 现在的 `JobToggleIn` 只有 enabled/detector，多余字段被 pydantic 忽略 → `window_points` 不变

- [ ] **Step 3: 实现**

`store.py` 加 `update_job_config(job_id, **fields)`：只更新传入的字段，逐字段校验（`window_points > 0`、`interval_seconds > 0`、阈值 `> 0`）。

`platform_routes.py` 把 `JobToggleIn` 扩成 `JobPatchIn`（全可选）：

```python
class JobPatchIn(BaseModel):
    name: str | None = None
    metric_id: int | None = None
    detector: str | None = None
    alert_threshold: float | None = None
    critical_threshold: float | None = None
    window_points: int | None = None
    interval_seconds: int | None = None
    enabled: bool | None = None
```

⚠️ `alert_rules` **不在其中**（D43：规则不可自由编辑）。

⚠️ 改 `metric_id` 时要检查该指标存在。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/anomaly_lab/platform/store.py src/anomaly_lab/web/platform_routes.py tests/web/test_api_contract.py
git commit -m "feat(api): 检测任务配置可编辑（告警规则除外）"
```

---

### Task 10: 任务详情拆成四个路由

**Files:**
- Modify: `frontend/src/pages/JobDetailPage.tsx`
- Create: `frontend/src/pages/job/JobConfigPanel.tsx`
- Create: `frontend/src/pages/job/JobRunsPanel.tsx`
- Create: `frontend/src/pages/job/JobDetectionsPanel.tsx`
- Create: `frontend/src/pages/job/JobFeedbackPanel.tsx`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/features/jobs/queries.ts`
- Test: `frontend/src/pages/JobDetailPage.test.tsx`

- [ ] **Step 1: 写失败测试**

扩展 `JobDetailPage.test.tsx`：

```tsx
it('任务详情页只展示配置，其余分区各有独立路由', async () => {
  renderPage('1')
  await waitFor(() => {
    const urls = calls.filter((u) => u.includes('/api/platform/jobs/'))
    expect(urls.some((u) => u.includes('/runs'))).toBe(true)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL（当前所有请求都在一个页面里）

- [ ] **Step 3: 实现**

`router.tsx`：

```tsx
<Route path="/jobs/:jobId" element={<JobDetailPage />} />
<Route path="/jobs/:jobId/runs" element={<JobDetailPage />} />
<Route path="/jobs/:jobId/detections" element={<JobDetailPage />} />
<Route path="/jobs/:jobId/feedback" element={<JobDetailPage />} />
```

`JobDetailPage.tsx` 改成**布局壳**：
- 用 `useLocation()` 判断当前分区（`pathname.endsWith('/runs')` 等）
- 顶部：任务名 + 摘要卡（指标名、检测序列数、最近运行时间、反馈条数）+ 分区导航（Tabs 或按钮组，用 `Link` 跳转）
- 内容区按分区渲染对应 Panel
- **各 Panel 自己发请求**（而不是壳统一发）—— 用 `enabled` 按分区开关，避免「在配置页也去拉 compare」

摘要卡的数据来源：
- 指标名 ← catalog
- 检测序列数 ← `useRuns(jobId)` 的最新 run 的 `n_series`
- 最近运行时间 ← 同上 `started_at`
- 反馈条数 ← `useFeedback(jobId)` 的长度

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/JobDetailPage.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src
git commit -m "refactor(frontend): 任务详情拆成配置/运行记录/检测结果/反馈四个路由"
```

---

## Chunk 4: 告警中心筛选 + 详情

### Task 11: 告警筛选加序列与时间范围

**Files:**
- Modify: `frontend/src/features/alerts/queries.ts`
- Modify: `frontend/src/features/alerts/AlertList.tsx`
- Test: `frontend/src/features/alerts/alerts.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
it('时间范围筛选会传给后端', async () => {
  // 选时间后应发 /api/platform/alerts?since=...&until=...
})
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

`AlertFilters` 加 `seriesId?: string`、`since?: string`、`until?: string`（后端已支持）。

`AlertList` 工具条加：
- `Select` 序列（候选从 `events` 里汇总去重）
- `RangePicker`（antd `DatePicker.RangePicker`）→ 转 ISO 字符串

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/alerts
git commit -m "feat(frontend): 告警中心支持序列与时间范围筛选"
```

---

### Task 12: 告警详情抽屉

**Files:**
- Create: `frontend/src/features/alerts/AlertDetailDrawer.tsx`
- Modify: `frontend/src/features/alerts/AlertList.tsx`
- Test: `frontend/src/features/alerts/alertDetail.test.tsx`

- [ ] **Step 1: 写失败测试**

断言：点「详情」→ 抽屉里出现序列名与图容器；请求打到 `/api/platform/jobs/{job_id}/preview?run_id=...&series_id=...`。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

抽屉数据来自 `GET /api/platform/jobs/{job_id}/preview?run_id={run_id}&series_id={series_id}`：
- `timestamps` / `values` / `scores` / `severity` 画图
- 用 `markArea` 高亮 `[start_ts, end_ts]` 区间
- 复用 `DetectionChart`？—— 不完全适用（数据结构不同：Badcases vs Preview）。**新建** `features/alerts/AlertChart.tsx`，用 ECharts 画「值 + 分数 + 告警区间」。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/alerts
git commit -m "feat(frontend): 告警详情抽屉，图形高亮告警区间"
```

---

## Chunk 5: 评估报告筛选 / 聚合 / 删除

### Task 13: 回测行补时间范围与来源维度

**Files:**
- Modify: `src/anomaly_lab/evaluation/backtest.py`
- Modify: `src/anomaly_lab/evaluation/report.py`
- Test: `tests/evaluation/test_backtest.py`（或新建）

- [ ] **Step 1: 写失败测试**

```python
def test_backtest_row_carries_time_range_and_source():
    rows = backtest_detector([make_series()], detector_factory)
    row = rows[0]
    assert row.start_ts and row.end_ts
    assert row.source
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`BacktestRow` 加三个字段：

```python
    #: 序列时间范围（ISO 字符串）—— 前端按它筛时间
    start_ts: str
    end_ts: str
    #: 数据来源维度 —— 前端按它聚合
    source: str
```

`backtest_detector` 里填：

```python
            start_ts=str(series.timestamps[0]) if len(series.timestamps) else "",
            end_ts=str(series.timestamps[-1]) if len(series.timestamps) else "",
            source=str(series.meta.get("source", "synthetic")),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/evaluation -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/anomaly_lab/evaluation tests/evaluation
git commit -m "feat(evaluation): 回测记录带上时间范围与数据来源维度"
```

---

### Task 14: 评估记录排除（删除 + 恢复）

**Files:**
- Create: `src/anomaly_lab/evaluation/exclusions.py`
- Modify: `src/anomaly_lab/web/app.py`
- Test: `tests/web/test_api_contract.py`

- [ ] **Step 1: 写失败测试**

```python
def test_excluded_row_disappears_from_summary(tmp_path):
    # 排除一条后 /api/summary 的 rows 里没有它，且 excluded 列表里有
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`src/anomaly_lab/evaluation/exclusions.py`：

```python
"""评估记录的排除清单。

「删除一条检测记录」= 把它记进排除清单，而不是改 report.json ——
report.json 是 `make evaluate` 的产物，重跑会把它整个覆盖掉。
"""

def exclusion_key(series_id: str, detector: str) -> str:
    return f"{series_id}::{detector}"


class ExclusionStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data.get("excluded", [])

    def add(self, series_id: str, detector: str) -> dict:
        items = self.list()
        key = exclusion_key(series_id, detector)
        if not any(i["key"] == key for i in items):
            items.append({
                "key": key,
                "series_id": series_id,
                "detector": detector,
                "excluded_at": datetime.now(UTC).isoformat(),
            })
            self._save(items)
        return next(i for i in items if i["key"] == key)

    def remove(self, series_id: str, detector: str) -> bool:
        items = self.list()
        key = exclusion_key(series_id, detector)
        kept = [i for i in items if i["key"] != key]
        if len(kept) == len(items):
            return False
        self._save(kept)
        return True
```

端点（放 `app.py`，与 `/api/summary` 同侧）：

```python
    @app.get("/api/evaluation/exclusions")
    def list_exclusions() -> dict:
        return {"excluded": _exclusions().list()}

    @app.post("/api/evaluation/exclusions")
    def add_exclusion(payload: ExclusionIn) -> dict:
        return _exclusions().add(payload.series_id, payload.detector)

    @app.delete("/api/evaluation/exclusions/{series_id}/{detector}")
    def remove_exclusion(series_id: str, detector: str) -> dict:
        ok = _exclusions().remove(series_id, detector)
        if not ok:
            raise HTTPException(status_code=404, detail="该记录不在排除清单里")
        return {"restored": True}
```

`/api/summary` 过滤：

```python
    @app.get("/api/summary")
    def summary() -> dict:
        path = _report_path()
        if not path.exists():
            return {"generated_at": None, "title": "", "summary": {}, "rows": [], "excluded": []}
        payload = json.loads(path.read_text(encoding="utf-8"))
        excluded = _exclusions().list()
        keys = {i["key"] for i in excluded}
        payload["rows"] = [
            row for row in payload.get("rows", [])
            if exclusion_key(row["series_id"], row["detector"]) not in keys
        ]
        payload["excluded"] = excluded
        return payload
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/web/test_api_contract.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/anomaly_lab/evaluation src/anomaly_lab/web/app.py tests/web/test_api_contract.py
git commit -m "feat(api): 评估记录可排除与恢复"
```

---

### Task 15: 前端封装评估排除

**Files:**
- Modify: `frontend/src/api/series.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.test.ts`

- [ ] **Step 1: 加封装与类型**

```ts
export interface Exclusion {
  key: string
  series_id: string
  detector: string
  excluded_at: string
}

export const getExclusions = () => request<{ excluded: Exclusion[] }>('/api/evaluation/exclusions')

export const excludeEvaluationRow = (seriesId: string, detector: string) =>
  postJson<Exclusion>('/api/evaluation/exclusions', { series_id: seriesId, detector })

export const restoreEvaluationRow = (seriesId: string, detector: string) =>
  request<unknown>(
    `/api/evaluation/exclusions/${encodeURIComponent(seriesId)}/${encodeURIComponent(detector)}`,
    { method: 'DELETE' },
  )
```

`Summary` 类型加 `excluded?: Exclusion[]`。

`EXPECTED_PATHS` 加 `'/api/evaluation/exclusions'`、`'/api/evaluation/exclusions/{id}'`。

> ⚠️ `normalize()` 里 `/api/evaluation/exclusions/{series_id}/{detector}` 有**两个**动态段 —— 现有 normalize 只把末段替换。需要在 normalize 里加规则：把 `/api/evaluation/exclusions/xxx/yyy` 归一成 `/api/evaluation/exclusions/{id}/{id}`，或在 EXPECTED_PATHS 里写成两段形式并让 normalize 把前一段也替换。**选后者更省事**：normalize 加一条 `path.replace(/\/api\/evaluation\/exclusions\/[^/]+\/[^/]+$/, '/api/evaluation/exclusions/{id}/{id}')`。

- [ ] **Step 2: 跑测试**

Run: `cd frontend && npx vitest run src/api/endpoints.test.ts`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api
git commit -m "feat(frontend): 封装评估记录排除端点"
```

---

### Task 16: 评估报告加筛选与维度聚合

**Files:**
- Modify: `frontend/src/features/evaluation/EvaluationPage.tsx`
- Create: `frontend/src/features/evaluation/filters.ts`
- Create: `frontend/src/features/evaluation/aggregate.ts`
- Modify: `frontend/src/features/evaluation/queries.ts`
- Test: `frontend/src/features/evaluation/aggregate.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
import { aggregateBy } from './aggregate'
it('按检测算法聚合', () => {
  const out = aggregateBy(rows, 'detector')
  expect(out.find((b) => b.key === 'iqr')?.n_series).toBe(2)
})
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`filters.ts`：

```ts
export type DimensionKey = 'detector' | 'metric_class' | 'source'

export interface EvaluationFilters {
  since?: string
  until?: string
  detector?: string
  metricClass?: string
  source?: string
}

export function filterRows(rows: EvaluationRow[], filters: EvaluationFilters): EvaluationRow[] {
  return rows.filter((row) => {
    if (filters.detector && row.detector !== filters.detector) return false
    if (filters.metricClass && row.metric_class !== filters.metricClass) return false
    if (filters.source && row.source !== filters.source) return false
    // 时间筛选：区间**相交**即命中（不是完全包含）
    if (filters.since && row.end_ts < filters.since) return false
    if (filters.until && row.start_ts > filters.until) return false
    return true
  })
}
```

`aggregate.ts`：

```ts
export interface AggregateBucket {
  key: string
  n_series: number
  n_truth: number
  n_pred: number
  precision: number
  recall: number
  f1: number
  range_f1: number
}

export function aggregateBy(rows: EvaluationRow[], dim: DimensionKey): AggregateBucket[] {
  const buckets = new Map<string, EvaluationRow[]>()
  for (const row of rows) {
    const key = String(row[dim] ?? '—')
    const list = buckets.get(key) ?? []
    list.push(row)
    buckets.set(key, list)
  }
  const mean = (values: number[]) =>
    values.length ? values.reduce((a, b) => a + b, 0) / values.length : NaN
  return [...buckets.entries()]
    .map(([key, list]) => ({
      key,
      n_series: list.length,
      n_truth: list.reduce((a, r) => a + r.n_truth, 0),
      n_pred: list.reduce((a, r) => a + r.n_pred, 0),
      precision: mean(list.map((r) => r.precision)),
      recall: mean(list.map((r) => r.recall)),
      f1: mean(list.map((r) => r.f1)),
      range_f1: mean(list.map((r) => r.range_f1)),
    }))
    .sort((a, b) => b.f1 - a.f1)
}
```

`EvaluationPage` 顶部加筛选条：时间范围（RangePicker）、检测算法、形态、数据来源下拉；下方加「聚合视图」：维度选择器 + 聚合表；再下面是明细表。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/features/evaluation`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/evaluation
git commit -m "feat(frontend): 评估报告支持时间筛选与维度聚合"
```

---

### Task 17: 评估报告删除记录 + 恢复

**Files:**
- Modify: `frontend/src/features/evaluation/EvaluationPage.tsx`
- Modify: `frontend/src/features/evaluation/queries.ts`
- Test: `frontend/src/features/evaluation/evaluation.test.tsx`

- [ ] **Step 1: 写失败测试**

断言：点某行的「删除」→ 打出 `POST /api/evaluation/exclusions`；被排除的行从表里消失。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`queries.ts` 加：

```ts
export function useExcludeEvaluationRow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { series_id: string; detector: string }) => excludeEvaluationRow(v.series_id, v.detector),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['summary'] }),
  })
}
```

明细表加「操作」列 → 「删除记录」按钮（`Popconfirm` 二次确认，说明「会从报告中排除，可恢复」）。

页头加「已排除记录」按钮 → 抽屉列出被排除的记录，每行「恢复」。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/evaluation
git commit -m "feat(frontend): 评估报告可删除与恢复检测记录"
```

---

### Task 18: 端点清单同步 + 文档 + 全量验证

**Files:**
- Modify: `frontend/src/api/endpoints.test.ts`
- Modify: `docs/PLATFORM.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: 全量验证**

```bash
make lint
.venv/bin/python -m pytest -q
cd frontend && npx tsc --noEmit && npm test && npm run build && cd ..
```

Expected: 全绿

- [ ] **Step 2: 更新文档**

`docs/PLATFORM.md`：
- 路由表补 `/jobs/:id/runs`、`/jobs/:id/detections`、`/jobs/:id/feedback`、`/detections`
- 「Bad Case」→ 「检测记录」
- 端点清单补 PATCH 与评估排除端点

`docs/ROADMAP.md`：勾掉「前端可交互性」相关的项。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/endpoints.test.ts docs/PLATFORM.md docs/ROADMAP.md
git commit -m "docs: 同步前端信息架构重构的路由与端点"
```

> ⚠️ 提交前 `git reset HEAD docs/my-thought.md`。

---

## 风险与注意事项

| 风险 | 处置 |
|---|---|
| 编辑指标后历史 run 不一致 | run 已落盘，**历史不受影响**；新 run 用新配置。文档里写明 |
| 评估报告没有 synthetic 数据时是空的 | 空态文案说明「先跑 `make evaluate`」 |
| 抽屉里 ECharts 体积 | 抽屉所在页面已懒加载，ECharts 不额外增加首屏负担 |
| antd `RangePicker` 在测试里要 mock | 用 `vi.mock('antd/es/date-picker', ...)` 或改用原生 `input[type=date]` |
| antd 中文两字按钮自动插空格 | 测试断言用正则 `/删\s*除/` |
| `Select` 不是原生 select | 测试用 `click` + `findByTitle` |
| 含 `Link` 的组件要包 `MemoryRouter` | 测试里别忘 |
