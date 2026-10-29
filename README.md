# anomaly-lab

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()

一个端到端的时序异常检测实验室：**合成数据 → 形态分类 → 算法推荐 → 多类检测器 → 离线评测 → 回归报告 → Web 演示**。目标是完整走通工程闭环，并把每一步的取舍和数据都留下来。

> 结论先行：在自建合成集上，分类器 120/120 全对；检测器里去趋势 IQR 的总体 F1 最高（0.510），LSTM 次之（0.458），TCN 未跑赢简单基线（0.279）。这些数字只代表合成分布，不代表真实业务效果。

## 架构

```mermaid
flowchart LR
  A[合成数据 / 公开集] --> B[特征提取]
  B --> C[形态分类 + 算法推荐]
  A --> D[检测器族]
  D --> E[阈值搜索]
  E --> F[点级 / 区间级指标]
  F --> G[回测 + Bad Case 归因]
  G --> H[JSON / Markdown / 图]
  H --> I[FastAPI 标注与评估页]
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/ALGORITHMS.md](docs/ALGORITHMS.md)、[docs/DATA.md](docs/DATA.md)。

## 5 分钟快速开始

```bash
git clone <repo-url> anomaly-lab
cd anomaly-lab

# 依赖（国内网络默认走清华镜像，见 Makefile 的 PIP_INDEX）
make setup

# 深度模型需要 CPU 版 torch（可选；不装则自动跳过 TCN/LSTM）
uv pip install torch --index-url https://download.pytorch.org/whl/cpu

make generate     # 生成 120 条合成序列
make evaluate     # 用 IQR 检测并产出 reports/latest/report.md
make compare      # 统计 + 自训深度 + Chronos（不可用则跳过）对照表
make serve        # http://127.0.0.1:8000
```

端到端冒烟：

```bash
./scripts/smoke.sh
# 或离线模式：ANOMALY_LAB_OFFLINE=1 ./scripts/smoke.sh
```

## 数据

- **合成集（主力）**：6 种形态（平稳、周期、趋势、阶梯、高零值、稀疏事件）× 6 种异常（尖峰、上下文、漂移、频率突变、方差突变、平台断流），共 120 条、每条 500 点，随机种子可复现，真值逐点标注。
- **公开集（泛化验证）**：UCR 异常库按序列惰性加载，只读缓存，不拉全量 zip；离线时缺失缓存直接抛 `DatasetUnavailable`。公开集不参与调参。
- **人工标注**：Web 刷选后追加到 `data/annotations/{series_id}.jsonl`，每行一条记录（含 `created_at`）。

合成数据结论不等于真实分布结论，公开集仍需按场景校准。

## 算法

统一约定：**分数越大越异常**，且每个检测器显式声明 `score_type`（`zscore` / `pvalue` / `residual_ratio` / `prob`），阈值搜索按语义分桶，避免“把 p 值当 z 分数”的混用。

| 族 | 检测器 | 核心思想 |
|---|---|---|
| 统计 | IQR / MAD / ZScore | 稳健基线 + 绝对偏差标准化 |
| 统计 | Seasonal | 周期内同相位分组，组内中位数/MAD |
| 统计 | STLResidual | STL 分解后的残差 / 残差 MAD |
| 统计 | DeseasonalizedIQR | 先线性去趋势，再跑 IQR |
| 统计 | ChangePoint | 滑窗双样本 t 检验，`1 - p` 为概率 |
| 统计 | EventCount | 窗口非零事件数 vs 泊松基线 |
| 自训深度 | TCN / LSTM | 一维重构自编码器，重构误差归一为概率 |
| 预训练 | Chronos | 分位数预测区间的越界程度（权重不可用时跳过） |

## 评测结果（真实跑出，单次 CPU 测量）

120 条合成序列，逐条搜索阈值后按序列平均；`F1` 为点级，`Range-F1` 为区间级。

| 检测器 | Precision | Recall | F1 | Range-F1 | 单条延迟 |
|---|---:|---:|---:|---:|---:|
| DeseasonalizedIQR | 0.793 | 0.472 | **0.510** | 0.321 | 0.11 ms |
| STLResidual | 0.694 | 0.457 | 0.473 | 0.295 | 31.20 ms |
| ZScore | 0.780 | 0.418 | 0.465 | 0.294 | 0.02 ms |
| LSTM | 0.738 | 0.418 | 0.458 | 0.294 | 1.93 ms |
| Seasonal | 0.598 | 0.460 | 0.436 | 0.336 | 0.51 ms |
| IQR | 0.529 | 0.295 | 0.310 | 0.205 | 0.05 ms |
| MAD | 0.473 | 0.274 | 0.283 | 0.191 | 0.04 ms |
| TCN | 0.365 | 0.391 | 0.279 | 0.188 | 1.81 ms |
| ChangePoint | 0.165 | 0.665 | 0.207 | 0.247 | 129.61 ms |
| EventCount | 0.145 | 0.879 | 0.205 | 0.235 | 0.13 ms |
| Chronos | - | - | - | - | 跳过（无本地权重） |

形态分类：**100.00%（120/120）**；冒烟集 6/6。完整逐形态对照见 `reports/compare.md`。

## 一次真实迭代：把固定周期换成检测出的周期

- **问题**：`SeasonalDetector` 在 CLI 里固定 `period=24`，周期型序列的总体 F1 一直偏低。
- **归因**：合成周期型数据的真实周期在 24 和 48 之间变化；固定 24 会让部分序列相位分组错位，残差被抬高，阈值搜索也救不回来。
- **最小改动**：`fit` 时调用 `extract_features(...).dominant_period`，拿不到再回退 24；其余逻辑不动。
- **回归对比**（同一份 120 条数据，逐条搜索阈值）：

| 指标 | 固定 24 | 自适应周期 | 变化 |
|---|---:|---:|---:|
| 总体 F1 | 0.423 | 0.436 | +0.013 |
| 周期型 F1 | 0.588 | 0.667 | +0.079 |
| Range-F1 | 0.325 | 0.336 | +0.012 |

复现实验（报告写到临时目录后用 `diff_reports` 对比）：

```python
from anomaly_lab.data.loader import load_dataset
from anomaly_lab.detectors.statistical import SeasonalDetector
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.evaluation.report import build_report, diff_reports

series = load_dataset("data/synthetic")
before = backtest_detector(series, lambda: SeasonalDetector(period=24))
after = backtest_detector(series, lambda: SeasonalDetector())
build_report(before, "reports/iteration/before", "fixed 24")
build_report(after, "reports/iteration/after", "auto")
print(diff_reports("reports/iteration/before/report.json",
                   "reports/iteration/after/report.json"))
```

## 项目边界

- 不接实时流、不做在线学习、不做告警编排；只做离线可复现的检测与评测。
- 合成集的 100% 分类准确率不代表真实指标；真实场景需要重新标注、校准阈值。
- 公开集只做泛化验证，UCR 单序列 URL 尚未校准，默认离线缓存模式。
- Chronos 权重未纳入本次对比；`compare` 会显式记录跳过原因。
- 不使用任何现职公司的内部数据、代码、文档或系统命名；`compliance-check` 会扫描仓库。

## License

MIT，见 [LICENSE](LICENSE)。
