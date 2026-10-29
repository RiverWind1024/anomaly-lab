# 前端重构：前后端分离的检测控制台

- 日期：2026-10-30
- 状态：设计已确认（第 3 稿，已过两轮 spec review），待实施
- 相关文档：[ARCHITECTURE.md](../../ARCHITECTURE.md) · [PLATFORM.md](../../PLATFORM.md) · [DESIGN.md](../../DESIGN.md) · [PITFALLS.md](../../PITFALLS.md)

> **修订记录**
> - **第 2 稿**：修正第 1 稿 7 处与代码现实不符的阻塞项（SPA fallback 挂载方式、「增删」实际不存在、告警规则无编辑端点、`static/` 与 `dist/` 缺失会炸 `create_app()`、`/platform` 路由真实位置、422 的 `detail` 是数组、业务态用 404 + 文案表达、CORS 与 dev proxy 矛盾）。逐条见 §15-A。
> - **第 3 稿**：修正第 2 稿 3 处新阻塞（`check_dir=False` 在 starlette 1.10.0 上无效、两个旧 HTML 页面测试会与 503 语义冲突、import 清理清单不完整），并补齐 8 处遗漏（`/api/series/{id}/values` 漏出 API 层与 query key、两条失效规则缺失、业务态 404 实为 5 条、功能对照表漏 4 项旧功能与 2 项旧 bug、评估表漏 3 列、`make dev` 无可执行细节）。逐条见 §15-B。

---

## 1. 背景：为什么要推翻 D8

`docs/DESIGN.md` 的 **D8 / ADR-6** 写着：「FastAPI + 单页 HTML + ECharts，不引前端框架」，
理由是「前端只需画波形 + 刷选区间 + 看表格，引入构建链是纯负担」。

这个判断在项目只有「标注页 + 评估页」时是对的。现在平台的 Web 端已经长成：

- **648 行**命令式 JS（`platform.js` 512 + `annotate.js` 77 + `report.js` 59）
- 全部靠 `innerHTML` 拼字符串渲染，**没有组件边界**
- **全局可变状态**（`let chart; let catalog = {...}`）+ 手写 DOM 事件绑定
- 错误处理只有 `alert()`（platform.js 里 6 处）；`annotate.js` 还用 `prompt()`，
  且**完全没有错误处理**（fetch 不看 `resp.ok`）；**`report.js` 完全没有错误处理** ——
  `/api/badcases` 404 时 `if (!data.scores) return;` 静默失败
- 平台页已经有 5 个 section（数据源 / 指标 / 任务 / 预览+多算法对比 / 反馈闭环），
  其中「多算法对比」和「反馈→建议→一键应用」已经是完整业务闭环

**「画波形 + 看表格」这个范围描述已经过期了。** 后端也已从「输出 JSON」变成
「实时跑检测、算基线带、跑分类器、对比多算法、给调参建议」——前端要呈现的东西
本质上是一个**运维控制台**，不是几个只读页面。

因此本次推翻 D8，改为**前后端分离的独立前端工程**。代价（`node_modules` ~200MB、
多一条构建链、ADR 要改写）在本项目的收益面前可以接受。

---

## 2. 目标与非目标

### 目标

1. 前端成为**独立工程**：后端只出 JSON API，前端独立构建、独立演进
2. **功能等价迁移**：现有 4 个页面的全部功能在新技术栈下不丢（逐条对照见 §8.2）
3. 把「状态处理」补齐：五态齐全（见 §6.1），消灭 `alert()` / `prompt()` / 静默失败
4. 建立**单一视觉来源**：design system → CSS 变量 → AntD token + ECharts 配色
5. 保持「一条命令起全栈」的开发体验，**不引入跨域与多进程部署负担**

### 非目标（明确不做）

- 用户体系与权限
- SSR / SSG / 微前端
- 主题切换（暗色或浅色二选一）
- 国际化
- WebSocket 实时推送（轮询足够）
- 前端埋点与监控
- **新增业务功能**（本次只做等价迁移；例外见 §8.3）

---

## 3. 决策摘要

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | 分离程度 | 独立前端工程，构建产物由 FastAPI 托管 | 满足代码分离；保持单进程启动，避免跨域与双发版 |
| D2 | 框架 | React 18 + TypeScript + Vite | 生态最大；open-design 的设计产出可直接落进 React |
| D3 | 组件库 | Ant Design v5 | 本应用表格/表单极重，AntD 覆盖最全；可用 `ConfigProvider` 定制 token |
| D4 | 服务端状态 | TanStack Query | 读多写少 + 后端是唯一事实源；缓存/失效/轮询样板手写易出 bug |
| D5 | 图表 | ECharts + react-echarts | 保留现有能力，不换库；echarts 作为 npm 依赖，**不再单独 vendor** |
| D6 | 类型来源 | **手写** `types.ts` | 就 20 来个类型，手写可读；生成类型在后端微调时会红一片。代价是需防漂移 → 见 §9 |
| D7 | 路由 | react-router-dom | 8 个页面需要路由与深链接 |
| D8 | 端到端测试 | **不引 Playwright** | 成本高；本项目目前也无 E2E 基础 |
| D9 | 迁移方式 | 分 4 阶段，每阶段旧页面仍可用 | 不做大爆炸重写，随时能停 |
| D10 | 打包产物 | `frontend/dist`，**不入 git** | 由 `make frontend-build` 生成；`.gitignore` 已含 `dist/`，需补 `node_modules/` |
| D11 | CORS | **不加** | dev 走 vite 的 `/api` 代理，浏览器只与 :5173 同源；生产同源。加 CORS 会与「不引入跨域负担」的目标矛盾 |
| D12 | 业务态识别 | 后端加**可选响应头** `X-Anomaly-Biz-State` | JSON 结构一字不改；老前端只看 `detail` 文案，不受影响 |
| D13 | dist 定位 | `create_app(frontend_dist=...)` 可注入，默认**向上找 `frontend/dist`** | 向上找比写死 `parents[3]` 稳（wheel 安装下 `parents[3]` 指向 site-packages）；可注入让 SPA 测试不依赖真实构建产物 |

