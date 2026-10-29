# 前端分离重构 · 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 anomaly-lab 的 Web 端从「Jinja2 模板 + 命令式 JS」重写为独立的前后端分离前端工程（React 18 + TS + Vite），功能逐项等价迁移，并补齐五态处理。

**Architecture:** 后端只出 JSON API（契约不变，仅新增一个可选响应头 `X-Anomaly-Biz-State` 区分业务态）；前端是仓库根的 `frontend/` 独立工程，构建产物 `frontend/dist` 由 FastAPI 托管，`/api/*` 之外的路径一律回退到 `index.html`（SPA fallback）。分 6 个 chunk 推进，每个 chunk 结束都保持旧页面可用，随时可停。

**Tech Stack:** React 18 · TypeScript · Vite · Ant Design v5 · TanStack Query · react-router-dom · ECharts 5 + echarts-for-react · vitest + @testing-library/react

**Spec:** [`docs/superpowers/specs/2026-10-30-frontend-separation-design.md`](../specs/2026-10-30-frontend-separation-design.md)（第 3 稿，已过两轮 review）

---

## 执行须知

**三条硬约定**（违反会打穿验收）：

1. **颜色只有一个来源** —— `frontend/src/styles/tokens.css` 是唯一定义处。AntD 的 `ConfigProvider` theme token 与 ECharts 的 palette 都从它派生。**不允许组件里写死色值。**
2. **`alert()` / `prompt()` 一律不许出现** —— 错误一律走 `client.ts` 抛 `ApiError`，页面用 AntD `Alert` / `message.error` 展示。
3. **后端 API 的 JSON 结构一字不改** —— 唯一允许的变更是给 5 处业务态 404 加**可选响应头**。

**本计划与 skill 默认的偏离**（已与用户确认）：

- **不建 worktree** —— 用户明确要求直接在 `master` 上实现。
- **不是每个任务都写完整组件代码** —— 对「非显然」的部分（错误归一化、SPA fallback、业务态响应头、token 落地）给完整代码；对常规 React 组件给**精确的 props/接口契约 + 验收点**，实现时按契约写。原因：整份计划塞满 JSX 会到几千行，且到实现时必然与实际 UI 迭代脱节。**接口契约是硬要求**，不是建议。

**提交纪律**：每次提交**精确 `git add <具体文件>`**。`docs/DESIGN.md`（用户有未提交改动）与 `docs/my-thought.md`（用户未跟踪文件）**全程不动、不提交**。

**前置条件**：node ≥ 18（本机 v24）、npm ≥ 9（本机 11）可用；`make frontend-install` 用 `npm ci`，需要仓库里已有 `frontend/package-lock.json`（Task 2 首次生成后提交）。

---

## Chunk 0: 视觉方向落地

### Task 1: 产出三套视觉原型并选定

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`

- [ ] **Step 1: 确认三套原型已产出**

open-design 的三个 project 各有一个 run：

| 方向 | project | runId |
|---|---|---|
| A 暗色指挥中心 | `anomaly-lab-console-mission-control` | `d63f0aa8-a190-4f44-b099-26c205561ab0` |
| B 云平台暗色 | `anomaly-lab-console-dashboard-dark` | `f3d0a223-6c23-4343-908b-c8d26201cfac` |
| C 浅色企业风 | `anomaly-lab-console-light-enterprise` | `37fcb31b-3b2a-45d4-9019-cc1257b96bf5` |

用 open-design 的 `get_run` 轮询状态、`list_files` 看是否产出了 `index.html`。
若某个 run 仍无产物（`deliverableValidation` 为 `no_artifact`），说明该方向的 agent 只出了计划没落文件 ——
**换 prompt 重跑该方向**（prompt 里写「计划已批准，现在立刻实现它」，并强调「不要再输出计划，直接写文件」）。

- [ ] **Step 2: 请用户从三套里选一套**

把三套的 preview URL 并排给用户。**不要替用户选。**

- [ ] **Step 3: 读选定方向的 design system**

用 open-design MCP 资源读 `od://design-systems/<id>/DESIGN.md`：

| 方向 | design system id |
|---|---|
| A 暗色指挥中心 | `mission-control` |
| B 云平台暗色 | `dashboard` |
| C 浅色企业风 | `enterprise` |

该 DESIGN.md 里含完整的色板、排版、间距、圆角 token，照抄即可。

- [ ] **Step 4: 落地 `tokens.css`**

把该 design system 的**色板、排版、间距、圆角、阴影**全部落成 CSS 变量。变量名固定用这套
（后续所有组件只准引用这些名字）：

```css
/* frontend/src/styles/tokens.css */
:root {
  /* 表面 */
  --surface-canvas: ...;      /* 页面底色 */
  --surface-panel:  ...;      /* 面板/卡片 */
  --surface-raised: ...;      /* 悬浮/选中 */
  --border-subtle: ...;
  --border-strong: ...;

  /* 文本 */
  --text-primary:   ...;
  --text-secondary: ...;
  --text-tertiary:  ...;

  /* 语义色 —— 告警三档固定占用这三个 */
  --accent:          ...;     /* 主操作 */
  --status-normal:   ...;     /* severity 0 = 正常 */
  --status-p1:       ...;     /* severity 1 = P1（警告色） */
  --status-p0:       ...;     /* severity 2 = P0（危险色） */
  --status-info:     ...;

  /* 分类色（多算法对比的折线用，≥4 个算法要能区分开） */
  --series-1: ...; --series-2: ...; --series-3: ...; --series-4: ...; --series-5: ...;

  /* 排版 */
  --font-sans: ...;
  --font-mono: ...;           /* 数值/时间戳用等宽 */
  --text-xs: ...; --text-sm: ...; --text-md: ...; --text-lg: ...; --text-xl: ...;

  /* 间距与圆角 */
  --space-1: ...; --space-2: ...; --space-3: ...; --space-4: ...; --space-6: ...; --space-8: ...;
  --radius-sm: ...; --radius-md: ...; --radius-lg: ...;
}
```

**验收点**：
- 三个 severity 颜色（`--status-normal/p1/p0`）与 AntD 的 `success`/`warning`/`error` 一一对应
- 图表与表格用**同一个** `--status-p0`
- 分类色 ≥5 个且两两可辨

- [ ] **Step 5: 落地 `global.css`**

只放 reset + 少量全局样式（body 底色、字体、滚动条、`.empty-state` / `.muted` 这两个通用类）。
**不放任何组件样式。**

- [ ] **Step 6: 提交**

```bash
git add frontend/src/styles/tokens.css frontend/src/styles/global.css
git commit -m "feat(frontend): 视觉 token 落地（<选定的 design system 名字>）"
```

---

## Chunk 1: 前端工程骨架 + API 层

### Task 2: 初始化 frontend 工程

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/.gitignore`
- Modify: `.gitignore`（仓库根）

- [ ] **Step 1: 建目录并写 `package.json`**

⚠️ **包名必须是 `echarts-for-react`，不是 `react-echarts`** —— 后者 npm 上最高只有 `0.1.1`，
写 `^5` 会直接 `ETARGET` 装不上。`echarts-for-react` 是 React + ECharts 的通行封装，
peer 依赖 `echarts ^3||^4||^5||^6`。

```json
{
  "name": "anomaly-lab-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5",
    "antd": "^5",
    "echarts": "^5",
    "echarts-for-react": "^3",
    "react": "^18",
    "react-dom": "^18",
    "react-router-dom": "^6"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6",
    "@testing-library/react": "^16",
    "@testing-library/user-event": "^14",
    "@types/react": "^18",
    "@types/react-dom": "^18",
    "@vitejs/plugin-react": "^4",
    "jsdom": "^25",
    "typescript": "^5",
    "vite": "^5",
    "vitest": "^2"
  }
}
```

- [ ] **Step 2: 装依赖**

```bash
cd frontend && npm install
```

Run: 生成 `frontend/package-lock.json`
Expected: 无报错。**若报 `ETARGET`，说明包名写错了，回 Step 1。**

⚠️ **`package-lock.json` 必须提交进仓库** —— 之后 `make frontend-install` 才能用 `npm ci`。

- [ ] **Step 3: 写 `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

⚠️ `noUnusedLocals: true` —— **任何未使用的 import 会让 `tsc -b` 失败**，
后面每个任务写代码时都要注意（import 了就用，别留着用不上的）。

- [ ] **Step 4: 写 `vite.config.ts`**

⚠️ **不建 `tsconfig.node.json`** —— `tsconfig.json` 没有 `references`，`vite.config.ts`
根本不会被 `tsc -b` 检查；而带 `"types": ["node"]` 的独立配置在没装 `@types/node` 时
会直接报 `TS2688: Cannot find type definition file for 'node'`。一个 `tsconfig.json` 就够。

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // dev 时前端与 API 同源（浏览器只跟 :5173 说话），所以不需要 CORS
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

- [ ] **Step 5: 写 `index.html` 与 `src/main.tsx`**

`index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>anomaly-lab</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`src/main.tsx`（先只渲染一个占位，Task 5 再接 Router）：

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles/tokens.css'
import './styles/global.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div style={{ padding: 24, fontFamily: 'var(--font-sans)' }}>anomaly-lab 前端已就绪</div>
  </React.StrictMode>,
)
```

- [ ] **Step 6: 写测试 setup 与类型声明**

`frontend/src/test/setup.ts`：

```ts
import '@testing-library/jest-dom/vitest'
```

`frontend/src/vite-env.d.ts`：

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 7: 配 `.gitignore`**

`frontend/.gitignore`：

```
node_modules/
dist/
```

仓库根 `.gitignore` 追加一行 `node_modules/`（`dist/` 已存在，已覆盖 `frontend/dist`）。

- [ ] **Step 8: 验证**

```bash
cd frontend && npm run build
```

Expected: 生成 `frontend/dist/index.html` 与 `frontend/dist/assets/*`，**无 TS 报错**
（特别是不能有 `TS6133: declared but its value is never read`）

- [ ] **Step 9: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json \
        frontend/vite.config.ts frontend/index.html \
        frontend/src/main.tsx frontend/src/vite-env.d.ts frontend/src/test/setup.ts \
        frontend/.gitignore .gitignore
git commit -m "feat(frontend): 初始化 React + TS + Vite 工程骨架"
```

---

### Task 3: API 层 —— client 与错误归一化

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts`
- Test: `frontend/src/api/client.test.ts`

**这一步是整个前端的地基** —— spec §6.2 的三种情况都在这里落地。

- [ ] **Step 1: 写失败的测试**

