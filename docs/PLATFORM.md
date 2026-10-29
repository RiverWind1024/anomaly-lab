# 平台垂直切片

把「数据源 → 指标 → 检测任务 → 定时执行 → 基线预览」串成一条可运行的链路，对应 [my-thought.md](my-thought.md) 里第一阶段的设想。

## 快速体验

```bash
make platform-demo          # 生成 demo 源库 + 指标 + 任务（写入 data/）
make serve                  # http://127.0.0.1:8000/platform
```

或者纯脚本冒烟（不启 Web）：

```bash
make platform-smoke         # 跑一次任务并断言：2 条序列、有告警
```

## 三层配置模型

| 概念 | 存哪 | 关键字段 |
|---|---|---|
| 数据源 Source | `data/platform.db` 的 `sources` | 名称、类型（当前只有 `sqlite`）、路径（相对数据根目录或绝对路径） |
| 指标 Metric | `metrics` | 数据源、SQL、时间列、值列、分组列、时间格式、采样频率 |
| 检测任务 Job | `jobs` | 指标、算法、P1/P0 阈值、窗口点数、执行间隔、启用状态 |

运行记录在 `runs`，详细数组在 `data/cache/platform/runs/<run_id>/`（`index.json` + 每条序列一个 npz）。

## `$timefilter` 与 group by

指标 SQL 里必须**恰好有一个** `$timefilter`，执行时会被替换成时间条件：

```sql
SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts
```

执行时等价于（列名来自配置，已做标识符校验）：

```sql
SELECT * FROM (SELECT ts, host, value FROM metrics
               WHERE "ts" >= ? AND "ts" < ? ORDER BY ts) LIMIT 100001
```

- 时间范围用参数绑定，不做字符串拼接。
- 只允许 `SELECT` / `WITH` 开头的单条语句；含写操作关键字直接拒绝，连接以 `mode=ro` 打开。
- `group_column` 非空时，**在加载层就拆成独立序列**：序列 ID 为 `{指标名}:{分组值}`，检测器永远只面对一条序列。
- 单次查询上限 10 万行，超出要求缩小窗口或加聚合。

支持的时间格式：`iso`（ISO8601 字符串）、`epoch_s`、`epoch_ms`。

## 基线与告警分级

平台只接受能给出上下界的算法：`iqr` / `mad` / `zscore` / `seasonal` / `stl_residual` / `deseasonalized_iqr`。

- **分数越大越异常**，语义与离线评测一致（`score_type` 见 [ALGORITHMS.md](ALGORITHMS.md)）。
- **基线**：该算法认为的「正常值」曲线（IQR 类是稳健中位数，Seasonal 是相位中位数，STL 是趋势+季节拟合）。
- **上下界**：基线 ± 阈值 × 鲁棒尺度，阈值取任务的 P1 阈值；所以图上的带状区域就是 P1 判定的边界。
- **分级**：分数 > P1 阈值记 P1（橙），> P0 阈值记 P0（红），其余正常。阈值由用户在任务上配置，不自动猜测——「从 10 突增到 50 是 P0 还是 P1」没有通用答案。

## 调度语义

- 内置调度器随 `serve` 启动（`--no-scheduler` 可关闭），单线程串行执行任务。
- 每个任务有 `next_run_at`；到点执行后推进到 `now + interval`，失败也推进（失败详情在 `runs` 表，不会重试风暴）。
- 进程重启时把「错过」的窗口收敛到现在，**只补跑一次**，避免停机越久补得越多。
- 停用任务（`enabled=0`）不会进入到期队列。

## 已知限制（第一版有意不做）

- 只支持 SQLite 一种数据源；`kind` 字段与 `Source` 模型已为后续插件（InfluxDB / Prometheus）预留。
- 预处理（清洗/聚合）与取数在同一进程内完成，接口边界保留，但**没有**独立 worker 进程做内存隔离。
- 没有认证、多租户与权限；这是本地学习项目，不是可对外的服务。
- 多 worker 部署会各自跑一份调度器（当前按单进程使用设计）。
- 不做未来多步预测，上下界是「基线 ± 阈值 × 尺度」，不是统计意义上的预测区间。
- 序列级形态分类结果没有接进平台（离线分类器仍独立可用）。