### 被推翻的决策

| 原决策 | 处置 |
|---|---|
| D8 / ADR-6「不引 React/Vue/构建链」 | 推翻。理由见 §1 |

> 注：`docs/DESIGN.md` 本身有未提交的用户改动（且用户已自行删掉「不做前端框架工程」
> 这条非目标），本次**不动该文件**。D8 / ADR-6 的正式改写列入实施收尾清单，
> 需用户确认后再动 —— 见 §12。

---

## 4. 架构

### 4.1 目录结构

```
anomaly-lab/
├── src/anomaly_lab/                  # Python 后端：只出 JSON API
│   └── web/
│       ├── app.py                    # 改造（见 §4.2）
│       ├── platform_routes.py        # 改造：删 /platform HTML 路由 + 清理失效 import；13 个 API 端点不动
│       └── static/                   # 阶段 4 才删（与旧页面一起退役）
│
├── frontend/                          # 独立前端工程
│   ├── package.json  package-lock.json
│   ├── vite.config.ts                # dev server + /api 代理
│   ├── tsconfig.json
│   ├── index.html
│   ├── dist/                         # 构建产物，不入 git
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                   # ConfigProvider + QueryClientProvider + Router
│       ├── router.tsx
│       ├── api/
│       │   ├── client.ts             # fetch 封装 + ApiError + detail 归一化（§6.2）
│       │   ├── types.ts              # 手写类型，对齐 OpenAPI
│       │   ├── platform.ts           # 13 个 /api/platform/* 端点，一函数一端点
│       │   ├── series.ts             # /api/series、/api/series/{id}/values、/api/summary、/api/badcases
│       │   └── annotate.ts           # /api/annotate/*
│       ├── components/               # 通用组件
│       │   ├── AppLayout.tsx         # 侧边栏 + 顶栏
│       │   ├── StateBoundary.tsx     # 五态封装（§6.1）
│       │   ├── DataTable.tsx
│       │   └── ...
│       ├── features/                 # 按业务域切
│       │   ├── jobs/
│       │   │   ├── PreviewChart.tsx      # 值 + 基线 + 上下界 + 告警点 ＋（新增）分数副轴/阈值线
│       │   │   ├── CompareChart.tsx      # 多算法叠加图（旧有）
│       │   │   ├── CompareTable.tsx      # 多算法对比表
│       │   │   ├── ComparePicker.tsx     # 对比算法勾选组（旧有）
│       │   │   ├── RunsView.tsx          # 任务运行记录列表（旧有）
│       │   │   ├── AlertRulesView.tsx    # 告警规则**只读**展示（无编辑端点，见 §8.3）
│       │   │   ├── FeedbackPanel.tsx     # 反馈 + 建议 + 一键应用
│       │   │   ├── FeedbackHistory.tsx   # 反馈历史列表（旧有）
│       │   │   ├── ClassificationCard.tsx# 形态分类结论（旧有提示的正式化）
│       │   │   └── queries.ts            # 本域的 query/mutation hooks
│       │   ├── sources/  metrics/  series/  evaluation/  annotate/
│       ├── pages/                    # 路由级页面（薄壳，8 个）
│       └── styles/
│           ├── tokens.css            # ★ 唯一颜色定义处（CSS 变量）
│           └── global.css
│
└── Makefile                          # 新增 4 个目标
```

**为什么按 `features/` 而不是按组件类型切**：
预览图表、对比图/表、规则展示、反馈面板这 5 个东西是**同一个业务域**（检测任务）的组成部分，
共享同一份 run/series 上下文、同一套 severity 映射。放一起改才不会散。

**API 层的两层落点**：`api/*.ts` 只做「一个端点一个函数 + 类型」，不碰 React；
`features/<域>/queries.ts` 才是 TanStack Query 的 hooks。这样 API 层可脱离 React 单独测试。

### 4.2 后端改造清单