`frontend/src/api/client.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { ApiError, request } from './client'

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

/** request() 的 T 推不出来，catch 回来的值是 unknown —— 用这个助手拿类型安全的 ApiError。 */
async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    return e as ApiError
  }
  throw new Error('期望抛 ApiError，但请求成功了')
}

describe('request', () => {
  it('把 422 的数组 detail 拼成可读文案', async () => {
    const resp = jsonResponse(422, {
      detail: [
        { loc: ['body', 'freq'], msg: 'value is not a valid frequency', type: 'value_error' },
        { loc: ['body', 'query'], msg: 'field required', type: 'missing' },
      ],
    })
    const err = await expectApiError(request('/api/platform/metrics', { method: 'POST' }, resp))
    expect(err.status).toBe(422)
    expect(err.message).toBe('value is not a valid frequency；field required')
  })

  it('字符串 detail 原样透出', async () => {
    const resp = jsonResponse(404, { detail: '序列不存在: abc' })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.message).toBe('序列不存在: abc')
  })

  it('读取业务态响应头 X-Anomaly-Biz-State', async () => {
    const resp = jsonResponse(404, { detail: '该任务还没有运行记录' }, {
      'X-Anomaly-Biz-State': 'no_run',
    })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.bizState).toBe('no_run')
  })

  it('响应头缺失时按 detail 前缀兜底', async () => {
    const resp = jsonResponse(404, { detail: '该任务还没有运行记录' })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.bizState).toBe('no_run')
  })

  it('既没有响应头也不是业务态文案时 bizState 为 undefined', async () => {
    const resp = jsonResponse(404, { detail: '序列不存在: abc' })
    const err = await expectApiError(request('/api/x', {}, resp))
    expect(err.bizState).toBeUndefined()
  })

  it('2xx 直接返回 body', async () => {
    const resp = jsonResponse(200, { ok: true })
    await expect(request('/api/x', {}, resp)).resolves.toEqual({ ok: true })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/api/client.test.ts
```

Expected: FAIL —— `Cannot find module './client'`

- [ ] **Step 3: 实现 `client.ts`**

```ts
/** 后端用这个响应头区分「业务态」（空/数据不足）与「真错误」。 */
export type BizState =
  | 'no_run'
  | 'no_series'
  | 'no_data'
  | 'insufficient_data'
  | 'no_algorithms'
  | 'no_result'

export class ApiError extends Error {
  readonly status: number
  readonly bizState?: BizState
  constructor(status: number, message: string, bizState?: BizState) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.bizState = bizState
  }
}

/**
 * 响应头缺失时的兜底：按 detail **前缀**判定业务态。
 *
 * 为什么要兜底：老版本后端（或任何没加头的 404）不该一律显示成红色错误框 ——
 * 「该任务还没有运行记录」是业务态（spec §6.1）。
 *
 * 前缀表与 spec §4.2.1 的 detail 列一一对应。
 * 后端改文案时**这里要同步改**，否则会退化成红框。
 */
const DETAIL_PREFIX_TO_STATE: ReadonlyArray<[string, BizState]> = [
  ['该任务还没有运行记录', 'no_run'],
  ['该次运行没有序列结果', 'no_series'],
  ['该窗口内没有取到数据', 'no_data'],
  ['有效点仅', 'insufficient_data'],
  ['没有可对比的算法', 'no_algorithms'],
  ['该序列还没有检测结果', 'no_result'],
]

function stateFromDetail(detail: string): BizState | undefined {
  for (const [prefix, state] of DETAIL_PREFIX_TO_STATE) {
    if (detail.includes(prefix)) return state
  }
  return undefined
}

/** FastAPI 的 422 把 detail 返成数组 [{loc, msg, type}]，直接渲染会得到 [object Object]。 */
function normalizeDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String(item.msg) : ''))
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  return '请求失败'
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
  override?: Response,
): Promise<T> {
  const resp = override ?? (await fetch(path, init))
  if (!resp.ok) {
    let detail: unknown = resp.statusText
    try {
      const body = await resp.json()
      detail = (body as { detail?: unknown }).detail ?? detail
    } catch {
      /* 非 JSON 响应，保留 statusText */
    }
    const bizState = (resp.headers.get('X-Anomaly-Biz-State') as BizState | null)
      ?? stateFromDetail(normalizeDetail(detail))
    throw new ApiError(resp.status, normalizeDetail(detail), bizState ?? undefined)
  }
  return (await resp.json()) as T
}

export function postJson<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/api/client.test.ts
```

Expected: PASS，6 个用例全绿

- [ ] **Step 5: 写 `types.ts`**

手写类型。**必须逐字段对齐后端实际响应** —— 字段名不许改。

下面这份是照着后端实际响应写出来的（`reports/latest/report.json` 与各端点实测）：

```ts
// —— /api/platform/catalog ——
export interface CatalogSource { id: number; name: string; kind: string; path: string; created_at: string }
export interface CatalogMetric {
  id: number; source_id: number; name: string; query: string
  time_column: string; value_column: string; group_column: string | null
  time_format: string; freq: string; source_timezone: string; missing_policy: string
  created_at: string
}
export interface CatalogJob {
  id: number; metric_id: number; name: string; detector: string
  alert_threshold: number; critical_threshold: number
  window_points: number; interval_seconds: number; enabled: boolean
  last_run_at: string | null; next_run_at: string | null; created_at: string
  alert_rules: AlertRule[]
}
export interface CatalogDetector {
  name: string; default_threshold: number; score_type: string; label: string
}
export interface Catalog {
  sources: CatalogSource[]; metrics: CatalogMetric[]; jobs: CatalogJob[]; detectors: CatalogDetector[]
}

// —— 告警规则 ——
export interface AlertRule {
  multiplier?: number       // 倍数条件（缩放因子）
  op?: string               // 绝对值条件：> >= < <=
  value?: number            // 绝对值条件的阈值
  level: string             // 正常 / P1 / P0
}

// —— 运行记录 ——
export type RunStatus = 'running' | 'success' | 'failed' | 'insufficient_data'
export interface RunSummary {
  id: number; job_id: number; status: RunStatus
  n_series: number; n_alerts: number; error: string | null
  started_at: string; finished_at: string | null
}

// —— 预览 ——
export interface SeriesEntry {
  series_id: string; group: string | null
  n: number; n_valid: number; n_missing: number
  n_alerts: number; n_p0: number
  sufficient: boolean; detector: string; metric_class: string | null
  fallback: boolean; file: string | null
}
export interface Preview {
  run_id: number; job_id: number
  detector: string; requested_detector: string
  metric_class: string; detector_rationale: string; detector_fallback: boolean
  score_type: string
  series_id: string; group: string | null
  n: number; n_valid: number; n_missing: number
  n_alerts: number; n_p0: number
  sufficient: boolean; insufficient_reason: string
  sampled: boolean; original_n: number
  timestamps: string[]
  values: (number | null)[]
  scores: (number | null)[]
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  severity: number[]
  alert_threshold: number; critical_threshold: number
  alert_rules: AlertRule[]
  levels: string[]
  series: SeriesEntry[]
}

// —— 多算法对比 ——
export interface CompareDetector {
  name: string; score_type: string; default_threshold: number
  baseline: (number | null)[]; lower: (number | null)[]; upper: (number | null)[]
  scores: (number | null)[]; severity: number[]
  n_alerts: number
  /** 最高档上的告警**点数**（不是档位序号）：n_top = (severity == top_level).sum() */
  n_top: number
  is_auto: boolean
}
export interface Compare {
  job_id: number; series_id: string; group: string | null
  n: number; sampled: boolean; original_n: number
  timestamps: string[]; values: (number | null)[]
  /** ⚠️ 可为 null：分类器对点数不足的序列给不出形态 */
  metric_class: string | null
  /** ⚠️ 可为 null：点数不足 30 时给不出置信度 */
  confidence: number | null
  reasons: string[]
  recommendation: { detectors: string[]; rationale: string }
  auto_detector: string; auto_fallback: boolean; auto_rationale: string
  available: string[]
  detectors: CompareDetector[]
  levels: string[]; alert_rules: AlertRule[]; band_width: number
}

// —— 反馈（注意字段是 start_ts / end_ts，不是 start / end）——
export type FeedbackKind = 'correct' | 'false_alarm' | 'missed' | 'other'
export interface FeedbackRecord {
  id: number
  job_id: number
  run_id: number | null
  series_id: string
  start_ts: string
  end_ts: string
  kind: FeedbackKind
  note: string
  created_at: string
}
export interface FeedbackList { feedback: FeedbackRecord[] }
export interface Suggestion {
  /** ⚠️ 可为 null：任务还没有运行记录时后端返回 null */
  run_id: number | null
  evaluated_detectors: string[]
  current_detector: string; suggested_detector: string; detector_changed: boolean
  current_multiplier: number; suggested_multiplier: number; reason: string
  current: unknown | null; best: unknown | null; candidates: unknown[]
}

// —— 序列 / 评估 / 标注 ——
export interface SeriesMeta { series_id: string; metric_class: string; n: number; n_anomalies: number }
export interface SeriesValues {
  series_id: string; timestamps: string[]; values: number[]; labels: number[]
}
export interface EvaluationRow {
  series_id: string; metric_class: string; detector: string
  score_type: string; threshold: number
  precision: number; recall: number; f1: number; range_f1: number
  n_truth: number; n_pred: number; elapsed_ms: number
}
export interface EvalBucket {
  n_series: number; n_truth: number; n_pred: number
  precision: number; recall: number; f1: number; range_f1: number; elapsed_ms: number
}
export interface Summary {
  generated_at: string | null; title: string
  summary: {
    overall?: EvalBucket
    by_detector?: Record<string, EvalBucket>
    by_metric_class?: Record<string, EvalBucket>
  }
  rows: EvaluationRow[]
}
export interface Badcase {
  kind: string; group: string; reason: string; indices: number[]
}
export interface Badcases {
  series_id: string; detector: string; threshold: number; score_type: string
  timestamps: string[]; values: number[]; scores: number[]; badcases: Badcase[]
}
export interface Annotation {
  series_id: string; start: number; end: number; type: string; created_at: string
}
export interface AnnotationList { series_id: string; intervals: Annotation[] }
```

**验收点**：对照后端实际响应逐字段核对（`reports/latest/report.json` 的 `rows` 有 **12** 个字段、
`summary` 有 `overall`/`by_detector`/`by_metric_class` 三个键）。**任何字段名对不上都要改这里。**

