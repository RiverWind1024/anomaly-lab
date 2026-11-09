# RESEARCH · 环境 / 数据集 / 算法调研（2026-10-28 实测）

> 本文记录**实测结果**而非推测结论。所有可达性数据均为 2026-10-28 当日 curl 探测。
> 网络环境不稳定 → **任何依赖外网的步骤都必须有降级路径**。

---

## 1. 本机环境

| 项 | 实测值 | 影响 |
|---|---|---|
| 系统 Python | **3.14.7**（`/usr/lib64/python3.14`） | statsmodels 未安装；3.14 的科学计算 wheel 覆盖不稳 → **不用它建项目** |
| numpy | 2.4.4 | ✅ |
| pandas | 3.0.2 | ✅ |
| scipy | 1.17.1 | ✅ |
| scikit-learn | 1.8.0 | ✅ |
| matplotlib | 3.10.9 | ✅ |
| torch | 2.12.0+cu130 | ✅（系统已装 CUDA 版；项目内用 CPU 版） |
| fastapi | 0.136.1 | ✅ |
| statsmodels | **未安装** | STL / ADF 必需 → 项目 venv 装 |
| uv | `~/.local/bin/uv` | ✅ 用于建 3.12 venv |
| CPU | 16 核 | 足够并行评估 + CPU 训练 TCN |
| 内存 | 14 GB | 足够 |
| 磁盘 | 731 GB 空闲 | 足够 |

**结论**：用 `uv python install 3.12` + `uv venv --python 3.12` 建独立环境；
`uv pip install torch --index-url https://download.pytorch.org/whl/cpu` 装 CPU 版 torch（体积小很多）。

---

## 2. 网络可达性实测（决定了数据层设计）

| URL / 源 | 结果 | 说明 |
|---|---|---|
| `https://www.cs.ucr.edu/~eamonn/time_series_data_2018/UCR_TimeSeriesAnomalyDatasets2021.zip` | **HTTP 206 ✅**（zip 正常，前 1MB 下载 207 KB） | UCR 异常检测库可用，**但速度仅 ~10 KB/s** |
| `https://zenodo.org/api/records/...` | HTTP 200 ✅ | 通用镜像/备份 |
| `https://pypi.org/pypi/chronos-forecasting/json` | HTTP 200 ✅ | 2.3.2，Apache-2.0 |
| `https://pypi.org/pypi/statsmodels/json` | **超时/失败**（网络抖动） | 需重试或换源 |
| `https://raw.githubusercontent.com/numenta/NAB/...` | **超时 ❌** | GitHub raw 不可依赖 |
| `https://huggingface.co/api/datasets/...` | **超时 ❌**（历史可达，不稳定） | HF 不可依赖（Chronos 权重有风险） |
| `https://github.com/...` | **超时 ❌** | 不可依赖 |
| `https://api.github.com/...` | 可达 ✅ | 只读 API 可用 |

### 2.1 由实测推出的硬约束

1. **不拉全量数据集** —— 10 KB/s 下 UCR 全量（数百 MB）不可行 → **按序列惰性下载**，只取 20–40 条
2. **多镜像 + 本地缓存 + 断点续传** —— `.cache/datasets/`，记录来源 URL 与校验值
3. **主流程 100% 离线可跑** —— 合成数据 + 统计基线不依赖任何外网
4. **Chronos 权重必须可降级** —— HF 不稳 → 拿不到就跳过并在报告标注 `skipped`
5. **README 的快速开始不能依赖下载** —— 首次体验必须是 clone → 合成数据 → 出报告

---

## 3. 公开数据集候选评估

| 数据集 | 内容 | 标注 | 可达 | 定位 |
|---|---|---|---|---|
| **UCR Anomaly Archive 2021** | 250+ 真实单变量序列，训练/测试分离 | ✅ 异常区间标注 | ✅ 慢 | **主力**：真实分布 + 真值，用来验证泛化 |
| NAB（Numenta） | 58 个真实时序 | ✅ 标注 | ❌ raw 超时 | 备选（需镜像） |
| SKAB | 工业传感器 34 序列 | ✅ 标注 | ⚠️（HF 路径不通） | 备选 |
| Yahoo WebScope S5 | 真实业务指标 A1–A4 | 部分标注 | 需注册 | 暂不用（获取成本高） |
| NASA SMAP / MSL | 遥测多变量 | ✅ 标注 | 需镜像 | v2 考虑（多变量） |
| ETT | 电力温度 7 变量 | 异常无标注 | ⚠️ | 适合预测不适合异常检测 |
| Monash Archive | 30+ 多频率数据集 | 少 | ❌ pypi 404 | 备选 |

**结论**：v1 只做 **UCR**（20–40 条精选），其余进 ROADMAP。

### 3.1 UCR 使用注意