| # | 改动 | 细节 | 阶段 |
|---|---|---|---|
| B1 | 删 4 个 HTML 页面路由 | `/`、`/annotate`、`/report` 在 `app.py`；**`/platform` 在 `platform_routes.py:142`** | 4 |
| B2 | 清理失效 import 与模板目录 | 删 B1 的路由后，以下全部失效（ruff F401）：`app.py` 的 `HTMLResponse`、`Request`、`Jinja2Templates`、模块级 `_TEMPLATES = Jinja2Templates(...)`；`platform_routes.py` 的 `HTMLResponse`、`Request`，以及 `platform_routes.py:144` 那句**函数内延迟 import** `from anomaly_lab.web.app import _TEMPLATES`（本是为绕循环依赖而写，路由没了它自然消失，`platform_routes.py` 之后不再依赖 `app.py`）。**同时删掉 `templates/` 目录下全部 5 个 Jinja 模板**（`base/index/annotate/report/platform.html`） | 4 |
| B3 | 删 `/static` 挂载 + `static/` 目录 | `app.py:97` 的 `app.mount("/static", StaticFiles(directory=.../static"))`。**必须与 B1 同一次提交**：目录先删、挂载还在会抛 `RuntimeError: Directory does not exist`，`create_app()` 直接炸，8 处 `create_app()` 调用全部失败 | 4 |
| B4 | 挂静态产物（**条件挂载**） | **不挂 `"/"`**。只在 `dist/assets` **存在时**才 `app.mount("/assets", StaticFiles(directory=dist/"assets"))`。<br>⚠️ **不要用 `check_dir=False` 当安全网**：本机 starlette **1.10.0** 的 `check_dir=False` 只跳过**构造期**检查，`StaticFiles.__call__` 里的 `check_config()` 会在**第一次请求**时抛 `RuntimeError: StaticFiles directory '...' does not exist.` —— 实测 `dist` 缺失时每个 `/assets/*` 请求都 500。正确做法是**目录不存在就根本不挂** | 4 |
| B5 | SPA fallback | catch-all `@app.get("/{full_path:path}")`，**注册在所有 `/api/*` 之后、且是最后一个路由**。逻辑：<br>① `full_path` 以 `api/` 开头 → 404 JSON（拼错的 API 不该拿到 HTML）<br>② `dist/<full_path>` 是文件 → `FileResponse`<br>③ 否则 → `dist/index.html` | 4 |
| B6 | dist 定位与缺失策略 | 路径：**从 `Path(__file__).resolve()` 向上找 `frontend/dist`**（比写死 `parents[3]` 稳 —— wheel 安装下 `parents[3]` 指向 site-packages）。**dist 不存在时不挂载、不报错**，返回 503 + 一句「请先执行 `make frontend-build`」。理由：CI 与新 clone 的仓库没有 dist，崩溃就等于所有测试红 | 4 |
| B7 | `create_app` 支持注入 dist | 新增参数 `create_app(..., frontend_dist: Path | None = None)`，默认走 B6 的「向上找」。这样 SPA 路由测试可以用 `tmp_path` 造一个假 dist，**不依赖真实构建产物**，测试在任何环境都确定 | 4 |
| B8 | 业务态响应头 | 5 处业务态 404 加响应头 `X-Anomaly-Biz-State`，取值见 §4.2.1。**JSON 结构一字不改**（老前端只看 `detail` 文案，不受影响） | 4 |
| B9 | 改写 2 个旧 HTML 页面测试 | `tests/web/test_app.py::test_index_page_loads`（断言 `GET / == 200` 且正文含 "anomaly-lab"）与 `tests/web/test_report_page.py::test_report_page_loads`（断言 `GET /report == 200`）。B1 删掉这两个路由后，它们落到 catch-all —— **dist 不存在时返回 503**（CI / 新 clone），断言必然失败。改为：用 B7 注入的 tmp dist 断言 SPA fallback 行为（见 §10） | 4 |
| B10 | **不动** | 13 个 `/api/platform/*` 的请求/响应 **JSON 结构**、以及 `/api/series`、`/api/series/{id}/values`、`/api/summary`、`/api/badcases`、`/api/annotate/*` 的 JSON 结构，**一字不改** | — |

#### 4.2.1 业务态 → 响应头映射表（B8 的确切内容）

| 端点 | 状态码 | `detail` | `X-Anomaly-Biz-State` | 前端语义 |
|---|---|---|---|---|
| `GET /api/platform/jobs/{id}/preview` | 404 | 该任务还没有运行记录 | `no_run` | 空态·已配置但无运行记录 +「立即运行」 |
| `GET /api/platform/jobs/{id}/preview` | 404 | 该次运行没有序列结果 | `no_series` | 空态 |
| `GET /api/platform/jobs/{id}/preview` | **200** | —（响应体 `sufficient:false` + `insufficient_reason`） | — | **数据不足态**（不是 404！） |
| `GET /api/platform/jobs/{id}/compare` | 404 | 该窗口内没有取到数据 | `no_data` | 空态·该窗口无数据 |
| `GET /api/platform/jobs/{id}/compare` | 404 | 序列 X 有效点仅 N 个，不足以做检测 | `insufficient_data` | **数据不足态** |
| `GET /api/platform/jobs/{id}/compare` | **400** | 没有可对比的算法 | `no_algorithms` | 空态·无可选算法 |
| `GET /api/badcases` | 404 | 该序列还没有检测结果 | `no_result` | 空态·Bad Case 页 |
| 上述端点 | 404 | 序列不存在 | （**不加头**） | **真错误**（序列不在数据集） |
| 上述端点 | 404 | 序列不存在: X | （**不加头**） | **真错误**（X 不在这次运行里） |
| 任意 | 400 | 当前倍数无效 / 倍数必须为正数 | （**不加头**） | **真错误**（输入非法） |
| 任意 | 404 | store 的 `ValueError` 原文（如「任务不存在: 999」） | （**不加头**） | **真错误** |

**注意 preview 与 compare 的数据不足表达方式不同**：preview 是 **200 + 响应体**，
compare 是 **404 + 响应头**。前端两条路径都要处理。

**为什么不用「只按中文文案匹配」**：后端改一个字就会打穿前端判定。响应头是显式契约，
且对现有客户端零影响。响应头缺失时（如老版本后端）退回按 `detail` **前缀**匹配，
前缀表就是上表的 `detail` 列（`序列 X 有效点仅…` 取「序列」+「有效点仅」两段前缀）。

### 4.3 部署形态

```
开发：  vite dev server :5173  ──proxy /api──→  uvicorn :8000
生产：  uvicorn :8000  ──→  /api/*  +  /assets/*  +  /* → frontend/dist（单进程）
```

`make serve` 继续走 `python -m anomaly_lab.cli serve`（它负责装配 store + scheduler + uvicorn），
而不是裸 uvicorn；`serve` 依赖 `frontend-build`，dist 缺失时给出明确报错。

---

## 5. 视觉方向落地

三个候选方向由 open-design 并行产出原型（基于同一份真实 API 数据的 brief），
用户从中选定一个：

| 方向 | design system id | 特征 |
|---|---|---|
| A 暗色指挥中心 | `mission-control` | 深空蓝底 + 琥珀遥测 + 等宽数字 + 层级告警色 |
| B 云平台暗色 | `dashboard` | 深色云平台质感 + 模块化网格 + 玻璃面板 |
| C 浅色企业风 | `enterprise` | 浅色高对比 + 表格表单优先 + 留白分层 |