- [ ] **Step 6: 提交**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/api/types.ts
git commit -m "feat(frontend): API 客户端与手写类型（422 归一化 + 业务态响应头）"
```

---

### Task 4: 端点封装层

**Files:**
- Create: `frontend/src/api/platform.ts`
- Create: `frontend/src/api/series.ts`
- Create: `frontend/src/api/annotate.ts`

**规则**：`api/*.ts` 只做「一个端点一个函数」，**不碰 React**（这样可脱离 React 单测）。
⚠️ `noUnusedLocals` 开着 —— **import 的每个类型都要用上**。

- [ ] **Step 1: 写 `api/platform.ts`**

13 个 `/api/platform/*` 端点，一函数一个：

```ts
import { request, postJson } from './client'
import type {
  AlertRule, Catalog, Compare, FeedbackList, Preview, RunSummary, Suggestion,
} from './types'

export const getCatalog = () => request<Catalog>('/api/platform/catalog')

export const createSource = (payload: { name: string; path: string; kind?: string }) =>
  postJson<{ id: number }>('/api/platform/sources', payload)

export const createMetric = (payload: {
  source_id: number; name: string; query: string
  time_column: string; value_column: string; group_column?: string | null
  time_format?: string; freq?: string; source_timezone?: string; missing_policy?: string
}) => postJson<{ id: number }>('/api/platform/metrics', payload)

export const createJob = (payload: {
  metric_id: number; name: string; detector?: string
  alert_threshold?: number; critical_threshold?: number
  window_points?: number; interval_seconds?: number; enabled?: boolean
  alert_rules?: AlertRule[] | null
}) => postJson<{ id: number }>('/api/platform/jobs', payload)

/** PATCH 只支持 enabled 与 detector —— 告警规则**不能**自由编辑（spec §8.3）。 */
export const toggleJob = (jobId: number, payload: { enabled?: boolean; detector?: string }) =>
  request<unknown>(`/api/platform/jobs/${jobId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

export const runJob = (jobId: number) => postJson<{ run_id: number }>(`/api/platform/jobs/${jobId}/run`, {})

export const getRuns = (jobId: number) => request<{ runs: RunSummary[] }>(`/api/platform/jobs/${jobId}/runs`)

export const getPreview = (jobId: number, opts: { runId?: number; seriesId?: string } = {}) => {
  const params = new URLSearchParams()
  if (opts.runId !== undefined) params.set('run_id', String(opts.runId))
  if (opts.seriesId) params.set('series_id', opts.seriesId)
  const qs = params.toString()
  return request<Preview>(`/api/platform/jobs/${jobId}/preview${qs ? `?${qs}` : ''}`)
}

export const getCompare = (jobId: number, opts: { seriesId?: string; detectors?: string[] } = {}) => {
  const params = new URLSearchParams()
  if (opts.seriesId) params.set('series_id', opts.seriesId)
  if (opts.detectors?.length) params.set('detectors', opts.detectors.join(','))
  const qs = params.toString()
  return request<Compare>(`/api/platform/jobs/${jobId}/compare${qs ? `?${qs}` : ''}`)
}

/**
 * 提交反馈。
 * ⚠️ POST 端点是 `/api/platform/feedback`（**与任务无关**），
 * 不是 `/api/platform/jobs/{id}/feedback` —— 后者只注册了 GET。
 * ⚠️ 字段是 start_ts / end_ts（不是 start / end），且必须带 job_id。
 */
export const createFeedback = (payload: {
  job_id: number
  series_id: string
  start_ts: string
  end_ts: string
  kind: string
  note?: string
  run_id?: number | null
}) => postJson<{ id: number }>('/api/platform/feedback', payload)

export const getFeedback = (jobId: number) =>
  request<FeedbackList>(`/api/platform/jobs/${jobId}/feedback`)

export const getSuggestion = (jobId: number, runId?: number) => {
  const qs = runId === undefined ? '' : `?run_id=${runId}`
  return request<Suggestion>(`/api/platform/jobs/${jobId}/feedback/suggestion${qs}`)
}

export const applySuggestion = (jobId: number, payload: { multiplier: number; detector?: string }) =>
  postJson<unknown>(`/api/platform/jobs/${jobId}/apply-suggestion`, payload)
```

- [ ] **Step 2: 写 `api/series.ts`**

```ts
import { request } from './client'
import type { Badcases, SeriesMeta, SeriesValues, Summary } from './types'

export const getSeries = () => request<SeriesMeta[]>('/api/series')
export const getSeriesValues = (seriesId: string) =>
  request<SeriesValues>(`/api/series/${encodeURIComponent(seriesId)}/values`)
export const getSummary = () => request<Summary>('/api/summary')
export const getBadcases = (seriesId: string) =>
  request<Badcases>(`/api/badcases?series_id=${encodeURIComponent(seriesId)}`)
```

- [ ] **Step 3: 写 `api/annotate.ts`**

```ts
import { request, postJson } from './client'
import type { AnnotationList } from './types'

export const getAnnotations = (seriesId: string) =>
  request<AnnotationList>(`/api/annotate/${encodeURIComponent(seriesId)}`)

export const saveAnnotations = (seriesId: string, intervals: { start: number; end: number; type: string }[]) =>
  postJson<{ saved: number; path: string }>(`/api/annotate/${encodeURIComponent(seriesId)}`, { intervals })
```

- [ ] **Step 4: 验证端点清单与后端一致**

```bash
grep -oE '@router\.(get|post|patch)\("([^"]+)"' src/anomaly_lab/web/platform_routes.py
grep -oE '@app\.(get|post|patch)\("([^"]+)"' src/anomaly_lab/web/app.py
```

把列出的路径与 `api/*.ts` 里的函数**逐条对齐**。

⚠️ 不要写死「13 + 5」这种计数：`platform_routes.py` 里除了 13 个 API 还有 1 个
`/platform` HTML 路由（Chunk 6 才删），`app.py` 里除了 API 还有 3 个 HTML 路由。
**按路径逐条核对，不按数量核对。**

已知对应关系（写完对照一遍）：

| 后端路径 | 方法 | 前端函数 |
|---|---|---|
| `/api/platform/catalog` | GET | `getCatalog` |
| `/api/platform/sources` | POST | `createSource` |
| `/api/platform/metrics` | POST | `createMetric` |
| `/api/platform/jobs` | POST | `createJob` |
| `/api/platform/jobs/{id}` | PATCH | `toggleJob` |
| `/api/platform/jobs/{id}/run` | POST | `runJob` |
| `/api/platform/jobs/{id}/runs` | GET | `getRuns` |
| `/api/platform/jobs/{id}/preview` | GET | `getPreview` |
| `/api/platform/jobs/{id}/compare` | GET | `getCompare` |
| `/api/platform/feedback` | POST | `createFeedback` |
| `/api/platform/jobs/{id}/feedback` | GET | `getFeedback` |
| `/api/platform/jobs/{id}/feedback/suggestion` | GET | `getSuggestion` |
| `/api/platform/jobs/{id}/apply-suggestion` | POST | `applySuggestion` |
| `/api/series` | GET | `getSeries` |
| `/api/series/{id}/values` | GET | `getSeriesValues` |
| `/api/summary` | GET | `getSummary` |
| `/api/badcases` | GET | `getBadcases` |
| `/api/annotate/{id}` | GET/POST | `getAnnotations` / `saveAnnotations` |

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/platform.ts frontend/src/api/series.ts frontend/src/api/annotate.ts
git commit -m "feat(frontend): 端点封装层（一函数一端点，不碰 React）"
```

---

### Task 5: 应用骨架 —— QueryClient / Router / Layout / StateBoundary

**Files:**
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/router.tsx`
- Create: `frontend/src/components/AppLayout.tsx`
- Create: `frontend/src/components/StateBoundary.tsx`
- Create: `frontend/src/pages/Placeholder.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: 写 `AppLayout.tsx`**

侧边栏 + 内容区。导航项固定 7 条（**不含「告警」** —— spec §8.3 明确告警中心不在本次范围）：

```tsx
const NAV = [
  { to: '/',          label: '序列总览' },
  { to: '/sources',   label: '数据源' },
  { to: '/metrics',   label: '指标' },
  { to: '/jobs',      label: '检测任务' },
  { to: '/evaluation',label: '评估报告' },
  { to: '/badcases',  label: 'Bad Case' },
  { to: '/annotate',  label: '标注' },
]
```

侧边栏底色用 `var(--surface-panel)`，激活项用 `var(--accent)`。

- [ ] **Step 2: 写 `StateBoundary.tsx`**

五态封装（spec §6.1）。**这是前端最重要的抽象** —— 所有数据视图都必须经过它。

⚠️ **`bizState` 必须在这里被消费** —— 后端加 `X-Anomaly-Biz-State` 响应头（Task 17）
的全部意义就在于此：业务态要走空态/数据不足态，**不能显示红色错误框**。

```tsx
import { Alert, Skeleton } from 'antd'
import type { ReactNode } from 'react'
import { ApiError, type BizState } from '../api/client'

export interface StateBoundaryProps<T> {
  isLoading: boolean
  error: unknown
  data: T | undefined
  /** 数据为空时的判定；返回 false 说明有数据 */
  isEmpty?: (data: T) => boolean
  emptyTitle?: string
  emptyHint?: string
  /** 空态按钮（如「立即运行」） */
  emptyAction?: ReactNode
  /** 数据不足态：返回原因字符串则进入「数据不足」态（不是错误态） */
  insufficient?: (data: T) => string | null
  /** 业务态（bizState）对应的空态标题；缺省用统一文案 */
  bizTitles?: Partial<Record<BizState, string>>
  children: (data: T) => ReactNode
}

/** 业务态 → 默认空态标题 */
const BIZ_DEFAULT_TITLES: Record<BizState, string> = {
  no_run: '该任务还没有运行记录',
  no_series: '该次运行没有序列结果',
  no_data: '该窗口内没有取到数据',
  insufficient_data: '数据不足',
  no_algorithms: '没有可对比的算法',
  no_result: '还没有可查看的 Bad Case',
}

export function StateBoundary<T>(props: StateBoundaryProps<T>) {
  const {
    isLoading, error, data, isEmpty, emptyTitle, emptyHint, emptyAction,
    insufficient, bizTitles, children,
  } = props

  if (isLoading) return <Skeleton active paragraph={{ rows: 6 }} />

  if (error) {
    const apiErr = error instanceof ApiError ? error : null
    const biz = apiErr?.bizState
    if (biz === 'insufficient_data') {
      // 数据不足是业务态，不是错误态 —— 用 warning 而不是 error
      return <Alert type="warning" showIcon message="数据不足" description={apiErr?.message} />
    }
    if (biz) {
      const title = bizTitles?.[biz] ?? BIZ_DEFAULT_TITLES[biz]
      return (
        <div className="empty-state">
          <p className="empty-title">{title}</p>
          {/* ⚠️ 后端的 detail 文案常常与标题一字不差（如 no_run），
              重复渲染会出现两个同样的文本 —— 相同时只渲染标题。 */}
          {apiErr?.message && apiErr.message !== title && (
            <p className="muted">{apiErr.message}</p>
          )}
          {emptyAction}
        </div>
      )
    }
    return <ErrorPanel error={error} />
  }

  if (data === undefined) return null

  const reason = insufficient?.(data)
  if (reason) {
    return <Alert type="warning" showIcon message="数据不足" description={reason} />
  }

  if (isEmpty?.(data)) {
    return (
      <div className="empty-state">
        <p className="empty-title">{emptyTitle ?? '暂无数据'}</p>
        {emptyHint && <p className="muted">{emptyHint}</p>}
        {emptyAction}
      </div>
    )
  }

  return <>{children(data)}</>
}

function ErrorPanel({ error }: { error: unknown }) {
  const message = error instanceof ApiError ? error.message : '请求失败'
  const status = error instanceof ApiError ? error.status : undefined
  return (
    <Alert
      type="error"
      showIcon
      message={status ? `请求失败（HTTP ${status}）` : '请求失败'}
      description={message}
    />
  )
}
```

- [ ] **Step 3: 写 `router.tsx` 与 `App.tsx`**

路由表（8 个页面，路径与 spec §8.2-A 一致）：

```
/            → 序列总览
/sources     → 数据源
/metrics     → 指标
/jobs        → 任务列表
/jobs/:jobId → 任务详情
/evaluation  → 评估报告
/badcases    → Bad Case
/annotate    → 标注
```

`App.tsx` 里套 `QueryClientProvider` → `ConfigProvider`（theme token 从 `tokens.css` 读）→ `BrowserRouter` → `AppLayout` + `Routes`。

**AntD theme token 的映射**（spec §5）：

```tsx
const theme = {
  token: {
    colorPrimary: 'var(--accent)',
    colorSuccess: 'var(--status-normal)',
    colorWarning: 'var(--status-p1)',
    colorError: 'var(--status-p0)',
    colorBgBase: 'var(--surface-canvas)',
    colorBgContainer: 'var(--surface-panel)',
    colorBorder: 'var(--border-subtle)',
    colorText: 'var(--text-primary)',
    colorTextSecondary: 'var(--text-secondary)',
    fontFamily: 'var(--font-sans)',
    borderRadius: 'var(--radius-md)',
  },
}
```

> 若 AntD 不接受 CSS 变量作为色值（部分版本会做颜色运算而报错），改为在运行时用
> `getComputedStyle(document.documentElement).getPropertyValue('--accent')` 读出实际色值再传。
> **先试变量，不行再改读法。**

- [ ] **Step 4: 写 `Placeholder.tsx` 并挂上路由**

每个路由先指向 `Placeholder`，Task 7 起逐个替换成真页面。

- [ ] **Step 5: 验证**

```bash
cd frontend && npm run build && npm run test
```

Expected: build 通过（**无 TS6133 未使用 import 报错**）；vitest 全绿（此时只有 client 的 5 个用例）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/App.tsx frontend/src/router.tsx frontend/src/components/AppLayout.tsx \
        frontend/src/components/StateBoundary.tsx frontend/src/pages/Placeholder.tsx \
        frontend/src/main.tsx
git commit -m "feat(frontend): 应用骨架（QueryClient + Router + 侧边栏 + 五态边界）"
```

---

## Chunk 2: 五态验证 + 序列总览 + 任务列表

### Task 6: StateBoundary 单测

**Files:**
- Test: `frontend/src/components/StateBoundary.test.tsx`

- [ ] **Step 1: 写失败的测试**

覆盖 5 种状态 **+ 业务态（bizState）**：

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { StateBoundary } from './StateBoundary'

const data = { ok: true }

describe('StateBoundary', () => {
  it('加载中显示骨架屏', () => {
    const { container } = render(
      <StateBoundary isLoading error={undefined} data={undefined}>{() => <div>内容</div>}</StateBoundary>,
    )
    expect(container.querySelector('.ant-skeleton')).toBeTruthy()
  })

  it('真错误显示 detail 原文（红色）', () => {
    render(
      <StateBoundary isLoading={false} error={new ApiError(500, '数据库锁住了')} data={undefined}>
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('数据库锁住了')).toBeTruthy()
    expect(screen.queryByText('数据不足')).toBeNull()
  })

  it('bizState=insufficient_data 显示警告而不是错误', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '序列 x 有效点仅 12 个，不足以做检测', 'insufficient_data')}
        data={undefined}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('数据不足')).toBeTruthy()
    expect(screen.getByText('序列 x 有效点仅 12 个，不足以做检测')).toBeTruthy()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('bizState=no_run 显示空态而不是红色错误框', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '该任务还没有运行记录', 'no_run')}
        data={undefined}
        emptyAction={<button>立即运行</button>}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('该任务还没有运行记录')).toBeTruthy()
    expect(screen.getByText('立即运行')).toBeTruthy()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('bizState 文案与标题相同时不重复渲染', () => {
    // 后端 no_run 的 detail 就是「该任务还没有运行记录」，
    // 与默认标题一字不差 —— 渲染两遍会出现「Found multiple elements」
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(404, '该任务还没有运行记录', 'no_run')}
        data={undefined}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getAllByText('该任务还没有运行记录')).toHaveLength(1)
  })

  it('bizState=no_algorithms 显示对应空态标题', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={new ApiError(400, '没有可对比的算法', 'no_algorithms')}
        data={undefined}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('没有可对比的算法')).toBeTruthy()
    expect(screen.queryByText(/请求失败/)).toBeNull()
  })

  it('响应体里的 sufficient=false 也进数据不足态', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={undefined}
        data={data}
        insufficient={() => '有效点仅 12 个，不足以做检测'}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('数据不足')).toBeTruthy()
    expect(screen.getByText('有效点仅 12 个，不足以做检测')).toBeTruthy()
    expect(screen.queryByText('内容')).toBeNull()
  })

  it('空态显示标题与按钮', () => {
    render(
      <StateBoundary
        isLoading={false}
        error={undefined}
        data={data}
        isEmpty={() => true}
        emptyTitle="还没有检测任务"
        emptyAction={<button>新建任务</button>}
      >
        {() => <div>内容</div>}
      </StateBoundary>,
    )
    expect(screen.getByText('还没有检测任务')).toBeTruthy()
    expect(screen.getByText('新建任务')).toBeTruthy()
  })

  it('有数据时渲染 children', () => {
    render(
      <StateBoundary isLoading={false} error={undefined} data={data}>{() => <div>内容</div>}</StateBoundary>,
    )
    expect(screen.getByText('内容')).toBeTruthy()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/StateBoundary.test.tsx
```

Expected: FAIL（组件还没写完或断言不对）

- [ ] **Step 3: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/components/StateBoundary.test.tsx
```

Expected: PASS，9 个用例

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/StateBoundary.test.tsx
git commit -m "test(frontend): StateBoundary 五态 + 业务态单测"
```

---

### Task 7: 序列总览页

**Files:**
- Create: `frontend/src/features/series/queries.ts`
- Create: `frontend/src/features/series/SeriesOverview.tsx`
- Create: `frontend/src/pages/SeriesOverviewPage.tsx`
- Modify: `frontend/src/router.tsx`

- [ ] **Step 1: 写 `features/series/queries.ts`**

TanStack Query hooks 的标准写法（后续每个域都照抄这个形状）：

```ts
import { useQuery } from '@tanstack/react-query'
import { getSeries } from '../../api/series'

export const seriesKey = ['series'] as const

export function useSeries() {
  return useQuery({ queryKey: seriesKey, queryFn: getSeries })
}
```

⚠️ **不要** import `SeriesMeta` —— 这里用不到，`noUnusedLocals` 会报 TS6133 让 build 失败。

- [ ] **Step 2: 写 `SeriesOverview.tsx`**

用 `StateBoundary` 包住，用 AntD `Table` 渲染。列：`series_id` / `metric_class` / `n` / `n_anomalies`。
空态：「还没有可分析的序列」+「先运行 make generate 生成合成数据」。

- [ ] **Step 3: 写页面并接路由**

`pages/SeriesOverviewPage.tsx` 是薄壳，只调 hook 传给 feature 组件。

- [ ] **Step 4: 验证**

```bash
cd frontend && npm run build && npm run test
```

手动验证：起后端 `make serve`，前端 `cd frontend && npm run dev`，访问 `http://127.0.0.1:5173/` 应看到序列列表。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/series frontend/src/pages/SeriesOverviewPage.tsx frontend/src/router.tsx
git commit -m "feat(frontend): 序列总览页"
```

---

### Task 8: 任务列表页 + 新建任务表单

**Files:**
- Create: `frontend/src/features/jobs/queries.ts`
- Create: `frontend/src/features/jobs/JobList.tsx`
- Create: `frontend/src/features/jobs/JobForm.tsx`
- Create: `frontend/src/features/jobs/AlertRulesInput.tsx`
- Create: `frontend/src/pages/JobsPage.tsx`
- Modify: `frontend/src/router.tsx`

**这个表单是 spec §8.2-A 里最容易漏的几条旧功能的落点**：

| 旧功能 | 实现要求 |
|---|---|
| 倍数条件 | `2.5, P1` |
| **绝对值条件** | `>50, P0` / `>=50` / `<10` / `<=10` —— 解析正则 `^(>=\|<=\|>\|<)\s*(-?\d+(\.\d+)?)$` |
| **倍数必须为正** | `multiplier <= 0` 是非法输入（后端 `parse_rules` 会拒），前端要**当场拦下并给行内错误**，不要等 422 |
| 规则语义说明 | 提示文案：**顺序即档位顺序**（最后一行最严重）、**命中多条取最高档**、留空用默认两档 |
| **选算法自动预填默认规则** | 选算法 → 规则框填 `${default_threshold}, P1\n${(default_threshold*1.5).toFixed(2)}, P0` |

- [ ] **Step 1: 写 `features/jobs/queries.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createJob, getCatalog, runJob, toggleJob } from '../../api/platform'
import type { CatalogJob } from '../../api/types'

export const catalogKey = ['catalog'] as const

export function useCatalog() {
  return useQuery({ queryKey: catalogKey, queryFn: getCatalog })
}

/** 「立即运行」是同步的：检测在请求内跑完才返回。所以用 mutation 的 loading 态，不轮询。 */
export function useRunJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) => runJob(jobId),
    onSuccess: (_data, jobId) => {
      void qc.invalidateQueries({ queryKey: catalogKey })          // last_run_at / next_run_at 变了
      void qc.invalidateQueries({ queryKey: ['runs', jobId] })
      void qc.invalidateQueries({ queryKey: ['preview', jobId] })
      void qc.invalidateQueries({ queryKey: ['suggestion', jobId] })
    },
  })
}

