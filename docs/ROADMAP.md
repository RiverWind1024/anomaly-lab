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
