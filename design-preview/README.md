# anomaly·lab · 设计样张（静态）

一套 7 页的静态设计样张，用来评审“怎么设计更好”。**不改现有前端代码**，
所有数字都来自真实后端接口的一次快照。

## 页面

| 样张 | 对应真实路由 | 内容 |
|---|---|---|
| `index.html` | `/` | 概览：异常分数轨迹 + 告警事件条带、序列切换、KPI 条、任务健康、回测 |
| `alerts.html` | `/alerts` | 告警中心：真实列（等级/时间/点数/峰值分数/任务/序列/算法/详情）+ 四个筛选下拉 |
| `jobs.html` | `/jobs` | 检测任务：真实列（ID/名称/指标/算法/告警规则/间隔/状态/操作）+ 最近运行 |
| `evaluation.html` | `/evaluation` | 评估报告：整体指标、形态/算法/来源筛选、120 条逐条记录、维度聚合 |
| `sources.html` | `/sources` | 数据源：数据源列表、指标列表、浏览数据（只读查询的真实行） |
| `detections.html` | `/detections` | 检测记录：形态/算法/来源/时间筛选 + 分页的记录索引 + 信号曲线 + 检测偏差 |
| `annotate.html` | `/annotate` | 标注：选序列 → 波形上刷选区间 → 选类型 → 保存，标注列表 |

> 每页都以真实应用**已有的列表结构与列**为主体，只做视觉与信息量上的微调：
> 数字等宽右对齐、状态用克制 pill、规则列过长省略并在 title 里给全、
> 表格下补一行摘要（上次运行 / 覆盖点数 / 保留策略）。不另造布局。

- 方向：`data-terminal`（dark），seed `1377792503`，保留 `palette,type`
- 产品脸：IBM Plex Sans 正文，IBM Plex Mono 用于数字/时间戳/ID（本地加载 woff2）
- 签名：异常分数轨迹 + 告警事件条带；序列切换贯穿概览页
- 侧栏只有品牌、导航、主题 —— 不放「数据源 / 指标」这类常量，每页的发现句说明这屏在看什么
- 导航在样张内部互跳；侧栏底部「在真实应用中打开」回到 `127.0.0.1:5173`
- 响应式：1440/768/390，侧栏在 ≤860 折叠为顶栏+抽屉，KPI 两列，任务表在手机变两行
- 无 emoji、渐变、阴影、玻璃；数字等宽右对齐；状态色克制

## 本地预览

```bash
cd design-preview && python3 -m http.server 5199
# http://127.0.0.1:5199/
```

## 重新抓快照

样张里的每个数字都来自 `snapshot.mjs`，不手写：

```bash
# 后端：.venv/bin/python -m anomaly_lab.cli serve --port 8000
node design-preview/snapshot.mjs http://127.0.0.1:8000
```

数据来源：`/api/platform/overview`、`/api/platform/catalog`、`/api/platform/alerts`、
`/api/platform/jobs/{id}/runs`、`/api/platform/jobs/{id}/preview`、`/api/platform/storage`、
`/api/summary`、`/api/series`、`/api/series/{id}/values`、`/api/badcases`、`/api/annotate/{id}`。

## 检查

```bash
node /home/jiangzifeng/Project/.opencode/skills/design-taste-frontend/scripts/lint.mjs --app design-preview
for f in index alerts jobs evaluation sources detections annotate; do
  node /home/jiangzifeng/Project/.opencode/skills/design-taste-frontend/scripts/inspect.mjs \
    design-preview/$f.html --app --out .taste-skill/p-$f
done
```

当前结果：7 页全部 `0 FAIL, 0 WARN`；lint `0 FAIL, 26 WARN`（mono / framework-colour / em-dash
均为产品脸与现有生产色的刻意选择）。