> 三个 id 已确认在 open-design 中真实存在（`od://design-systems/<id>/DESIGN.md` 可读）。

**这是计划里的一个显式检查点**：产出原型 → **用户选定** → 落地 `tokens.css` → 阶段 1 才能继续。

### 落地规则：颜色只有一个来源

```
选定 design system
      ↓
frontend/src/styles/tokens.css     ← 唯一的颜色定义处（CSS 变量）
      ├──→ AntD ConfigProvider theme.token    ← 表格、表单、按钮
      ├──→ ECharts palette / 颜色常量         ← 图表
      └──→ severity→颜色映射                 ← 正常 / P1 / P0
```

**不允许 AntD 与 ECharts 各自定义一套色值。** 后端返回的 `severity`（0/1/2）
映射到「正常/P1/P0」三色，这条映射必须走同一套变量 —— 否则图表里的红点
与表格里的红色徽标对不上，这是运营盯屏幕时最先发现的问题。

---

## 6. 状态与错误处理

### 6.1 五态矩阵

每个数据视图必须覆盖这 5 种状态。当前前端只有「有数据」和「`alert()`」两种。

| 状态 | 表现 |
|---|---|
| 加载中 | **骨架屏**，不是转圈 spinner |
| 空 · 未配置 | 「还没有检测任务」+「新建任务」按钮 |
| 空 · 已配置但无运行记录 | 「该任务还没有运行记录」+「立即运行」按钮 |
| 错误 | 内联 Alert，显示后端 `detail` 原文，**不弹窗** |
| **数据不足**（业务态，不是错误） | 「有效点仅 N 个，不足以做检测」，图表位置放占位说明 |

最后一行是本项目的硬约定（见 `docs/PLATFORM.md`「缺失值：自动兜底 + 可覆盖 + 绝不静默」）：
**有效点不够时不能画成「一切正常」。**
旧前端在 preview 返回 `sufficient: false` 时把图表画空 —— 用户看到一片空白，会以为系统正常。

状态判定来源见 §4.2.1：空态与数据不足态由 `X-Anomaly-Biz-State` 响应头（或 preview 的
`sufficient:false` 响应体）识别，**不显示红色错误框**。

### 6.2 错误契约

```
后端  HTTPException(status_code, detail="中文说明")
  ↓
前端  client.ts 解析 → 抛 ApiError { status, message, bizState? }
  ↓
页面  AntD <Alert> / message.error(message)
```

**`alert()` 与 `prompt()` 从前端代码里彻底消失**（含 `annotate.js:61` 选异常类型用的 `prompt()`）。
`report.js` / `annotate.js` 那种「静默 return」也不保留。

三处必须特殊处理：

| 情况 | 处理 |
|---|---|
| **422 校验错误** | FastAPI 的 `detail` 是**数组**（`[{loc, msg, type}]`），不是字符串。必须拼接 `msg` 字段：`detail.map(d => d.msg).join("；")`。直接渲染会得到 `[object Object]`。422 在建指标/建任务时很容易触发（SQL、时间格式、规则行） |
| **业务态 4xx** | 按 §4.2.1 的映射表判定 → 走 §6.1 的空态 / 数据不足态。**响应头缺失时按 `detail` 前缀兜底**，前缀表（与 §4.2.1 的 `detail` 列一致）：<br>`该任务还没有运行记录` → `no_run`<br>`该次运行没有序列结果` → `no_series`<br>`该窗口内没有取到数据` → `no_data`<br>`序列 … 有效点仅` → `insufficient_data`<br>`没有可对比的算法` → `no_algorithms`<br>`该序列还没有检测结果` → `no_result`<br>其余（「序列不存在」等）→ 真错误 |
| **真错误** | 其余 4xx/5xx → 红色内联 Alert，`detail` 原文 |

---

## 7. 数据流

### 7.1 query key 约定（完整清单）

```
['catalog']                                    # GET  /api/platform/catalog
['preview', jobId, runId, seriesId]            # GET  /api/platform/jobs/{id}/preview
['compare',  jobId, seriesId, detectors]        # GET  /api/platform/jobs/{id}/compare
['suggestion', jobId, runId]                   # GET  /api/platform/jobs/{id}/feedback/suggestion
['feedback', jobId]                            # GET  /api/platform/jobs/{id}/feedback
['runs', jobId]                                # GET  /api/platform/jobs/{id}/runs
['series']                                     # GET  /api/series
['seriesValues', seriesId]                     # GET  /api/series/{id}/values      ← 标注页数据源
['summary']                                    # GET  /api/summary                 ← 评估报告页
['badcases', seriesId]                         # GET  /api/badcases                ← Bad Case 页
['annotations', seriesId]                      # GET  /api/annotate/{id}           ← 标注页
```

### 7.2 失效规则

写死在 mutation 里，不靠人记：

| 操作 | 失效 |
|---|---|
| 建 / 改 / 启停任务 | `['catalog']` |
| **立即运行** | `['catalog']`（`Job` 含 `last_run_at` / `next_run_at`）**+ `['runs', jobId]` + `['preview', …]` + `['suggestion', …]`** |
| 提交反馈 | `['feedback', jobId]` + `['suggestion', …]` |
| **应用建议倍数** | `['catalog']` + `['suggestion', …]` **+ `['compare', …]`**（compare 响应带**当前** `alert_rules` 与 `band_width`，不改会拿旧倍数解读对比结果） |
| 保存标注 | `['annotations', seriesId]` |

> `['preview', …]` 里的 `alert_rules` 是**运行时的快照**，不随任务配置变 —— 所以应用建议后
> 不需要失效 `['preview', …]`。这一点要写在代码注释里，否则后来者会「顺手」加一条。

### 7.3 run 状态与轮询

**run 状态词表**（`store.py` / `runner.py`）：

```
running | success | failed | insufficient_data
```

