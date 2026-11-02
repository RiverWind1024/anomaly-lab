# spec 2 实现计划：假远端时序数据库 + 活数据

> 对应 spec：`docs/superpowers/specs/2026-11-02-mock-timeseries-db-design.md`
> 分支：`feature/mock-tsdb`

## 任务分解

| # | 任务 | 文件 | 验证 |
|---|---|---|---|
| T1 | 造数器：4 条曲线 + AR(1) + 尖峰/漂移/断流/值缺失 | `src/anomaly_lab/mock_tsdb/generator.py` | 确定性、形态、断流测试 |
| T2 | 存储层：SQLite（WAL）+ 写入 + 只读查询 | `src/anomaly_lab/mock_tsdb/tsdb.py` | 只读校验、列结构 |
| T3 | HTTP 服务：`POST /api/v3/query_sql` + 三种格式 | `src/anomaly_lab/mock_tsdb/server.py` | 格式、参数校验 |
| T4 | 后台线程：持续写入 + 滚动删旧 | `src/anomaly_lab/mock_tsdb/server.py` | 数据在流动 |
| T5 | 平台侧种子：`seed_mock_remote` | `src/anomaly_lab/platform/mock_remote.py` | 幂等测试 |
| T6 | CLI：`mock-tsdb` / `mock-demo` | `src/anomaly_lab/cli.py` | 命令存在 |
| T7 | Makefile 目标 | `Makefile` | `make -n` |
| T8 | **连接器一致性测试**（sqlite vs http） | `tests/platform/test_mock_tsdb.py` | 两条路径结果相同 |
| T9 | **WAL + 只读测试** | `tests/platform/test_mock_tsdb.py` | 只读到已提交数据 |
| T10 | 端到端：取数 → 检测 → 告警 | `tests/platform/test_mock_tsdb.py` | 尖峰报出告警 |
| T11 | 文档 | `docs/PLATFORM.md` `docs/ROADMAP.md` `README.md` | 自检 |

## 实施顺序

```
T1 → T2 → T3 → T4      # 假远端自己先完整
        ↓
     T5 → T6 → T7      # 平台侧接线
        ↓
  T8 → T9 → T10 → T11  # 测试与文档
```

## 关键约束（实现时不能忘）

1. **时间字面量格式统一 `+00:00`**（T 分隔 + 偏移）。
   SQLite 对 TEXT 做字典序比较，格式不统一 → 边界行误判。
2. **只读校验**用平台同款的 `validate_readonly_sql`（T2/T3）。
3. **确定性造数**：`np.random.default_rng([seed, index])` 取 innovation，
   AR(1) 递推。不能用全局 RNG。
4. **写入要开 WAL**（T2），平台侧 `mode=ro` 打开（spec §11 约束 1）。
5. **假远端的数据单独放** `data/mock_tsdb/`，不碰 `data/platform/source.db`。
6. **`{sql}` 放 body 不放 url** —— body 原样替换，url 里会百分号编码。
7. **`format` 请求与解析必须一致** —— body 里写 `format=csv`，config 里也 `csv`。
8. **不实现鉴权**，但接受并忽略 `Authorization` 头。
9. **JSON 用对象数组**（不是 InfluxDB 3 的两段式）—— CSV 是主通路。
10. **不新增任何依赖**。

## 验收

```bash
.venv/bin/python -m pytest -q -p no:warnings   # 全绿
make lint                                       # ruff 全绿
```

真实验证（人工）：

```bash
make mock-tsdb &        # 假远端 :8181
make mock-demo           # 平台侧建源/指标/任务
make serve               # UI 看效果
```