export function useToggleJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, payload }: { jobId: number; payload: { enabled?: boolean; detector?: string } }) =>
      toggleJob(jobId, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: catalogKey }),
  })
}

export function useCreateJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof createJob>[0]) => createJob(payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: catalogKey }),
  })
}

export function jobMetricName(job: CatalogJob, metricNameById: Map<number, string>): string {
  return metricNameById.get(job.metric_id) ?? String(job.metric_id)
}
```

- [ ] **Step 2: 写 `AlertRulesInput.tsx`**

契约：

```tsx
export interface AlertRulesInputProps {
  value: AlertRule[]
  onChange: (rules: AlertRule[]) => void
}
```

内部维护**纯文本**（每行 `条件, 等级`），解析成 `AlertRule[]`。解析规则：

- 行内逗号后的部分拼回等级（沿用旧 `platform.js` 的 `rest.join(',')` 行为）
- 条件匹配绝对值正则 → `{ op, value, level }`
- 否则 `Number(条件)`；**必须 `> 0`**，否则该行标为非法
- 非法行 → 显示行内错误文案，**不静默丢弃**
- 留空 → 返回 `null`（后端用默认两档）

非法行的错误文案示例：「第 2 行：倍数必须大于 0」/「第 1 行：格式应为「倍数, 等级」或「>50, 等级」」。

- [ ] **Step 3: 写 `JobForm.tsx`**

字段：指标（select）、名称、算法（select）、窗口点数、执行间隔、告警规则（`AlertRulesInput`）。

**选算法时自动预填**：

```tsx
const onDetectorChange = (name: string) => {
  const det = detectors.find((d) => d.name === name)
  if (!det) return
  const base = det.default_threshold
  setRulesText(`${base}, P1\n${(base * 1.5).toFixed(2)}, P0`)
}
```

规则说明文案（照搬旧 `platform.html` 的语义）：

> **从上到下按严重程度排列**（最后一行最严重），命中多条时取最高档。
> 倍数条件是主判定；`>50` 这类绝对值条件并行生效，只能抬高等级、不会压低分数判定。
> 留空则用默认两档（缩放因子 2.5 → P1，3.75 → P0）。

- [ ] **Step 4: 写 `JobList.tsx` 与页面**

表格列：ID / 名称 / 指标 / 算法（`auto` 显示「自动推荐」）/ 告警规则 / 间隔 / 状态（启用/停用）/ 操作（立即运行、启停）。

规则格式化函数（照搬旧 `platform.js` 的 `formatRules`）：

```ts
export function formatRules(rules: AlertRule[] | null | undefined): string {
  if (!rules?.length) return '-'
  return rules
    .map((r) => (r.multiplier == null ? `${r.op}${r.value}` : `${r.multiplier}×`) + `→${r.level}`)
    .join(' / ')
}
```

- [ ] **Step 5: 验证**

手动：新建任务 → 选算法 → 规则自动预填 → 填一个 `0, P1` 看是否被拦 → 保存 → 列表出现新任务 →
立即运行 → 状态刷新。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/features/jobs frontend/src/pages/JobsPage.tsx frontend/src/router.tsx
git commit -m "feat(frontend): 任务列表页与新建任务表单（含告警规则编辑）"
```

