# anomaly-lab

> 时序异常检测全流程学习项目 —— 形态分类 → 算法推荐 → 多族检测器 → 离线评测闭环 → Bad Case 归因 → 回归对比

**状态：设计已批准，实施计划就绪（尚未开工）**

| 文档 | 内容 |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md) | 设计文档：目标、架构、算法清单、数据策略、里程碑、风险 |
| [`docs/PLAN.md`](docs/PLAN.md) | 实施计划：4 个 Chunk、约 25 个 Task、逐步 TDD 步骤与验收命令 |
| [`docs/RESEARCH.md`](docs/RESEARCH.md) | 环境 / 网络 / 数据集 / 算法实测调研（含 2026-10-28 可达性数据） |

## 一句话

把「指标形态分类 → 算法选型 → 检测 → 标注 → 回测 → 评估 → 归因 → 迭代」这条完整链路，
在**合成数据 + 公开数据集**上自己从零打通一遍，并让它每次改动都能量化对比。

## 合规声明

本项目**不使用任何现职公司的内部数据、内部代码、内部文档、内部指标口径或内部系统命名**。
只使用自建合成数据、公开数据集（UCR 等）与公开实现（statsmodels / scikit-learn / PyTorch / chronos-forecasting）。
仓库内置 `anomaly-lab compliance-check` 命令做自动自检。

## License

MIT
