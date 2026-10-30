# 告警中心与删除功能（设计）

日期：2026-10-30
状态：待实现
前置：Web 前端分离（Chunk 0–6）、表单即时校验与 Chronos 接入（`5a7eb4f`）

## 1. 目标与范围

补齐 ROADMAP 上剩余的两项「以后做」：

- **告警中心** —— 跨任务汇总告警事件的列表页（只读）。
- **删除功能** —— 任务 / 指标 / 数据源的删除端点与前端入口（级联删除）。

明确**不做**（留给以后）：告警事件状态机（确认 / 抑制 / 通知）、删除的回收站与恢复。

## 2. 现状与约束

### 2.1 告警目前存在哪

告警**不是**一等公民：

| 位置 | 内容 |
|---|---|
| `runs` 表 | 只有计数 `n_alerts`，无明细 |
| run 目录 `cache/platform/runs/{run_id}/*.npz` | 逐点 `severity` 数组（0 = 正常，1..N = 档位序号） |
| run 目录 `index.json` | 每条序列的 `series_id` / `group` / `n_alerts` / `file` |

档位名不是固定的 `P0/P1` —— 它来自任务的规则表（`AlertRule.level`，可自定义如「注意」），
所以告警事件必须带上**档位序号**与**档位名**两个字段。

### 2.2 删除的现有基础

`platform/store.py` 的 schema 已经写了 `ON DELETE CASCADE`，且 `_conn()` 里
`PRAGMA foreign_keys=ON` —— **级联删除在数据库层已经可用**，只是没有端点。

依赖链：`sources → metrics → jobs → runs / feedback`。

漏掉的一环是**文件系统**：每次运行的产物在 `cache/platform/runs/{run_id}/`，
删掉 job/metric/source 后这些目录会变成孤儿垃圾。

### 2.3 滚动窗口带来的重复问题

任务每次运行取「最近 `window_points` 个点」的窗口，同一段异常会被**连续多次 run 重复报出**。
如果按时间范围扫所有历史 run，同一个异常区间会出现很多遍。

**决策：以每个任务的最新一次成功运行为准。** 这样天然无重复，语义是
「当前各任务处于什么告警状态」，也正好对应告警中心的用途。

## 3. 告警中心

### 3.1 后端

**新模块 `src/anomaly_lab/platform/alert_events.py`**（纯逻辑，不碰 HTTP）：

```python
@dataclass(frozen=True)
class AlertEvent:
    job_id: int
    job_name: str
    metric_id: int
    metric_name: str
    series_id: str
    group: str | None
    level: str          # 档位名（来自规则表，可能不是 P0/P1）
    level_index: int    # 档位序号，越大越严重
    start_ts: str       # ISO 秒精度
    end_ts: str
    n_points: int       # 区间内的告警点数
    max_score: float    # 区间内峰值分数
    detector: str
    score_type: str
    run_id: int
```

两个函数：

- `events_from_series(severity, timestamps, scores, levels, ...) -> list[AlertEvent]`
  —— 把逐点 `severity` 合并成区间。规则：`severity > 0` 的**连续**点合成一个区间
  （中间隔着正常点就断开）；区间的档位取**区间内 severity 的最大值**；
  `max_score` 取区间内 scores 的最大值；`start_ts`/`end_ts` 是区间首尾的时间戳。
  这是纯函数，可以脱 IO 单测。

- `collect_alert_events(store, data_root) -> tuple[list[AlertEvent], list[dict]]`
  —— 遍历所有 job，取 `store.latest_run(job.id)`，读 `index.json` 与各序列 npz，
  汇总事件。第二个返回值是 **skipped 列表**（见 §3.3）。

### 3.2 端点

`GET /api/platform/alerts`

| 参数 | 类型 | 说明 |
|---|---|---|
| `job_id` | int? | 只看某个任务 |
| `level` | str? | 只看某个档位（按档位名精确匹配） |
| `series_id` | str? | 只看某条序列 |
| `since` / `until` | str? | 事件**开始时间**落在该区间内（ISO 字符串） |

响应：

```json
{
  "events": [ { ...AlertEvent } ],
  "levels": ["P1", "P0"],
  "jobs": [ {"id": 3, "name": "demo-job"} ],
  "skipped": [ {"job_id": 4, "name": "x", "reason": "还没有运行记录"} ]
}
```

- `levels` / `jobs` 是**筛选下拉的候选值**（从实际数据汇总，不是硬编码）。
- `skipped` 是**诚实报告**：某个任务没被纳入统计时必须说清楚为什么
  （还没跑过 / 上次运行失败 / 结果文件缺失），不能静默消失。

### 3.3 什么情况下会被 skipped

| 情况 | reason |
|---|---|
| 任务没有 run 记录 | `还没有运行记录` |
| 最新 run 状态是 failed | `最近一次运行失败：<error>` |
| 最新 run 是 running | `最近一次运行尚未结束` |
| `index.json` 不存在 | `运行结果文件缺失` |
| npz 文件缺失 | `序列结果文件缺失：<series_id>` |

`insufficient_data` 的 run **不算 skipped** —— 它没有告警（数据不足 ≠ 一切正常，
但也不是告警），只是贡献 0 个事件。

### 3.4 前端

- 新页面 `frontend/src/pages/AlertsPage.tsx` + `frontend/src/features/alerts/`
  （`AlertList.tsx` / `queries.ts`）。
- 路由 `/alerts`，侧边栏「告警中心」（放在「检测任务」之后）。
- 筛选栏：任务下拉、档位下拉、时间范围（`RangePicker`）。
- 表格列：等级（Tag，颜色按档位严重度）、时间（起 ~ 止）、点数、峰值分数、
  任务（链接到 `/jobs/{id}`）、序列、算法。