---

## Chunk 3: 任务详情 —— 预览与多算法对比

### Task 9: 预览图表

**Files:**
- Create: `frontend/src/features/jobs/PreviewChart.tsx`
- Create: `frontend/src/features/jobs/PreviewPanel.tsx`
- Create: `frontend/src/pages/JobDetailPage.tsx`
- Test: `frontend/src/features/jobs/PreviewChart.test.tsx`
- Modify: `frontend/src/features/jobs/queries.ts`

- [ ] **Step 1: 加 preview / runs / compare 的 hooks**

`features/jobs/queries.ts` 追加（**query key 必须与 spec §7.1 一致**）：

⚠️ 同时要**补 import**：`getPreview`、`getRuns`、`getCompare` 来自 `../../api/platform`，
`useQuery` 来自 `@tanstack/react-query`（Task 8 已经引了 `useQuery`，这里只需加前三个）。

```ts
export function usePreview(jobId: number, runId?: number, seriesId?: string) {
  return useQuery({
    queryKey: ['preview', jobId, runId, seriesId],
    queryFn: () => getPreview(jobId, { runId, seriesId }),
    enabled: jobId > 0,
  })
}

export function useRuns(jobId: number) {
  return useQuery({
    queryKey: ['runs', jobId],
    queryFn: () => getRuns(jobId),
    enabled: jobId > 0,
    // 只在有 run 处于 running 时继续轮询；空闲时停（spec §7.3）
    refetchInterval: (query) => {
      const runs = query.state.data?.runs ?? []
      return runs.some((r) => r.status === 'running') ? 3000 : false
    },
  })
}

export function useCompare(jobId: number, seriesId?: string, detectors?: string[]) {
  return useQuery({
    queryKey: ['compare', jobId, seriesId, detectors],
    queryFn: () => getCompare(jobId, { seriesId, detectors }),
    enabled: jobId > 0,
  })
}
```

- [ ] **Step 2: 写 `PreviewChart.tsx`**

契约：

```tsx
export interface PreviewChartProps {
  timestamps: string[]
  values: (number | null)[]
  scores: (number | null)[]
  baseline: (number | null)[] | null
  lower: (number | null)[] | null
  upper: (number | null)[] | null
  severity: number[]
  alertThreshold: number
  criticalThreshold: number
  levels: string[]
}
```

图表构成（`echarts-for-react` 的 `ReactECharts`）：

| 系列 | 类型 | 说明 |
|---|---|---|
| 上下界带 | `line` + `stack: 'band'` | `lower` 用透明、`upper` 用 `var(--status-normal)` 半透明 |
| 基线 | `line` | 虚线，`var(--text-secondary)` |
| 实际值 | `line` | `var(--text-primary)` |
| 分数 | `line` + `yAxisIndex: 1` | **新增**（旧预览图没有） |
| 阈值线 | `markLine` | `alertThreshold` / `criticalThreshold` 两条虚线 |
| 告警点 | `scatter` | 按 `severity` 分 0/1/2 三色 + 点大小分级 |

**必须处理的三种边界**（spec §6.1 + §8.2-A）：

1. **`baseline` / `lower` / `upper` 为 `null`**（该算法没有基线带）→ **不画带**，图上给一句说明「该算法未提供基线带」
2. **`values` 里有 `null`**（缺点）→ **断线**（ECharts 默认 `connectNulls: false`），不要连起来
3. 数组里的 `null` 直接传给 ECharts（ECharts 认 `null` 表示缺点）

`dataZoom`：**`inside` + `slider` 都要有**（旧版有，迁移时最容易丢）。

颜色全部从 `tokens.css` 的变量取（`var(--status-p0)` 等）。

- [ ] **Step 3: 写 `PreviewChart.test.tsx`**

spec §9 明确要求覆盖「数据不足 / 无基线带 / 有缺失点」三种行为：

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PreviewChart, buildPreviewOption } from './PreviewChart'

const base = {
  timestamps: ['2026-10-27T22:49:00', '2026-10-27T22:54:00', '2026-10-27T22:59:00'],
  values: [1, 2, 3] as (number | null)[],
  scores: [0.1, 0.2, 0.3] as (number | null)[],
  baseline: [1, 2, 3] as (number | null)[],
  lower: [0, 1, 2] as (number | null)[],
  upper: [2, 3, 4] as (number | null)[],
  severity: [0, 0, 0],
  alertThreshold: 2.5,
  criticalThreshold: 4,
  levels: ['正常', 'P1', 'P0'],
}

describe('PreviewChart', () => {
  it('没有基线带时给出说明而不是空图', () => {
    render(<PreviewChart {...base} baseline={null} lower={null} upper={null} />)
    expect(screen.getByText(/未提供基线带/)).toBeTruthy()
  })

  it('缺点在图上表现为断线（connectNulls 不开）', () => {
    const option = buildPreviewOption({ ...base, values: [1, null, 3] })
    const series = option.series as Array<{ name?: string; connectNulls?: boolean }>
    const valueSeries = series.find((s) => s.name === '数值')
    expect(valueSeries).toBeTruthy()
    expect(valueSeries!.connectNulls).not.toBe(true)
  })
})
```

> 为此要把 ECharts option 的构造抽成**导出的纯函数** `buildPreviewOption(props)`，
> 组件只负责 `ReactECharts option={buildPreviewOption(props)}`。这样才能单测。
> （顺带这条也让「缺点断线」这种行为可验证，而不是只能肉眼看图。）
>
> **返回类型要显式收窄**：`buildPreviewOption` 的返回类型写成
> `{ series: Array<{ name?: string; connectNulls?: boolean }> }`（或给 `series` 收窄成数组），
> 否则 `option.series.find(...)` 会在 `strict` 下报
> `TS2339: Property 'find' does not exist on type 'SeriesOption | SeriesOption[]'`。

- [ ] **Step 4: 写 `PreviewPanel.tsx`**

把 preview 数据 + 图表 + 「已抽样 N/M」提示 + 数据不足态组装起来。

**数据不足态的关键**（spec §4.2.1）：preview 的数据不足是 **200 + `sufficient:false`**，
不是 404。所以 `StateBoundary` 的 `insufficient` 回调这样写：

```tsx
insufficient={(p) => (p.sufficient ? null : p.insufficient_reason || '有效点不足，不足以做检测')}
```

「已抽样 N/M」提示：后端在 `sampled: true` 时把点数降到 `MAX_PREVIEW_POINTS=2000`，
响应里有 `original_n`。提示文案：`已抽样 ${n}/${original_n} 点`。

**「立即运行」按钮**：preview 返回 `no_run` 业务态时，`StateBoundary` 的 `emptyAction` 要给这个按钮。

- [ ] **Step 5: 写页面并接路由**

`/jobs/:jobId` → `JobDetailPage`，读 `useParams()` 的 `jobId`，传给 feature 组件。

- [ ] **Step 6: 验证**

```bash
cd frontend && npm run test && npm run build
```

手动：访问 `/jobs/1`，确认图表画出基线带、告警点分 P1/P0 两色、缩放滑块在、缺点断线。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/features/jobs frontend/src/pages/JobDetailPage.tsx frontend/src/router.tsx
git commit -m "feat(frontend): 任务详情预览图表（基线带 + 告警点 + 分数副轴）"
```

---

### Task 10: 运行记录 + 序列切换

**Files:**
- Create: `frontend/src/features/jobs/RunsView.tsx`

- [ ] **Step 1: 写 `RunsView.tsx`**

契约：

```tsx
export interface RunsViewProps {
  runs: RunSummary[]
  selectedRunId: number | undefined
  onSelect: (runId: number) => void
}
```

显示文案照搬旧 `platform.js` 的 `loadRuns`：

```
#${r.id} ${r.status} (${r.n_series} 序列 / ${r.n_alerts} 告警)
```

失败时追加 ` · ${r.error.slice(0, 40)}`。

用 AntD `Select`（不是原生的下拉）。

- [ ] **Step 2: 序列下拉**

文案照搬旧 `platform.js`：

```ts
`${s.series_id} (${s.sufficient === false ? '数据不足' : `${s.n_alerts} 告警`})`
```

⚠️ 旧 UI **没有 P0 数**，P0 数是新增项（spec §8.2-C）—— 这一版先不加，别混淆。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/features/jobs/RunsView.tsx
git commit -m "feat(frontend): 运行记录与序列切换"
```

---

### Task 11: 多算法对比（图 + 表 + 勾选组）

**Files:**
- Create: `frontend/src/features/jobs/ComparePicker.tsx`
- Create: `frontend/src/features/jobs/CompareChart.tsx`
- Create: `frontend/src/features/jobs/CompareTable.tsx`

- [ ] **Step 1: 写 `ComparePicker.tsx`**

契约：

```tsx
export interface ComparePickerProps {
  /** 后端给的候选算法；为空时要回退到 detectors 的名字列表 */
  available: string[]
  fallbackNames: string[]
  autoDetector: string
  selected: string[]
  onChange: (selected: string[]) => void
}
```

候选列表**必须有回退**（照搬旧 `platform.js:312-314`）：

```ts
const names = available.length ? available : fallbackNames
```

否则 `available` 为空时勾选组会渲染成空的。

默认勾选规则照搬旧 `platform.js`：

```ts
input.checked = previous.length
  ? previous.includes(name)
  : names.length <= 4 || name === autoDetector
```

即：**候选 ≤4 个时全勾，否则只勾 auto**。

- [ ] **Step 2: 写 `CompareChart.tsx`**

把各算法的**基线与告警点叠在同一张图**上（这是旧版 `renderCompareChart` 的行为，别漏）。
每个算法一条基线线 + 一组告警散点，颜色按算法区分（从 `tokens.css` 的 `--series-1..5` 取）。

同样把 option 构造抽成导出的纯函数 `buildCompareOption(props)`，便于单测。

- [ ] **Step 3: 写 `CompareTable.tsx`**

列（照搬旧 `platform.js` 的 `renderCompareTable`）：

| 列 | 来源 |
|---|---|
| 算法 | `name` |
| 自动推荐 | `is_auto` → 「✓ 自动推荐」 |
| 告警数 | `n_alerts` |
| **最高档** | **档位名** = `levels[Math.max(...severity)]`（如 `P0`） |
| **最高档点数** | `n_top` = 最高档上的告警**点数**（后端已算好） |
| 最高分 | `max(scores)` —— ⚠️ **必须过滤 `null`**，否则 `Math.max` 得到 `NaN` |
| **惯用倍数** | `default_threshold` |
| 操作 | 「设为任务算法」按钮 |

⚠️ **`n_top` 是点数，不是档位序号** —— 后端算的是
`n_top = int((severity == top_level).sum())`（`platform/compare.py`）。
用 `levels[n_top]` 会得到 `undefined`（实测 `n_top` 是 7/10/6 这种数）。
旧 UI 的「最高档」列显示的其实就是这个点数（列名与内容不符），
新实现拆成「最高档」（档位名）与「最高档点数」（点数）两列。

「惯用倍数」这一列**不能省** —— spec §8.2-A 与 `PLATFORM.md` 都强调它是解读差异的参照。

最高档与最高分的正确写法：

```ts
const topSeverity = severity.length ? Math.max(...severity) : 0
const topLevel = levels[topSeverity] ?? '-'
const maxScore = scores.reduce<number | null>(
  (acc, s) => (s == null ? acc : acc == null ? s : Math.max(acc, s)),
  null,
)
```

「设为任务算法」→ `useToggleJob({ jobId, payload: { detector: name } })`。

- [ ] **Step 4: 验证**

手动：勾选/取消算法 → 表格与图同步变化；点「设为任务算法」→ 任务列表里的算法变了。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/features/jobs/ComparePicker.tsx frontend/src/features/jobs/CompareChart.tsx frontend/src/features/jobs/CompareTable.tsx
git commit -m "feat(frontend): 多算法对比（勾选组 + 叠加图 + 对比表）"
```

