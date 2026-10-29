# ROADMAP

> **规则：新想法只进这里，不插队进当前里程碑。**
> 这是防止项目烂尾的核心机制（DESIGN.md §8.3 风险 4）。

## v1 已排期（见 PLAN.md）

- Chunk 1：骨架 + 合成数据 + 形态分类
- Chunk 2：检测器 + 评估闭环
- Chunk 3：深度模型（TCN / LSTM / Chronos）
- Chunk 4：Web + 文档

## 待定 / 未决

- [ ] UCR 单序列文件的真实 URL 形式（实现时校准，RESEARCH.md §6）
- [ ] `chronos-t5-tiny` 权重的实际可下载性
- [ ] ECharts CDN 是否可达 → 倾向本地 vendor 一份

## v2 候选池（不在 v1 范围）

- 流式 / 在线检测（滑窗 + 增量统计量）
- 误报抑制策略（按异常方向 / 时段 / 偏离度匹配）—— 对应现职工作的"反馈抑制"
- 机器学习形态分类器（对照规则版，评估可解释性 vs 准确率的取舍）
- 零值 / 稀疏事件的专门建模（泊松、负二项）
- 多变量异常（NASA SMAP/MSL 遥测）
- 分布漂移检测（训练/服务分布不一致）
- 接入 Prometheus / OpenTelemetry 真实监控源 —— **注意：这会拉长红线边界，需重新评估合规**

## 环境降级记录

（若发生 statsmodels 缺失 / torch 不可达 / Python 3.12 装不上等，在此记录实际采用的降级方案与影响范围。）

## 实现期设计校准（Chunk 1）

- **分类规则顺序修正**：计划中 `zero_ratio >= 0.6 -> high_zero_ratio` 会先吞掉稀疏事件（其零值占比约 99%）。实现改为先按“非零连续段数”判 `sparse_event`，再判 `high_zero_ratio`。
- **`changepoint_score` 改为大窗口中位数差**：原“全局两段均值差”对 drift / flatline 等短异常段过于敏感；改用变点两侧 20% 窗口的中位数差 / 全局 MAD，阶梯与趋势/短异常段可稳定区分。
- **`trend_strength` 改为 |Spearman ρ|**：OLS 斜率显著性会被异常段抬高残差方差，导致趋势型与阶梯型混淆。
- **周期检测收紧**：周期候选需满足 `n // p >= 3`；ACF 峰前需有明显低谷，且在 2 倍周期处仍保留相关性（排除单调衰减造成的伪峰）。
- **UCR 在线下载**：单序列 URL 仍未校准；在线路径需通过 `ANOMALY_LAB_UCR_SERIES_URL`（含 `{name}`）显式提供模板，否则只读缓存。

## Chunk 3 环境记录

- **torch 已安装成功**：`download.pytorch.org/whl/cpu` 实测可达，安装 `torch 2.15.0+cpu`（cp312），未使用系统 Python 3.14 的 CUDA 版。
- **chronos 未安装**：`chronos-forecasting` 与本地权重均缺失，`compare` 中 Chronos 行记录 `ChronosUnavailable` 并跳过，不阻塞统计 + 自训深度两方对比。
- **深度模型训练数据**：CLI 默认用前 24 条合成序列训练 TCN/LSTM，模型缓存到 `data/cache/models/`。
- **compare 对照**：61 行（统计 8 个检测器 + TCN/LSTM + Chronos 跳过行）；STL 单次检测约 31ms，其余统计检测器 <1ms，深度模型约 1.8ms/条。

## v1 验收与开放项（2026-10-29）

- **已达标**：全量测试通过；ruff 无告警；离线 smoke 通过；合规自检通过；形态分类 120/120；统计 + 自训练深度 + Chronos 跳过行的三方对照表可生成；报告可 diff。
- **UCR 在线下载未校准**：单序列 URL 形式仍未验证，在线模式必须显式提供 `ANOMALY_LAB_UCR_SERIES_URL`；默认走离线缓存。
- **Chronos 未纳入对比**：`chronos-forecasting` 与本地权重均缺失，对照表保留跳过原因。
- **深度模型未跑赢基线**：TCN F1=0.279、LSTM F1=0.458，均低于去趋势 IQR 的 0.510；原因包括只用 24 条序列训练、合成异常与训练分布差异大。结论仅限合成集。
- **阈值搜索偏乐观**：当前逐序列用真值搜索阈值，属于诊断用上限；真实上线需按时间切分校准集/测试集，禁止在测试段搜阈值。
- **Web 标注回路**：API 与页面已实现，自动化测试覆盖 API；浏览器刷选交互仅手工冒烟，未做 Playwright 端到端。
- **合规豁免**：`docs/DESIGN.md`、`docs/PLAN.md`、`docs/RESEARCH.md` 因讨论禁词本身而豁免扫描，属有意设计。

## 平台垂直切片（2026-10-29，第一版）

- **范围**：SQLite 单源 + SQL 指标（`$timefilter`）+ group by 拆序列 + 双向基线/上下界 + P1/P0 用户配置分级 + 内置定时调度 + 前端预览。详见 [PLATFORM.md](PLATFORM.md)。
- **调度语义**：重启后错过的窗口只补跑一次；失败也推进 `next_run_at`，避免重试风暴。
- **正确性修复（自查后）**：缺失值不再静默失效（引入 `missing_policy` 与「数据不足」状态）；时间语义改为显式声明 `time_format` + `source_timezone`（对应 CloudWatch 的 `MetricTimezone`），比较统一走 `julianday()`；SQLite 打开 WAL；preview 校验 run 归属；手动运行与调度并发时复用同一次 run；配置期校验频率；运行失败原因透传到 API。
- **告警规则表**：任务改为配置「倍数（缩放因子）→ 等级」规则列表（如 `1×→P2`、`3×→P1`），判定以异常分数为准、取命中的最高档；上下界带用最低档倍数；判定语义统一为「达到即命中」。

开放项（下一版候选）：

- [ ] **业务绝对值条件**：作为并行条件支持（如「值 > 50 记 P1」），主判定仍以异常分数为准
- [ ] 数据源插件化：Prometheus / InfluxDB（`Source.kind` 与 `sqlite_source` 已留边界）
- [ ] 预处理独立进程/worker，兑现内存隔离的初衷
- [ ] 上下界改成统计意义上的预测区间（分位数或残差分布标定）
- [ ] 多 worker 部署时的调度锁（当前按单进程设计）
- [ ] 序列级形态分类结果接入平台任务（离线分类器与平台未打通）
- [ ] 认证/多租户与运行结果保留策略（当前 runs 只增不删）