- 空态：**区分两种空** —— 「没有任务」与「任务都正常」文案不同
  （前者提示去建任务，后者说明「当前没有告警」）。
- 复用既有 `StateBoundary`（五态）与 `features/*/queries.ts` 的
  TanStack Query 模式。

## 4. 删除功能

### 4.1 后端

**store 层**（`platform/store.py`）新增三个方法，返回**删除统计**：

```python
def delete_job(self, job_id: int) -> dict:      # {"jobs":1,"runs":3,"feedback":2}
def delete_metric(self, metric_id: int) -> dict:  # 连带 jobs/runs/feedback
def delete_source(self, source_id: int) -> dict:  # 连带 metrics/jobs/runs/feedback
```

- 依赖计数用 `SELECT COUNT(*)` 在删除前查出来（用于响应体与前端提示）。
- 数据库删除靠现有的 `ON DELETE CASCADE`。
- 不存在 → 抛 `ValueError` → 路由层转 404。

**文件系统清理**（不能靠数据库外键）：

- 删除前先取出该 job（或其下属 job）的所有 `run_id`；
- 数据库事务提交后，逐个删 `cache/platform/runs/{run_id}/` 目录；
- **文件删除失败不回滚数据库** —— 记录警告即可，DB 一致性优先。

**运行中的任务**：runner 模块已有 `_INFLIGHT`（job_id → run_id），
手动触发与调度触发都会登记。删除前检查，命中则返回 **409**「任务正在运行中，
请等本次运行结束后再删除」。

**端点**：

```
DELETE /api/platform/jobs/{job_id}
DELETE /api/platform/metrics/{metric_id}
DELETE /api/platform/sources/{source_id}
```

响应：`{"deleted": {"jobs": 2, "metrics": 1, "runs": 5, "feedback": 3}}`

### 4.2 前端

- 新目录 `frontend/src/features/delete/`：
  - `DeleteButton.tsx` —— AntD `Popconfirm` 包装的删除按钮，标题里带上
    **连带删除的数量**。
  - `queries.ts` —— 三个 mutation（`useDeleteJob/Metric/Source`），
    成功后 `invalidateQueries(['catalog'])`。
- 影响预览**不新增后端端点**：前端从 `catalog`（已有全量 sources/metrics/jobs）
  自己算出依赖数量，在确认弹窗里显示「将连带删除 N 个指标、M 个任务」。
- 三个列表组件加「操作」列：
  - `features/sources/SourceList.tsx`
  - `features/metrics/MetricList.tsx`
  - `features/jobs/JobList.tsx`（已有操作列，追加删除按钮）
- 删除数据源/指标的确认文案要**具体**（「将连带删除 2 个指标、3 个任务」），
  不能是笼统的「确定吗」。

### 4.3 前端 API 封装

`api/platform.ts` 新增：

```ts
export const deleteJob = (jobId: number) =>
  request<{ deleted: DeleteStats }>(`/api/platform/jobs/${jobId}`, { method: 'DELETE' })
export const deleteMetric = (metricId: number) => ...
export const deleteSource = (sourceId: number) => ...
```

## 5. 错误处理

| 场景 | 响应 |
|---|---|
| 删不存在的对象 | 404 + 人话 detail |
| 任务正在运行 | 409 + 「请等本次运行结束后再删除」 |
| 前端请求失败 | `message.error(err.message)` —— 既有模式，不静默 |
| 删除后列表 | `invalidateQueries(['catalog'])` 让列表刷新 |

## 6. 测试

**后端**

- `tests/platform/test_alert_events.py`
  - 区间合并：连续 / 断开 / 全正常 / 单点（纯函数，不碰 IO）
  - 档位取区间内最大值
  - `max_score` 取区间内峰值
- `tests/web/test_alerts_endpoint.py`
  - 建源 → 指标 → 任务 → 跑一次 → `GET /api/platform/alerts` 有事件
  - 筛选：`job_id` / `level` / `series_id` / 时间范围
  - 没有 run 的任务出现在 `skipped` 里，**不是**静默消失
- `tests/web/test_delete_endpoints.py`
  - 删 job → 404 再查
  - 删 metric → 连带 job/runs/feedback 都没了
  - 删 source → 连带 metric/job 都没了
  - run 目录文件真的被删了
  - 删不存在的 → 404
- `tests/web/test_api_contract.py` 追加 `/api/platform/alerts` 的字段守卫。

**前端（vitest）**

- `features/alerts/alerts.test.tsx` —— 渲染、筛选、空态区分
- `features/delete/DeleteButton.test.tsx` —— 确认弹窗文案带连带数量

## 7. 文档

- `docs/PLATFORM.md` —— 新增「告警中心」节；新增删除端点说明。
- `docs/ROADMAP.md` —— 勾掉这两项「以后做」，新增本轮小节。
- `README.md` —— 平台切片提到新页面与删除能力。

## 8. 验收标准

1. `GET /api/platform/alerts` 返回跨任务事件，字段完整，契约守卫绿。
2. 事件按区间聚合，档位为区间内最高档。
3. 跳过的任务在 `skipped` 里给出原因。
4. 前端 `/alerts` 页面能按任务/档位/时间筛选，空态文案区分「没有任务」与「没有告警」。
5. 删除任务/指标/数据源后，DB 里不留孤儿记录，run 目录文件被清理。
6. 运行中的任务删除返回 409。
7. pytest / vitest / ruff 全绿，`npm run build` 通过。