---

### Task 12: 分类结论 + 告警规则只读展示

**Files:**
- Create: `frontend/src/features/jobs/ClassificationCard.tsx`
- Create: `frontend/src/features/jobs/AlertRulesView.tsx`

- [ ] **Step 1: 写 `ClassificationCard.tsx`**

契约：

```tsx
export interface ClassificationCardProps {
  metricClass: string
  confidence: number
  reasons: string[]
  autoDetector: string
  autoRationale: string
  autoFallback: boolean
  scoreType: string
}
```

内容：形态（周期型/平稳型/…）+ 置信度 + 理由列表 + 自动推荐的算法 + 推荐理由 + 是否回退。

这是旧 UI 那句 `自动 → 检测器 · 形态（回退）· score_type · 规则` 的正式化（spec §8.2-A）。

- [ ] **Step 2: 写 `AlertRulesView.tsx`**

**只读**展示（spec §8.3：没有自由编辑规则的端点）。用 `formatRules` 渲染规则列表。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/features/jobs/ClassificationCard.tsx frontend/src/features/jobs/AlertRulesView.tsx
git commit -m "feat(frontend): 形态分类结论与告警规则只读展示"
```

---

## Chunk 4: 反馈闭环

### Task 13: 反馈面板 + 历史

**Files:**
- Create: `frontend/src/features/jobs/FeedbackPanel.tsx`
- Create: `frontend/src/features/jobs/FeedbackHistory.tsx`
- Modify: `frontend/src/features/jobs/queries.ts`

- [ ] **Step 1: 加反馈相关的 hooks**

⚠️ 同时要**补 import**：`getFeedback`、`getSuggestion`、`createFeedback`、`applySuggestion`
来自 `../../api/platform`；`useQueryClient` 来自 `@tanstack/react-query`。

```ts
export function useFeedback(jobId: number) {
  return useQuery({
    queryKey: ['feedback', jobId],
    queryFn: () => getFeedback(jobId),
    enabled: jobId > 0,
  })
}

export function useSuggestion(jobId: number, runId?: number) {
  return useQuery({
    queryKey: ['suggestion', jobId, runId],
    queryFn: () => getSuggestion(jobId, runId),
    enabled: jobId > 0,
  })
}

export function useCreateFeedback() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Parameters<typeof createFeedback>[0]) => createFeedback(payload),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['feedback', vars.job_id] })
      void qc.invalidateQueries({ queryKey: ['suggestion', vars.job_id] })
    },
  })
}

export function useApplySuggestion(jobId: number) {
  const qc = useQueryClient()
  return useMutation({
    // ⚠️ 不能写 `Parameters<typeof applySuggestion>[0]` —— applySuggestion 有两个参数
    // （jobId, payload），`[0]` 取到的是 jobId，类型直接对不上。
    mutationFn: (payload: { multiplier: number; detector?: string }) =>
      applySuggestion(jobId, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: catalogKey })        // 任务配置变了
      void qc.invalidateQueries({ queryKey: ['suggestion', jobId] })
      void qc.invalidateQueries({ queryKey: ['compare', jobId] }) // compare 响应带当前 alert_rules / band_width
    },
  })
}
```

⚠️ `['compare', jobId]` 的失效不能省 —— compare 的响应里带**当前**的 `alert_rules` 与
`band_width`，不刷新就会拿旧倍数解读对比结果（spec §7.2）。

- [ ] **Step 2: 写 `FeedbackPanel.tsx`**

表单字段：序列（默认当前序列）、开始时间、结束时间、类型（漏报/误报/正确/其他）、备注。

⚠️ **提交时字段名是 `start_ts` / `end_ts`，且必须带 `job_id`**（后端 `FeedbackIn` 要求）：

```ts
await createFeedback({
  job_id: jobId,
  series_id: seriesId.trim(),
  start_ts: start.trim(),
  end_ts: end.trim(),
  kind,
  note: note.trim(),
})
```

「评估并给建议」→ 读 `useSuggestion` 的结果。
「一键应用」→ `useApplySuggestion({ multiplier: suggestion.suggested_multiplier })`。

**建议结果的展示**：`reason` 字段是后端给的中文说明，直接显示；
`suggested_multiplier` 与 `current_multiplier` 不同时高亮差异。

- [ ] **Step 3: 写 `FeedbackHistory.tsx`**

表格列：ID / 序列 / 时间范围（`start_ts` ~ `end_ts`）/ 类型 / 备注。数据来自 `useFeedback`。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/features/jobs
git commit -m "feat(frontend): 反馈闭环（提交 + 历史 + 建议 + 一键应用）"
```

---

## Chunk 5: 其余页面

### Task 14: 数据源页 + 指标页

**Files:**
- Create: `frontend/src/features/sources/SourcesPage.tsx`
- Create: `frontend/src/features/metrics/MetricsPage.tsx`
- Create: `frontend/src/features/metrics/MetricForm.tsx`
- Modify: `frontend/src/router.tsx`

- [ ] **Step 1: 数据源页**

字段：名称、路径、类型（默认 sqlite）。列表列：ID / 名称 / 类型 / 路径。

- [ ] **Step 2: 指标页**

字段（照搬旧 `platform.html` 的全部字段，**一个都不能少**）：

| 字段 | 说明 |
|---|---|
| 数据源 | select |
| 名称 | |
| 时间列 | 默认 `ts` |
| 值列 | 默认 `value` |
| 分组列 | 可空（group by 拆序列） |
| 时间格式 | `iso_utc` / `iso_naive` / `epoch_s` / `epoch_ms` |
| 源时区 | 默认 `UTC` |
| 缺失值策略 | `drop` / `interpolate` / `error` |
| 频率 | 默认 `5min` |
| 查询语句 | textarea，默认 `SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts` |

⚠️ **`$timefilter` 是后端的占位符**，前端只原样提交，不要替换成实际时间范围。

列表列：ID / 名称 / 数据源 / 分组列 / 频率。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/features/sources frontend/src/features/metrics frontend/src/router.tsx
git commit -m "feat(frontend): 数据源页与指标页"
```

---

### Task 15: 标注页

**Files:**
- Create: `frontend/src/features/annotate/queries.ts`
- Create: `frontend/src/features/annotate/AnnotatePage.tsx`
- Modify: `frontend/src/router.tsx`

- [ ] **Step 1: 写 `features/annotate/queries.ts`**

补上 spec §7.1 里缺的 key 与 hook：

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAnnotations, saveAnnotations } from '../../api/annotate'
import { getSeriesValues } from '../../api/series'

export function useSeriesValues(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['seriesValues', seriesId],
    queryFn: () => getSeriesValues(seriesId!),
    enabled: Boolean(seriesId),
  })
}

export function useAnnotations(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['annotations', seriesId],
    queryFn: () => getAnnotations(seriesId!),
    enabled: Boolean(seriesId),
  })
}

export function useSaveAnnotations(seriesId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (intervals: { start: number; end: number; type: string }[]) =>
      saveAnnotations(seriesId!, intervals),
    onSuccess: () => {
      // 保存标注 → 失效 ['annotations', seriesId]（spec §7.2）
      void qc.invalidateQueries({ queryKey: ['annotations', seriesId] })
    },
  })
}
```

- [ ] **Step 2: 写标注页**

流程：选序列 → `useSeriesValues` 拉波形 → `useAnnotations` 拉已有标注 → ECharts 画波形 → 刷选区间 →
选异常类型（**下拉，不是 `prompt()`**）→ `useSaveAnnotations` 保存。

异常类型固定 6 种（照搬旧 `annotate.js:61` 的提示文案）：

```
spike / contextual / drift / freq_shift / variance_shift / flatline
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/features/annotate frontend/src/router.tsx
git commit -m "feat(frontend): 标注页（刷选 + 类型下拉）"
```

---

### Task 16: 评估报告页 + Bad Case 页

**Files:**
- Create: `frontend/src/features/evaluation/queries.ts`
- Create: `frontend/src/features/evaluation/EvaluationPage.tsx`
- Create: `frontend/src/features/evaluation/BadcasesPage.tsx`
- Modify: `frontend/src/router.tsx`

- [ ] **Step 1: 写 `features/evaluation/queries.ts`**

补上 spec §7.1 里缺的 key 与 hook：

```ts
import { useQuery } from '@tanstack/react-query'
import { getBadcases, getSummary } from '../../api/series'

export function useSummary() {
  return useQuery({ queryKey: ['summary'], queryFn: getSummary })
}

export function useBadcases(seriesId: string | undefined) {
  return useQuery({
    queryKey: ['badcases', seriesId],
    queryFn: () => getBadcases(seriesId!),
    enabled: Boolean(seriesId),
  })
}
```

- [ ] **Step 2: 评估报告页**

表格列（照搬旧 `report.js` 的 9 列，**一列都不能少**）：

```
序列 / 形态 / 检测器 / Precision / Recall / F1 / Range-F1 / 真值点 / 预测点
```

总体行显示 `summary.overall` 的 precision/recall/f1/range_f1。
无报告时显示「暂无报告，请先运行 evaluate」。

- [ ] **Step 3: Bad Case 页**

两栏：左侧序列列表（从 `useSummary()` 的 rows 取），右侧详情图（`useBadcases(seriesId)`）。

详情图要有：数值线 + 分数线 + 阈值线，**并且用 `badcases[].indices` 真正画出异常区间**。

⚠️ 旧版这里有 bug：`markArea: data.badcases && data.badcases.length ? {} : undefined` ——
空对象 markArea 等于没画，异常区间从来没显示过（spec §8.2-B）。新实现必须用 `indices` 画出区间。

**「该序列还没有检测结果」是业务态**（`no_result`）→ 用 `StateBoundary` 的 `bizState` 路径显示空态，
不是红色错误框。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/features/evaluation frontend/src/router.tsx
git commit -m "feat(frontend): 评估报告页与 Bad Case 页（修正异常区间未绘制）"
```

---

## Chunk 6: 后端改造 + 旧前端退役

### Task 17: 业务态响应头

**Files:**
- Modify: `src/anomaly_lab/web/platform_routes.py`
- Modify: `src/anomaly_lab/web/app.py`
- Test: `tests/web/test_biz_state.py`
- Test: `tests/web/conftest.py`（新增：共享 fixture）

- [ ] **Step 1: 写共享 fixture**

`tests/web/conftest.py`：

```python
from pathlib import Path

import pytest

from anomaly_lab.platform.store import PlatformStore