**`POST /api/platform/jobs/{id}/run` 是同步的** —— 检测在请求内跑完才返回
（旧前端也是 await 到返回才刷新列表）。所以：

- **「立即运行」按钮**用 mutation 的 loading 态覆盖整个 POST，**不轮询**
- **轮询只针对调度器触发的 run**：轮询 `['runs', jobId]`，当列表里存在
  `status == 'running'` 的 run 时继续（3 秒一次），否则停

无条件轮询是资源浪费，也会让「运行中」这个状态难以辨认。

---

## 8. 迁移策略

### 8.1 四个阶段

每阶段结束后**旧页面都还能用**，随时能停。

| 阶段 | 内容 | 完成判据 |
|---|---|---|
| 0 | 选定视觉方向 → 落地 `tokens.css` | 用户从 A/B/C 三套原型中选定一个 |
| 1 | 搭骨架：Vite + TS + 路由 + AntD + API 层 + tokens；搬「序列总览」「任务列表」 | 两个页面在新栈下可用，旧 `/platform` 仍可用 |
| 2 | 搬核心 `JobDetail`：预览图表 + 多算法对比（图/表/勾选组）+ 运行记录 + 规则只读展示 + 分类卡 + 反馈（提交/历史/建议） | 平台页的全部功能在 `/jobs/:id` 可用 |
| 3 | 搬「数据源」「指标」「标注」「评估」「Bad Case」 | **8 个页面全部可用** |
| 4 | 删旧模板 + 3 个老 JS + `/static` 挂载 + `templates/` 目录；后端切到托管 `dist` + SPA fallback + 业务态响应头 | 仓库里只剩一套前端；`/jobs/1` 刷新不 404 |

### 8.2 功能对照表（验收清单）

**A. 等价迁移**（旧有 → 新位置，逐条打勾）

| 旧位置 | 旧功能 | 新位置 |
|---|---|---|
| `/`（index.html） | 首页（只显示序列数） | `/` 序列总览 |
| `/platform` §1 | **新增**数据源 + 列表 | `/sources` |
| `/platform` §2 | **新增**指标（SQL / 时间格式 / 时区 / 缺失策略 / group by / freq）+ 列表 | `/metrics` |
| `/platform` §3 | **新增**任务（算法 / 窗口点数 / 执行间隔 / 告警规则）+ 列表 | `/jobs` |
| `/platform` §3 | 启停任务 | `/jobs` |
| `/platform` §3 | 立即运行 | `/jobs` / `/jobs/:id` |
| `/platform` §3 | 建任务时录入告警规则 —— **倍数条件**（`2.5, P1`） | `/jobs` 新建表单 |
| `/platform` §3 | 建任务时录入告警规则 —— **绝对值条件**（`>50, P0` / `>=50` / `<10` / `<=10`） | `/jobs` 新建表单 |
| `/platform` §3 | 规则语义说明：**顺序即档位顺序**（最后一行最严重）、**命中多条取最高档**、留空用默认两档（2.5→P1 / 3.75→P0） | `/jobs` 新建表单（提示文案） |
| `/platform` §3 | 选算法时按 `detectors[].default_threshold` **自动预填默认规则** | `/jobs` 新建表单 |
| `/platform` §4 | 预览图表：实际值 + 基线线 + 上下界带 + 告警散点 | `/jobs/:id` → `PreviewChart` |
| `/platform` §4 | 图表能力：`dataZoom`（inside + slider）、tooltip、legend、severity 分级配色与点大小 | `PreviewChart` / `CompareChart`（迁移时最容易丢，验收要逐项看） |
| `/platform` §4 | 预览点数超限提示（`MAX_PREVIEW_POINTS=2000`，显示「已抽样 N/M」） | `/jobs/:id` → `PreviewChart` |
| `/platform` §4 | **运行记录下拉**：`#id status (n_series 序列 / n_alerts 告警)` + 失败原因前 40 字 | `/jobs/:id` → `RunsView` |
| `/platform` §4 | **序列下拉**：`series_id (数据不足 \| N 告警)` | `/jobs/:id` |
| `/platform` §4 | 多算法对比**算法勾选组**（复选框；默认勾 auto 与 ≤4 个候选；可改选后重查） | `/jobs/:id` → `ComparePicker` |
| `/platform` §4 | 多算法对比**叠加图**（各算法基线与告警点叠在同一张图上） | `/jobs/:id` → `CompareChart` |
| `/platform` §4 | 多算法对比**表**（告警数 / 最高档 / 最高分 / **惯用倍数**） | `/jobs/:id` → `CompareTable` |
| `/platform` §4 | 多算法对比**表**的「最高档点数」列（= `n_top`，最高档上的告警**点数**） | `/jobs/:id` → `CompareTable` |
| `/platform` §4 | 「设为任务算法」 | `/jobs/:id` → `CompareTable` |
| `/platform` §4 | 顶部提示：`自动 → 检测器 · 形态（回退）· score_type · 规则`，推荐理由在 tooltip | `/jobs/:id` → `ClassificationCard` |
| `/platform` §5 | 反馈提交（漏报 / 误报 / 正确 / 其他 + 备注） | `/jobs/:id` → `FeedbackPanel` |
| `/platform` §5 | **反馈历史列表** | `/jobs/:id` → `FeedbackHistory` |
| `/platform` §5 | 「评估并给建议」 | `/jobs/:id` → `FeedbackPanel` |
| `/platform` §5 | 「一键应用」建议倍数 | `/jobs/:id` → `FeedbackPanel` |
| `/report` | 评估总表（序列 / 形态 / 检测器 / Precision / Recall / F1 / Range-F1 / **真值点** / **预测点**） | `/evaluation` |
| `/report` | 点行看 Bad Case 详情（数值 + 分数 + 阈值线） | `/badcases` |
| `/annotate` | 波形刷选标注 + 选异常类型（6 种）+ 存 JSONL | `/annotate` |