- 每个序列是独立文件（含 `values` 与异常区间标注），**按需下载**而非全量 zip
- 序列长度/频率差异大 → 数据层要按 `SeriesBundle` 归一（统一 timestamps + freq，缺失用 NaN）
- UCR 标注是**区间**，人工标注也是区间 → 评估需区间重叠指标（D3）

---

## 4. 算法调研与选型

### 4.1 统计基线（自己实现）

| 方法 | 复杂度 | 对形态的敏感点 | 备注 |
|---|---|---|---|
| IQR | O(n) | 平稳/近平稳 | 分位数法，抗离群 |
| MAD | O(n log n) | 平稳 + 尖峰 | 中位数绝对偏差，比 σ 更鲁棒 |
| 3σ / Z-score | O(n) | 仅近似平稳 | 朴素基线，用于对照 |
| STL + 残差阈值 | O(n) | 趋势 + 周期 | statsmodels；**周期长度必须由分类器给出** |
| 季节性感知阈值 | O(n·k) | 强周期 | 按"同一时刻跨周期"分组统计 |
| 变点检测（CUSUM / 二分） | O(n log n) | 阶梯 / 漂移 | 对突变敏感 |

### 4.2 深度模型

| 模型 | 参数量级 | CPU 训练可行 | 备注 |
|---|---|---|---|
| **TCN** | 0.1–0.5M | ✅ 很快 | 膨胀因果卷积，异常检测常用强基线，首选 |
| **LSTM** | 0.3–1M | ✅ 可 | 与 TCN 对比"递归 vs 卷积" |
| DeepAR-lite | 1–5M | ⚠️ 慢 | v2 考虑 |
| **Chronos (chronos-t5-tiny)** | ~8M | ✅ 推理快 | **Apache-2.0，pip 可装**；权重来自 HF（不稳定 → 必须降级） |

**验证策略**：合成数据训练（含异常段），在**留出合成集** + **UCR** 上评估 → 避免自评自。

### 4.3 形态分类特征（自己实现，优先可解释）

| 特征 | 方法 | 判别什么 |
|---|---|---|
| 平稳性 | ADF 检验（statsmodels） | 平稳型 vs 趋势型 |
| 周期性 | 自相关函数峰值 + 显著性 | 周期型；给出周期长度 |
| 零值比例 | 零值计数 / 总数 | 高零值比例型 |
| 稀疏性 | 非零样本数、事件成簇性 | 稀疏事件型 |
| 阶跃性 | 窗口均值变点统计量 | 阶梯型 |
| 噪声水平 | 高频残差能量占比 | 噪声爆炸 vs 平稳 |
| 趋势强度 | 线性/分段回归斜率显著��� | 趋势型 |

> 设计原则：**可解释性优先**。分类结果必须能给出"因为 ADF 平稳且自相关无显著峰 → 判为平稳型 → 推荐 IQR"这样的链条。机器学习分类器（v2）作为对照，不作主路径。

---

## 5. 已确认可用的库

| 库 | 版本 | 许可 | 用途 |
|---|---|---|---|
| chronos-forecasting | 2.3.2 | Apache-2.0 | 预训练时序模型 |
| numpy | 2.x | BSD | 数值 |
| pandas | 2.x | BSD | 数据帧 |
| scipy | 1.x | BSD | 统计检验 |
| statsmodels | 0.14.x | BSD | STL / ADF / seasonal_decompose |
| scikit-learn | 1.8 | BSD | 指标、特征、分组对比 |
| PyTorch | 2.x | BSD | TCN / LSTM |
| FastAPI | 0.136 | MIT | Web |
| uvicorn | — | BSD | ASGI |
| Jinja2 | — | BSD | 模板 |
| ECharts | 5.x | Apache-2.0 | 前端图表（CDN） |
| pytest / hypothesis | — | MIT | 测试 / 属性测试 |
| joblib | — | BSD | 并行 |
| matplotlib | 3.10 | PSF-like | 离线出图 |

**开源友好**：全部 permissive 许可（MIT/BSD/Apache-2.0）→ 本项目可 MIT 授权公开。

---

## 6. 待实现时再验证的事项

- [ ] `uv python install 3.12` 能否成功（uv 可下载列表里 3.14/3.15/3.16 可见，3.12 应同理）
- [ ] `uv pip install statsmodels`（3.12 wheel）能否拉下来
- [ ] `download.pytorch.org/whl/cpu` 是否可达（不可达则复用系统 torch 2.12）
- [ ] UCR **单序列文件**的真实 URL 形式（总 zip 可达不等于单文件 URL 可达）
- [ ] `chronos-t5-tiny` 权重从 HF 拉取的实际成功率与耗时
- [ ] ECharts CDN 在面试演示环境（可能是别人的网络）是否可达 → **考虑本地 vendor 一份 js 文件**