@pytest.fixture
def store_with_job(tmp_path: Path) -> PlatformStore:
    """一个含数据源 / 指标 / 任务的 store（任务**没有运行记录**）。

    ⚠️ store 的方法名是 `add_source` / `add_metric` / `add_job`（不是 create_*），
    且 `add_metric` / `add_job` 的参数**全是关键字参数**。
    """
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    store.add_job(
        metric_id=metric.id,
        name="j",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=60,
    )
    return store


@pytest.fixture
def make_dist(tmp_path: Path):
    """造一个假的 frontend/dist，供 SPA 路由测试用。"""

    def _make() -> Path:
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text(
            "<!doctype html><html><body>根</body></html>", encoding="utf-8"
        )
        (dist / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
        return dist

    return _make
```

> `make_dist` fixture 用来造假的 `frontend/dist`，供 SPA 路由测试用。
> 上面 `store_with_job` 的写法照抄 `tests/platform/test_insufficient_data.py` 的建店代码 ——
> 那是最新、最可靠的参考。

- [ ] **Step 2: 写失败的测试**

⚠️ **关键**：三个业务态 404 分支的**可达条件各不相同**，不能用同一个请求去断言。

| 分支 | 可达条件 | 请求 |
|---|---|---|
| `no_run` | 任务**存在**但没有运行记录 | `GET /api/platform/jobs/{存在的 job_id}/preview` |
| `no_result` | 序列**存在**但没有检测结果 | `GET /api/badcases?series_id={存在的序列}` |
| 「序列不存在」 | 序列**不在数据集里** → **真错误**，不加头 | `GET /api/badcases?series_id=不存在的序列` |

`tests/web/test_biz_state.py`：

```python
import anomaly_lab.web.app as webapp
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_preview_no_run_has_biz_state_header(store_with_job):
    job_id = store_with_job.list_jobs()[0].id
    client = TestClient(create_app(platform_store=store_with_job))
    resp = client.get(f"/api/platform/jobs/{job_id}/preview")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") == "no_run"


def test_preview_unknown_job_is_a_real_error_without_biz_state(store_with_job):
    client = TestClient(create_app(platform_store=store_with_job))
    resp = client.get("/api/platform/jobs/999999/preview")
    assert resp.status_code == 404
    # 「任务不存在: 999999」是参数错误，不该带业务态头
    assert resp.headers.get("X-Anomaly-Biz-State") is None


def test_badcases_unknown_series_is_a_real_error_without_biz_state():
    client = TestClient(create_app())
    resp = client.get("/api/badcases?series_id=根本不存在的序列")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") is None


def test_badcases_existing_series_without_results_has_biz_state_header(monkeypatch, tmp_path):
    """序列存在但没有检测结果 → 业务态，不是错误。

    用 monkeypatch 把检测目录指向空目录，让「序列存在但无 .npz」这个条件
    **不依赖本机缓存状态**（实测数据集 120 条序列全都有 iqr 检测结果，
    直接用真实缓存测不到这个分支）。
    """
    monkeypatch.setattr(webapp, "_detections_root", lambda: tmp_path)
    client = TestClient(create_app())
    resp = client.get("/api/badcases?series_id=stationary-42-500")
    assert resp.status_code == 404
    assert resp.headers.get("X-Anomaly-Biz-State") == "no_result"
```

> `stationary-42-500` 是合成数据里的第一条序列，**换数据集时要同步换**。
> 更稳的写法是从 `GET /api/series` 取第一条，但那样要多一次请求；
> 先用固定 id，跑不通再改成动态取。

- [ ] **Step 3: 跑测试确认失败**

```bash
.venv/bin/python -m pytest tests/web/test_biz_state.py -v
```

Expected: FAIL —— 没有响应头

- [ ] **Step 4: 加响应头**

在 `platform_routes.py` 的 4 处 + `app.py` 的 1 处业务态 404 上加 `headers=`：

```python
raise HTTPException(
    status_code=404,
    detail="该任务还没有运行记录",
    headers={"X-Anomaly-Biz-State": "no_run"},
)
```

对照表（**逐条核对 spec §4.2.1**，行号按 v3 时为准）：

| 文件 | detail | state |
|---|---|---|
| `platform_routes.py` | 该任务还没有运行记录 | `no_run` |
| `platform_routes.py` | 该次运行没有序列结果 | `no_series` |
| `platform_routes.py` | 该窗口内没有取到数据 | `no_data` |
| `platform_routes.py` | 序列 X 有效点仅 N 个，不足以做检测 | `insufficient_data` |
| `platform_routes.py` | 没有可对比的算法（**400**） | `no_algorithms` |
| `app.py` | 该序列还没有检测结果 | `no_result` |

**不要**给这些加头（它们是真错误）：
「序列不存在」、「序列不存在: X」、「当前倍数无效」、「倍数必须为正数」、
以及 store 的 `ValueError` 原文（如「任务不存在: 999」）。

> 准确清单可以自己 grep 出来核对：
> `grep -rhn 'detail="' src/anomaly_lab/web/platform_routes.py src/anomaly_lab/web/app.py | sed 's/.*detail="\(.*\)".*/\1/' | sort -u`
> （f-string 的两条要单独看：`序列不存在: {series_id}` 与 `序列 … 有效点仅 …`）

- [ ] **Step 5: 跑测试确认通过**

```bash
.venv/bin/python -m pytest tests/web/test_biz_state.py -v
```

Expected: PASS

- [ ] **Step 6: 跑全量测试确认没打破别的**

```bash
.venv/bin/python -m pytest
```

Expected: 全部通过（数量 = 268 + 新增）

- [ ] **Step 7: 提交**

```bash
git add src/anomaly_lab/web/platform_routes.py src/anomaly_lab/web/app.py \
        tests/web/test_biz_state.py tests/web/conftest.py
git commit -m "feat(web): 业务态 404 加 X-Anomaly-Biz-State 响应头（JSON 结构不变）"
```

---

### Task 18: SPA 托管与 fallback

**Files:**
- Modify: `src/anomaly_lab/web/app.py`
- Test: `tests/web/test_spa.py`

- [ ] **Step 1: 写失败的测试**

`tests/web/test_spa.py`：

```python
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_spa_route_returns_index_html(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/jobs/1")
    assert resp.status_code == 200
    assert "根" in resp.text


def test_unknown_api_path_returns_404_json(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/api/typo")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


def test_asset_file_is_served(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_missing_dist_returns_503_without_crashing(tmp_path):
    client = TestClient(create_app(frontend_dist=tmp_path / "不存在"))
    resp = client.get("/jobs/1")
    assert resp.status_code == 503
    assert "make frontend-build" in resp.text


def test_existing_api_still_works(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    assert client.get("/api/health").json() == {"status": "ok"}


def test_path_traversal_cannot_escape_dist(tmp_path, make_dist):
    """⚠️ 安全回归：catch-all 不能变成任意文件读取。

    `dist / '../secret.txt'` 会指向 dist 外的文件；百分号编码的 %2f
    不会被 httpx 规范化掉，会原样到达 Starlette。
    """
    (tmp_path / "secret.txt").write_text("SECRET-CONTENT", encoding="utf-8")
    client = TestClient(create_app(frontend_dist=make_dist()))
    for path in ("/..%2fsecret.txt", "/%2e%2e/secret.txt"):
        resp = client.get(path)
        assert "SECRET-CONTENT" not in resp.text
        # 应该回退到 index.html
        assert resp.status_code == 200
        assert "根" in resp.text
```

- [ ] **Step 2: 跑测试确认失败**

```bash
.venv/bin/python -m pytest tests/web/test_spa.py -v
```

Expected: FAIL —— `create_app()` 不接受 `frontend_dist`

- [ ] **Step 3: 实现**

`app.py` 顶部加一个定位函数：

```python
def _find_frontend_dist() -> Path | None:
    """从本文件向上找 frontend/dist。

    比写死 parents[3] 稳 —— wheel 安装下 parents[3] 指向 site-packages。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "frontend" / "dist"
        if candidate.is_dir():
            return candidate
    return None
```

`create_app` 签名加参数：

```python
def create_app(
    platform_store: PlatformStore | None = None,
    platform_data_root: Path | None = None,
    start_scheduler: bool = False,
    frontend_dist: Path | None = None,
) -> FastAPI:
```

`dist` 解析与挂载 —— **加在 `create_app` 的最末尾**（所有 `/api/*` 路由之后）：

```python
    dist = frontend_dist if frontend_dist is not None else _find_frontend_dist()
    has_dist = dist is not None and dist.is_dir()
    assets_dir = dist / "assets" if has_dist else None

    # /assets 只在目录存在时挂载。
    # ⚠️ 不要用 check_dir=False 当安全网：starlette 1.10.0 只跳过构造期检查，
    # 首次请求时 check_config() 仍会抛 RuntimeError。
    if assets_dir is not None and assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # 拼错的 API 不该拿到 HTML
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if not has_dist:
            raise HTTPException(
                status_code=503,
                detail="前端未构建，请先执行 make frontend-build",
            )
        # ⚠️ 安全：必须把 target 限制在 dist 之内。
        # 直接 `dist / full_path` 会形成**任意文件读取**：
        # `GET /..%2fsecret.txt` → full_path='../secret.txt' → dist/../secret.txt 存在 → 读出 dist 外的内容。
        # （字面量 '..' 会被 httpx 规范化掉，但百分号编码的 %2f 会原样到达 Starlette。）
        target = (dist / full_path).resolve()
        if full_path and target.is_file() and target.is_relative_to(dist.resolve()):
            return FileResponse(target)
        return FileResponse(dist / "index.html")
```

⚠️ **三条顺序硬约束**：

1. catch-all 必须注册在**所有** `/api/*` 路由之后（Starlette 按注册顺序匹配）。
   当前 `app.py` 里 `app.include_router(build_router(...))` 在第 98 行、各 `@app.*` API 路由在
   106~205 行 —— catch-all 追加在 `create_app` 末尾即可。
2. catch-all 必须在**现有 `/static` 挂载之后**（那个挂载在 **Task 19** 才删 —— 注意不是 Task 20）。
3. **不要** `app.mount("/", ...)` —— `Mount("/")` 的路径正则 `^/(?P<path>.*)$` 会 FULL 匹配一切路径，
   注册在它之后的 catch-all 永远不会被命中（spec §4.2 B4）。

import 需要加 `from fastapi.responses import FileResponse`。

⚠️ **`api/` 前缀的判断要在 503 判断之前** —— 否则 dist 缺失时 `/api/typo` 会返回 503 而不是 404。

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python -m pytest tests/web/test_spa.py -v
```

Expected: PASS，6 个用例（含路径穿越回归）

- [ ] **Step 5: 跑全量测试**

```bash
.venv/bin/python -m pytest
```

Expected: **全绿**。旧的 `test_index_page_loads` / `test_report_page_loads` 这时**仍然通过** ——
因为 HTML 路由还没删（Task 20 才删），它们命中的还是 Jinja 路由。
Task 20 删路由后它们才会失败，Task 21 负责改写。

- [ ] **Step 6: 提交**

```bash
git add src/anomaly_lab/web/app.py tests/web/test_spa.py
git commit -m "feat(web): SPA 托管与 fallback（条件挂载 /assets + catch-all）"
```

---

### Task 19: 退役旧前端

**Files:**
- Delete: `src/anomaly_lab/web/templates/base.html`
- Delete: `src/anomaly_lab/web/templates/index.html`
- Delete: `src/anomaly_lab/web/templates/annotate.html`
- Delete: `src/anomaly_lab/web/templates/report.html`
- Delete: `src/anomaly_lab/web/templates/platform.html`
- Delete: `src/anomaly_lab/web/static/annotate.js`
- Delete: `src/anomaly_lab/web/static/platform.js`
- Delete: `src/anomaly_lab/web/static/report.js`
- Delete: `src/anomaly_lab/web/static/style.css`
- Delete: `src/anomaly_lab/web/static/echarts.min.js`
- Modify: `src/anomaly_lab/web/app.py`
- Modify: `src/anomaly_lab/web/platform_routes.py`

- [ ] **Step 1: 删 4 个 HTML 路由**

`app.py`：删 `/`、`/annotate`、`/report` 三个路由。
`platform_routes.py`：删 `/platform` 路由（**它在 `platform_routes.py:142`，不在 `app.py`**）。

- [ ] **Step 2: 清理失效 import**

`app.py`：`HTMLResponse`、`Request`、`Jinja2Templates`、模块级 `_TEMPLATES` —— 全部失效，删掉
（ruff 的 F401 会报）。

`platform_routes.py`：`HTMLResponse`、`Request`、以及 `platform_routes.py:144` 那句
**函数内延迟 import** `from anomaly_lab.web.app import _TEMPLATES`（本是为绕循环依赖而写，
路由没了它自然消失；之后 `platform_routes.py` 不再依赖 `app.py`）。

- [ ] **Step 3: 删 `/static` 挂载 + `static/` 目录**

`app.py` 删掉 `app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")`。

⚠️ **必须与 Step 1/2 同一次提交** —— 目录先删、挂载还在，`create_app()` 会抛
`RuntimeError: Directory does not exist`，**12 处 `create_app()` 调用全部失败**
（`cli.py:518` + `tests/` 里 11 处）。

- [ ] **Step 4: 删 `templates/` 与 `static/` 目录**

```bash
git rm -r src/anomaly_lab/web/templates src/anomaly_lab/web/static
```

- [ ] **Step 5: 验证**

```bash
.venv/bin/python -m ruff check src tests
```

Expected: ruff 全绿

```bash
.venv/bin/python -m pytest
```

Expected: **只有 2 个旧 HTML 页面测试失败**（`test_index_page_loads` / `test_report_page_loads`
现在命中 catch-all，dist 不存在 → 503）。这是预期的，Task 21 改写。

- [ ] **Step 6: 提交**

```bash
git add src/anomaly_lab/web/app.py src/anomaly_lab/web/platform_routes.py
git add -u src/anomaly_lab/web/templates src/anomaly_lab/web/static
git commit -m "refactor(web): 退役旧前端（Jinja 模板 + 命令式 JS + /static 挂载）"
```

---

### Task 20: 改写旧的 HTML 页面测试

**Files:**
- Modify: `tests/web/test_app.py`
- Modify: `tests/web/test_report_page.py`

⚠️ **必须在 Task 19 之后** —— HTML 路由删掉后，这两个测试命中的才是 SPA catch-all。

- [ ] **Step 1: 读现有测试**

```bash
cat tests/web/test_app.py tests/web/test_report_page.py
```

- [ ] **Step 2: 改写**

两个测试断言的是「旧 Jinja 页面能返回」。路由已删、页面由 SPA 提供，所以改成断言 SPA 行为：

`tests/web/test_app.py`：

```python
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_index_serves_spa(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "根" in resp.text


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/api/health").json() == {"status": "ok"}
```

`tests/web/test_report_page.py`：

```python
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_report_route_serves_spa(make_dist):
    client = TestClient(create_app(frontend_dist=make_dist()))
    resp = client.get("/report")
    assert resp.status_code == 200
    assert "根" in resp.text


def test_api_summary_returns_rows():
    client = TestClient(create_app())
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    assert "rows" in resp.json()
```

`make_dist` fixture 来自 `tests/web/conftest.py`（Task 17 已建）。

**不要删掉这两个文件** —— 它们仍要验证「`/` 与 `/report` 由 SPA 提供」。

- [ ] **Step 3: 跑全量测试**

```bash
.venv/bin/python -m pytest
```

Expected: **全绿**

- [ ] **Step 4: 提交**

```bash
git add tests/web/test_app.py tests/web/test_report_page.py
git commit -m "test(web): 旧 HTML 页面测试改写为 SPA 行为断言"
```

---

### Task 21: Makefile 与 CI

**Files:**
- Modify: `Makefile`
- Modify: `pyproject.toml`（可选：去掉 `jinja2`）

- [ ] **Step 1: 加 4 个 Makefile 目标**

```makefile
NPM ?= npm

.PHONY: frontend-install frontend-build dev

frontend-install:
	cd frontend && $(NPM) ci

frontend-build:
	cd frontend && $(NPM) run build

# dev：vite 与 uvicorn 两个进程并行。
#
# ⚠️ 两个坑：
#  1. vite 必须在**子 shell** 里 cd —— 否则外层 shell 的 cwd 停在 frontend/，
#     而 CONFIG.data_dir = Path("data") 是相对 cwd 的，服务器会去读 frontend/data/。
#  2. `&` 起的后台任务要**杀整个进程组** —— 只 kill $! 杀的是 npm 的 wrapper，
#     真正的 node vite 子进程会活下来占着 5173 端口。
#     `set -m` 让后台任务自成一个进程组，然后 `kill -- -$$VPID` 整组收掉。
dev:
	@set -m; \
	(cd frontend && $(NPM) run dev -- --port 5173) & \
	VPID=$$!; \
	trap 'kill -- -$$VPID 2>/dev/null || true' EXIT INT TERM; \
	$(PY) -m anomaly_lab.cli serve --port 8000
```

把 `serve` 改成依赖前端构建：

```makefile
serve: frontend-build
	$(PY) -m anomaly_lab.cli serve --port 8000
```

- [ ] **Step 2: 验证**

```bash
make frontend-install
make frontend-build
ls frontend/dist/index.html
```

Expected: 产物存在

```bash
make serve
```

Expected: 打开 `http://127.0.0.1:8000/` 是 SPA；刷新 `http://127.0.0.1:8000/jobs/1` 不 404。

另外确认 cwd 没跑偏、以及 vite 没被漏掉：

```bash
make dev
# 在另一个终端：ls / 应该有 repo 根的 data/ 与 reports/，而不是 frontend/data/
# Ctrl-C 后：lsof -i :5173 应该没有输出（vite 已被整组收掉）
```

- [ ] **Step 3: 去掉 jinja2 依赖（可选）**

`pyproject.toml` 里删掉 `jinja2`，然后：

```bash
uv pip install -e . --index-url https://pypi.tuna.tsinghua.edu.cn/simple
.venv/bin/python -m pytest
```

- [ ] **Step 4: 提交**

```bash
git add Makefile pyproject.toml
git commit -m "build: Makefile 增加前端目标（install/build/dev/serve）"
```

---

### Task 22: 后端类型漂移守卫

**Files:**
- Test: `tests/web/test_api_contract.py`

spec §9 要求「断言关键响应字段存在」来防手写 `types.ts` 漂移（决策 D6 的代价补偿）。

- [ ] **Step 1: 写测试**

```python
"""API 契约守卫：前端 types.ts 是手写的，后端字段变了这里要红。"""
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_catalog_contract():
    client = TestClient(create_app())
    body = client.get("/api/platform/catalog").json()
    for key in ("sources", "metrics", "jobs", "detectors"):
        assert key in body
    # ⚠️ detectors **没有 id** —— 它是按 name 索引的字典，不是表记录
    for key in ("name", "default_threshold", "score_type", "label"):
        assert key in body["detectors"][0]
    for key in ("id", "name", "kind", "path", "created_at"):
        assert key in body["sources"][0]


def test_series_contract():
    client = TestClient(create_app())
    body = client.get("/api/series").json()
    if not body:
        return  # 没有数据集时跳过
    for key in ("series_id", "metric_class", "n", "n_anomalies"):
        assert key in body[0]


def test_summary_contract():
    client = TestClient(create_app())
    body = client.get("/api/summary").json()
    assert "rows" in body
    assert "summary" in body
    if body["rows"]:
        for key in (
            "series_id", "metric_class", "detector", "score_type", "threshold",
            "precision", "recall", "f1", "range_f1", "n_truth", "n_pred", "elapsed_ms",
        ):
            assert key in body["rows"][0]


def test_annotate_contract():
    client = TestClient(create_app())
    body = client.get("/api/annotate/任意序列").json()
    assert "series_id" in body
    assert "intervals" in body
```

> `reports/latest/report.json` 不一定存在（CI 上可能没有），所以 `test_summary_contract`
> 在 `rows` 为空时只断言顶层键。`/api/series` 在没有数据集时返回 `[]`，此时跳过字段断言。

- [ ] **Step 2: 跑测试**

```bash
.venv/bin/python -m pytest tests/web/test_api_contract.py -v
```

Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tests/web/test_api_contract.py
git commit -m "test(web): API 契约守卫（防手写 types.ts 漂移）"
```

---

### Task 23: 收尾文档

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/PLATFORM.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/DESIGN.md`（**需用户确认后再动**）

- [ ] **Step 1: 问用户是否要改 `docs/DESIGN.md`**

`docs/DESIGN.md` 有用户自己的未提交改动。spec §12 F1 要求改写 D8 / ADR-6
（「不再引入 React/Vue/构建链」→「前端为独立 React+TS+Vite 工程……」）。
**先问用户，得到许可再动。** 未获许可时只做 F2~F4。

- [ ] **Step 2: 更新 `docs/ARCHITECTURE.md` 的 Web 章节**

反映新结构：前端是 `frontend/` 独立工程；后端只出 JSON API；`make dev` / `make serve` 的用法。

- [ ] **Step 3: 更新 `docs/PLATFORM.md`**

补一节「Web 前端」：工程结构、五态处理、颜色单一来源、`make dev`。

- [ ] **Step 4: 更新 `docs/ROADMAP.md`**

记录：「前端已迁移为独立 React 工程」「告警中心列入以后做」「最小窗口提示 + freq 校验列入以后做」。

- [ ] **Step 5: 提交**

```bash
git add docs/ARCHITECTURE.md docs/PLATFORM.md docs/ROADMAP.md
git commit -m "docs: 同步前端分离后的架构与平台文档"
```

---

## 收尾验收（对照 spec §10）

- [ ] `make dev` / `make serve` 一条命令起全栈
- [ ] spec §8.2-A 功能对照表**全表逐条打勾**
- [ ] spec §8.2-B 的 **6 个**问题全部消失
- [ ] `GET /jobs/1` → 200；`GET /api/typo` → 404 JSON；`GET /assets/<真实文件>` → 200
- [ ] 仓库里不再有两套前端（`templates/`、`static/` 已删）
- [ ] `pytest` / `vitest` / `ruff` 全绿
- [ ] 「数据不足」在 preview（200 路径）与 compare（404 路径）**都**正确呈现
- [ ] 图表 P0 红点与表格 P0 徽标**同色**
- [ ] dist 不存在时 `create_app()` 不崩溃，返回 503
- [ ] 迁移全程旧页面可用

```bash
# 全量验证
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests
cd frontend && npm run test && npm run build
grep -rn "alert(\|prompt(" frontend/src || echo "✓ 无 alert/prompt"
```