**B. 顺带修掉的问题**（旧行为是缺陷，新实现必须不同）

| 旧行为 | 新行为 |
|---|---|
| `report.js` 对 `/api/badcases` 404 静默 `return` | 显示错误 Alert |
| `report.js:55` `markArea: {}` 是**空对象 markArea，等于没画**；`/api/badcases` 返回的 `badcases[].indices` 从未被使用 → Bad Case 详情图看不出异常区间 | 用 `badcases[].indices` 真正画出异常区间 |
| 对比表的「最高档」列显示的是 `n_top`（最高档上的**点数**），与列名不符 —— `levels[n_top]` 会是 `undefined` | 「最高档」列显示**档位名**（`levels[max(severity)]`），另加「最高档点数」列显示 `n_top` |
| `platform.js` 6 处 `alert()` | 内联 Alert / `message.error` |
| `annotate.js:61` 用 `prompt()` 选异常类型 | 下拉选择（spike / contextual / drift / freq_shift / variance_shift / flatline） |
| `annotate.js` **零错误处理**：fetch 不看 `resp.ok`；`/api/series` 出错时 `items` 不是数组 | 统一走 `client.ts`，错误可见 |
| 预览 `sufficient: false` 时图表画空 | 显示「有效点仅 N 个，不足以做检测」占位 |

**C. 新增项**（明确标出，验收时不算「缺失」）

| 新增 | 说明 |
|---|---|
| 侧边栏导航布局 | 旧版是顶栏横向链接 |
| 序列列表（旧首页只有计数） | 真正的序列总览 |
| 序列列表里的 **P0 数** | 旧 UI 的序列下拉只有 `series_id (数据不足 \| N 告警)`，**没有 P0 数** |
| 预览图的**分数副轴 + 阈值线** | 旧平台预览图**没有**这两样（那是 badcase 详情图才有的）。作为新增 |
| `/badcases` 独立路由 | 旧版是评估页里点行弹出 |

> **删除功能不存在**：当前 UI 与后端**都没有删除能力** —— 没有 `DELETE` 端点，
> `store.py` 里没有 `delete_*`，`platform.html` 只有「新增」按钮。
> 因此「增删」改为「新增 + 列表」，**不把 DELETE 端点纳入本次范围**。

### 8.3 范围说明

- **告警中心**（跨任务汇总所有 P0/P1）**不在本次范围**。平台目前没有支撑它的 API
  （只有 run 级汇总 `n_alerts`/`n_p0` 与 preview 级 `severity` 数组），
  新增它意味着加后端端点 —— 属于新功能，不夹带进等价重构。列入 ROADMAP 的「以后做」。
  > （发给 open-design 的 brief 里导航含「告警」，那只是原型导航占位，实际实现不含。）
- **告警规则不能自由编辑**：现有 `PATCH /api/platform/jobs/{id}` 的请求体 `JobToggleIn`
  只接受 `enabled` / `detector`；规则只能在**建任务时**随 `JobIn.alert_rules` 一次性写入。
  `store.update_job_rules` 只被 `apply-suggestion`（按比例整体缩放）内部调用，没有对外的
  任意规则编辑端点。所以 `AlertRulesView` 是**只读展示**，规则录入仍在新建表单里。
  要支持自由编辑需新增端点 —— 不在本次范围。
- **「最小窗口需求提示」与「`freq` 一致性校验」是后端逻辑**，本次不做。
  它们要等新前端能展示提示与校验错误后再补，否则要改两遍。

---

## 9. 测试策略

| 层 | 工具 | 覆盖 |
|---|---|---|
| 后端 | pytest（已有 268 个） | 保持全绿（**B9 改写的 2 个除外**，它们换成 SPA 行为断言）；**扩展**：① 断言关键响应字段存在，防手写 `types.ts` 漂移（D6 的代价补偿）；② 断言 SPA 路由行为（`/jobs/1` → 200 + index.html 正文；**`GET /api/typo` → 404 JSON**；`/assets/x.js` → 200 真实文件内容）；③ 断言业务态 404 带 `X-Anomaly-Biz-State`、而「序列不存在」**不带**（§4.2.1 逐行断言）；④ 断言 dist 缺失时 `create_app()` 不崩溃且返回 503 |
| 前端单测 | vitest + @testing-library/react | API client 的 `detail` 归一化（422 数组拼接、业务态响应头）；`StateBoundary` 五态渲染；`PreviewChart` 在「数据不足 / 无基线带 / 有缺失点」下的行为 |
| 端到端 | **不引** | 见决策 D8 |

**CI 依赖**：`frontend/dist` 不入 git，所以 CI 必须先跑 `make frontend-install && make frontend-build`，
再跑 pytest。前端的 vitest 不依赖构建产物（跑源码）。

---

## 10. 验收标准

1. `make dev` / `make serve` **一条命令**起全栈
2. §8.2-A 功能对照表**逐项等价**（逐条打勾）
3. §8.2-B 的 **6 个**静默失败/弹窗问题**全部消失**
   （`grep -rn "alert(\|prompt(" frontend/src` 为空；`report.js`/`annotate.js` 的静默 return 已清除）
4. `npm run build` 后由 FastAPI 托管：
   - `GET /jobs/1` → **200** + index.html 正文（SPA fallback 生效）
   - `GET /api/typo` → **404 JSON**（不是 SPA 的 HTML）
   - `GET /assets/<真实文件>` → **200** + 文件内容
   - `POST /api/typo` → 405（路由方法不匹配，属正常）
5. 仓库里**不再有两套前端** —— 老 Jinja 模板（5 个）+ 3 个老 JS 文件 + `static/` 目录全删
6. `pytest` / `vitest` / `ruff` 全绿
7. 「数据不足」场景端到端可见（构造一个真的数据不足的序列跑一遍）；
   preview 的 200 路径与 compare 的 404 路径**都**能正确呈现数据不足态
