# spec 4 实现计划：数据保留与清理策略

> 对应 spec：`docs/superpowers/specs/2026-11-02-retention-policy-design.md`
> 分支：`feature/retention-policy`

## 任务分解

| # | 任务 | 文件 | 验证 |
|---|---|---|---|
| T1 | 保留策略的数据结构与纯函数 | `src/anomaly_lab/platform/retention.py` | 单测 |
| T2 | store：取全量 runs + 读写清理状态 | `src/anomaly_lab/platform/store.py` | 单测 |
| T3 | prune 执行器（删目录 / 删行 / 断引用 / 清孤儿） | `src/anomaly_lab/platform/retention.py` | 单测 |
| T4 | 调度器节流触发 | `src/anomaly_lab/platform/scheduler.py` | 单测 |
| T5 | CLI `prune` 命令 | `src/anomaly_lab/cli.py` | 手工 |
| T6 | HTTP 端点：`/api/platform/storage` + `/api/platform/prune` | `src/anomaly_lab/web/platform_routes.py` | 单测 |
| T7 | 契约守卫同步（两处） | `frontend/src/api/endpoints.test.ts`、`tests/web/test_api_contract.py` | pytest + vitest |
| T8 | 前端 API 封装 | `frontend/src/api/platform.ts`、`types.ts` | 类型检查 |
| T9 | 概览页「数据保留」卡片 | `frontend/src/pages/DashboardPage.tsx` | 页面测试 |
| T10 | 后端测试 | `tests/platform/test_retention.py`、`tests/web/test_retention_api.py` | pytest |
| T11 | 前端测试 | `frontend/src/pages/dashboard.test.tsx` | vitest |
| T12 | 文档 | `docs/PLATFORM.md`、`docs/ROADMAP.md` | 自检 |

## 实施顺序

```
T1 → T2 → T3          # 纯函数 → 存储 → 执行器
        ↓
     T4 → T5 → T6      # 触发器 → CLI → 端点
        ↓
     T7 → T8 → T9      # 契约 → 封装 → 界面
        ↓
     T10 → T11 → T12   # 测试与收尾
```

## 关键约束（实现时不能忘）

1. **最新一次 run 永远保留**（D84）—— 告警中心只读最新 run，删了它整个页面就空了。
2. **正在执行的 run 不删**（D85）—— `runner._INFLIGHT` 里登记着。
3. **feedback 不删，只把 `run_id` 置 NULL**（D86）—— 表里没有外键约束，必须手动 UPDATE。
4. **先删文件再删 DB 行**（D88）。
5. **保留窗口是 ∩ 不是 ∪**（D83）—— 两个条件都满足才保留。
6. **孤儿目录**：目录名转 int 查 DB，不在 `runs.id` 集合里就是孤儿；**非数字目录名跳过**。
7. **调度器清理要节流**（每小时一次）+ try/except（失败只记日志，不能杀掉调度线程）。
8. **不碰**：`data/mock_tsdb/`（假远端）、`data/annotations/`（人工标注）、
   `data/cache/detections/`（回测侧产物）。
9. **概览页文案**：「累计运行」→「保留期运行」（D92）。
10. **新端点要同步两处契约守卫**：`EXPECTED_PATHS` + `tests/web/test_api_contract.py`。
11. `to_iso` 输出带 `+00:00`，时间比较统一走 `parse_iso`。

## 验收

```bash
.venv/bin/python -m pytest -q          # 全绿
make lint                               # ruff 全绿
.venv/bin/python -m anomaly_lab.cli compliance-check
cd frontend && npx tsc --noEmit && npm test && npm run build
```

## 真机验证清单

- 造 300 次运行（临时改 store）→ `anomaly_lab prune --dry-run` 看报告 → 真删 → 磁盘占用下降
- 清理后告警中心仍有数据
- 清理后人工反馈仍在，`run_id` 为 NULL
- `MOCK_TSDB=1` 起假远端 → 平台清理后 `data/mock_tsdb/` 数据还在