8. 视觉一致性抽查：图表里的 P0 红点与表格里的 P0 徽标**同色**
9. `frontend/dist` 不存在时，`create_app()` **不崩溃**，返回明确的 503 提示
10. 迁移过程中**旧页面始终可用**（阶段 1~3 期间 `/platform` 等旧 URL 可访问）

---

## 11. Makefile 目标

```makefile
frontend-install   # cd frontend && npm ci      （首次需 npm install 生成 package-lock.json 并入库）
frontend-build     # cd frontend && npm run build → frontend/dist
dev                # 并行：vite :5173（/api 代理到 :8000）+ uvicorn :8000
serve              # frontend-build + python -m anomaly_lab.cli serve（单进程全栈）
```

`make dev` 的实现要点：

- vite 与 uvicorn **两个进程并行**：用 `&` 起 vite（后台），前台跑 uvicorn，
  uvicorn 退出时 `kill` 掉 vite（`trap`）。不引入 `concurrently` 之类的额外依赖。
- vite 的 `/api` 代理目标固定为 `http://127.0.0.1:8000`，写在 `vite.config.ts` 里
- `frontend-install` 用 `npm ci`（需要 `package-lock.json`）；**首次初始化用 `npm install`
  并把生成的 `package-lock.json` 提交进仓库**，之后 `npm ci` 才可用

`.gitignore` 补 `node_modules/`（`dist/` 已存在，覆盖 `frontend/dist`）。

---

## 12. 收尾清单（阶段 4 之后）

| # | 事项 | 说明 |
|---|---|---|
| F1 | 改写 `docs/DESIGN.md` 的 **D8 / ADR-6** | 该文件有用户未提交改动，**需用户确认后再动**。改写内容：「不再引入 React/Vue/构建链」→「前端为独立 React+TS+Vite 工程，后端只出 JSON API，构建产物由 FastAPI 托管」 |
| F2 | 清理 `pyproject.toml` 的 `jinja2` 依赖 | 删模板后不再需要（可选） |
| F3 | 更新 `docs/ARCHITECTURE.md` / `docs/PLATFORM.md` 的 Web 章节 | 反映新前端结构与 `make dev` / `make serve` |
| F4 | 更新 `docs/ROADMAP.md` | 记录「告警中心」「最小窗口提示 + freq 校验」列入以后做（当前 ROADMAP 里无对应条目，是纯新增） |

---

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `node_modules` 约 200MB，仓库变重 | `node_modules` 与 `dist` 均入 `.gitignore` |
| 后端手写类型与实际响应漂移 | pytest 断言关键响应字段（§9） |
| AntD 默认观感盖过选定的 design system | 颜色只走 `tokens.css`；AntD 用 `ConfigProvider` 定制，不引入第二套色板 |
| SPA fallback 吞掉 API 404 | catch-all 对 `api/` 前缀单独返回 404 JSON（§4.2 B5） |
| `Mount("/")` 吞掉全部路径 | **不挂 `"/"`**，只挂 `/assets`（§4.2 B4） |
| `check_dir=False` 让人误以为目录缺失是安全的 | **不用它**；目录不存在就**不挂载**（starlette 1.10.0 实测会在首次请求抛 RuntimeError） |
| 静态挂载目录不存在 → `create_app()` 崩溃 | `/static` 与 `dist` 都在阶段 4 同一次提交里处理；dist 缺失走 503（§4.2 B6） |
| 删掉 HTML 路由后旧测试断言 200 → 全红 | B9 明确改写这 2 个测试（§4.2） |
| 业务态被当成错误显示成红框 | 后端加 `X-Anomaly-Biz-State` 响应头（B8 + §4.2.1） |
| 422 的 `detail` 是数组，前端渲染成 `[object Object]` | client 层统一归一化（§6.2） |
| 迁移中途放弃 | 每阶段旧页面仍可用，可随时停在任一阶段 |
| `opencode upgrade` 冲掉 OD 兼容 shim | 见 §15-C |

---

## 14. 视觉方向与 token 落地的检查点

阶段 0 的产出必须包含：

1. 用户从 A/B/C 三套原型中选定一套（明确记录选了哪套）
2. `frontend/src/styles/tokens.css`：把该 design system 的色板、排版、间距、圆角落成 CSS 变量
3. AntD `ConfigProvider` 的 theme token 映射到同一套变量
4. ECharts 的 palette 从同一套变量读
5. `severity`（0/1/2）→ 正常 / P1 / P0 三色的映射写在同一处

---

## 15. 修订对照

### 15-A：第 1 稿 → 第 2 稿

| # | 第 1 稿的问题 | 修正 |
|---|---|---|
| 1 | 用 `Mount("/", StaticFiles(html=True))` + catch-all —— Starlette 下 Mount("/") FULL 匹配一切路径，catch-all 永不命中 | 只挂 `/assets`（B4），catch-all 内自行判定静态文件 vs index.html（B5） |
| 2 | 写「数据源/指标/任务**增删**」 —— 实际无任何 DELETE 端点 | 改为「新增 + 列表」，DELETE 不在范围（§8.2-A、§8.3） |
| 3 | 有 `AlertRulesEditor` —— 无编辑端点 | 改为 `AlertRulesView`（只读）（§4.1、§8.3） |
| 4 | 删 `static/` 但改造清单无对应项 | B3：与 B1 同一次提交 |
| 5 | 标 `platform_routes.py` 不动，却要删 `/platform` 路由（它在 `platform_routes.py`） | §4.1 改为「要动」；B1/B2 写清 |
| 6 | 漏了 422 的 `detail` 是数组、业务态用 404 + 文案 | §6.2 补处理；B8 加响应头 |
| 7 | CORS 与「dev 走 vite proxy」矛盾 | 决策 D11：不加 CORS |
| 8 | 未说 run 状态词表与同步语义 | §7.3 补齐 |
| 9 | query key 不完整 | 补 4 个 key |
| 10 | 「五态」vs「四态」自相矛盾 | 统一五态 |
| 11 | 阶段 3 写「7 个页面」 | 改为 8 个 |
| 12 | 对照表漏多算法叠加图、惯用倍数列、默认规则预填、抽样提示；把分数副轴误列为旧功能 | §8.2 拆成 A / B / C 三张表 |
| 13 | 有 `public/echarts.min.js` —— npm 依赖已含 echarts | 删除；D5 说明 |
| 14 | 缺 API 层落点 | 补 `api/platform.ts` 等 + `features/<域>/queries.ts` |
| 15 | `serve` 未说明用 `cli serve` | §4.3/§11 明确 |
| 16 | 只点名 `alert()` | 补 `prompt()` 与静默失败（§8.2-B） |
| 17 | D8 改写无限期推迟 | §12 F1 指定动作与前置条件 |
| 18 | 视觉方向是开放决策却无检查点 | §5 + §8.1 阶段 0 + §14 |

### 15-B：第 2 稿 → 第 3 稿

| # | 第 2 稿的问题 | 修正 |
|---|---|---|
| 1 | 用 `check_dir=False` 当「目录缺失也安全」的安全网 —— **starlette 1.10.0 实测无效**，只在构造期跳过检查，首次请求仍抛 RuntimeError | B4 改为「**目录不存在就不挂载**」；§13 删掉 `check_dir=False` 那一行 |
| 2 | §10 的两条验收标准冲突：删掉 HTML 路由后 `test_index_page_loads` / `test_report_page_loads` 断言 200，而 dist 缺失时返回 503 | B9：明确改写这 2 个测试；§9/§10 口径同步调整 |
| 3 | import 清理清单不完整（漏 `Jinja2Templates` 与模块级 `_TEMPLATES`），且没说删 `templates/` 目录 | B2 补全 import 清单 + 删 `templates/` 5 个模板 + 清理 `platform_routes.py:144` 的延迟 import |
| 4 | `GET /api/series/{id}/values` 既不在 `api/series.ts` 也不在 query key 里 → 标注页没有数据源 | §4.1 补进 `api/series.ts`；§7.1 补 `['seriesValues', seriesId]` |
| 5 | 失效规则漏 2 条：「立即运行」应失效 `['catalog']`（`last_run_at`/`next_run_at`）；「应用建议倍数」应失效 `['compare', …]`（compare 响应带当前 `alert_rules`/`band_width`） | §7.2 补两条，并写明 `['preview', …]` 不必失效的理由 |
| 6 | 「3 处业务态 404」与现实不符 —— 实为 **5 条**，且 preview 的数据不足是 **200 + 响应体**不是 404 | §4.2.1 改成完整映射表（5 条 404 + 1 条 200 路径 + 「序列不存在」按真错误处理） |
| 7 | 功能对照表写了旧 UI 没有的「P0 数」 | 移到 §8.2-C（新增） |
| 8 | 对照表漏 4 项真实旧功能：运行记录下拉、对比算法勾选组、告警规则绝对值条件 + 规则语义说明、反馈历史列表 | §8.2-A 补 4 行；§4.1 补 `ComparePicker` / `RunsView` / `FeedbackHistory` 组件 |
| 9 | 对照表漏 2 项真实旧 bug：`report.js` 的空对象 `markArea`（`badcases[].indices` 从未使用）；`annotate.js` 零错误处理 | §8.2-B 补 2 行；§10.3 的条数从 4 改为 6 |
| 10 | 评估总表漏 3 列 | §8.2-A 补 真值点 / 预测点 等完整 9 列 |
| 11 | `make dev` 无可执行细节；`npm ci` 在没有 lock 文件的全新仓库会失败 | §11 补：两进程并行方式、`trap` 清理、vite 代理目标、`package-lock.json` 首次生成并入库 |
| 12 | §10.4 写成「`/api/typo` 返回 404 JSON」，但非 GET 方法实际返回 405 | §10.4 限定为 `GET /api/typo`，并单列 405 的说明 |
| 13 | dist 路径写死 `parents[3]`，wheel 安装下失效 | 决策 D13：向上找 `frontend/dist`；B7 增加 `create_app(frontend_dist=...)` 注入参数，让 SPA 测试不依赖真实构建 |
| 14 | 未提 CI 需要 `frontend-build` | §9 补 CI 依赖说明 |

### 15-C：附注 —— OD 兼容 shim（本轮环境修复，非项目代码）

open-design 的 daemon 用 `opencode run --format json --dir <工作区>` 调 agent，
但本机 opencode 2.2.0 **没有 `--dir` flag**（`run --help` / `--help` 均已核对），
导致 OD 连续三次生成全部失败。修复方式（三层）：

1. `~/.opencode/bin/opencode` 换成 shim，把 `--dir <path>` 翻译成 `cd <path>`；
   真实二进制保留为 `opencode.real`（用 rename 而非覆盖，运行中的 inode 不受影响）
2. 给 OD 项目目录 `git init`，使「最近的 git root」正好是项目目录（语义等价于 `--dir`）
3. shim 给 `run` 子命令加 `--standalone`：容器内 opencode 用独立 HOME
   （`/home/open-design`），不知道宿主的 managed service 已占用 49374，
   会尝试再起一个 → "Managed service port 49374 is already in use"。
   `--standalone` 让每次 run 起私有服务，不抢端口，并行跑也不互撞

⚠️ `opencode upgrade` 会覆盖 shim；升级后若 OD 又报 `--dir` 错误，
用 `~/.opencode/bin/opencode.shim`（原件）恢复即可。**这与本项目仓库无关。**
