# anomaly-lab v1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成一个可离线跑通的时序异常检测全流程学习项目：合成数据 → 指标形态分类 → 算法推荐 → 多类检测器（统计 / 自训深度 / 预训练）→ 离线评测闭环 → Bad Case 归因 → 回归对比报告 → 轻量 Web 标注与评估页。

**Architecture:** 五层单向依赖（L1 数据 → L2 形态分类 → L3 检测器 → L4 评估闭环 → L5 CLI/Web）。层间只通过 `SeriesBundle`（数据契约）与 `DetectionResult`（检测契约）通信；L3 全部实现同一 `Detector` 协议并**显式声明分数语义**（`zscore` / `pvalue` / `residual_ratio` / `prob`），L4 按语义分桶搜索阈值，从而保证不同算法可公平对比。

**Tech Stack:** Python 3.12（uv 独立 venv）· numpy / pandas / scipy / statsmodels / scikit-learn / PyTorch(CPU) · chronos-forecasting 2.3.2 (Apache-2.0) · FastAPI + Jinja2 + ECharts · pytest + hypothesis · joblib · SQLite + JSONL

---

## 0. 执行前须知（每个 chunk 开始前读一遍）

### 0.1 环境建立（只做一次）

```bash
cd ~/Project/anomaly-lab
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
```

**若 `uv python install 3.12` 失败** → 依次尝试：
1. `uv python install 3.13`（3.13 的 statsmodels wheel 覆盖也较好）
2. 直接用系统 Python 3.14（`python3.14 -m venv .venv`），并**跳过依赖 statsmodels 的任务**（Task 1.4 的 ADF、Task 2.3 的 STL），改用手写 ADF 近似与滑动去趋势替代 —— 在 `docs/ROADMAP.md` 记录降级
3. 以上都不行 → 停下来报告，不要硬凑

**若 `uv pip install torch --index-url https://download.pytorch.org/whl/cpu` 不可达** → 用系统已装的 torch 2.12.0+cu130（`pip install -e ".[dev]"` 不带 torch 依赖，安装后 `python -c "import torch; print(torch.__version__)"` 验证）。

### 0.2 网络纪律（实测：GitHub raw / HF 时通时不通，UCR 仅 10 KB/s）

- **任何任务不得假设外网可用**。每个涉及外网的步骤都必须有降级路径。
- UCR 数据集**只按序列惰性下载**，不拉全量 zip。
- 若 `download.pytorch.org` 或 HF 不可达 → 对应任务标记 `skipped` 并在 `docs/ROADMAP.md` 记录，**不阻塞后续任务**。

### 0.3 硬红线（不可越过）

> **绝对禁止使用现职公司的任何内部数据、内部代码、内部文档、内部告警规则、内部指标口径、内部系统命名。**
> 本项目只允许：自建合成数据 + 公开数据集（UCR 等）+ 公开实现（statsmodels / sklearn / PyTorch / chronos）。
> 每个 chunk 结束前跑一次 `make compliance-check`（Task 4.6 实现）确认无泄漏。

### 0.4 工作方式

- 每个 Task 结束**必须 commit**（commit message 用下面的模板）
- 严格 TDD：先写失败测试 → 跑测试确认失败 → 最小实现 → 跑测试确认通过 → commit
- 任务之间不要交叉修改文件；如果发现需要改前一个 Task 的文件，先停下说明原因
- 实现过程中发现设计与代码冲突 → **改代码向设计靠拢**；确实是设计缺陷 → 记录到 `docs/ROADMAP.md` 并继续，在 chunk 汇报时提出

---

## Chunk 1: 骨架 + 合成数据 + 形态分类

> 产出：`anomaly-lab generate` 能造出 6 类形态的可复现数据集；`anomaly-lab classify` 能判形态并给推荐算法。**这一 chunk 结束后项目已可运行、可演示。**

### Task 1.1: 项目骨架与数据契约

**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `.gitignore`
- Create: `src/anomaly_lab/__init__.py`
- Create: `src/anomaly_lab/config.py`
- Create: `src/anomaly_lab/contracts.py`
- Create: `tests/test_contracts.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "anomaly-lab"
version = "0.1.0"
description = "时序异常检测全流程学习项目：形态分类 → 算法推荐 → 多类检测器 → 离线评测闭环"
readme = "README.md"
requires-python = ">=3.12,<3.13"
license = { text = "MIT" }
dependencies = [
  "numpy>=2.0",
  "pandas>=2.2",
  "scipy>=1.13",
  "statsmodels>=0.14",
  "scikit-learn>=1.5",
  "matplotlib>=3.8",
  "joblib>=1.4",
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "jinja2>=3.1",
  "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0", "hypothesis>=6.100", "ruff>=0.4"]
torch = ["torch>=2.2"]
chronos = ["chronos-forecasting>=2.3"]

[project.scripts]
anomaly-lab = "anomaly_lab.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/anomaly_lab"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: 写 .gitignore**

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
data/synthetic/
data/cache/
data/annotations/
.cache/
notebooks/.ipynb_checkpoints/
reports/
```

- [ ] **Step 3: 写 Makefile**

```makefile
PY := .venv/bin/python
PIP := uv pip

.PHONY: setup test lint generate classify detect evaluate compare report serve compliance-check clean

setup:
	uv python install 3.12
	uv venv --python 3.12
	$(PIP) install -e ".[dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests

generate:
	$(PY) -m anomaly_lab.cli generate --n 120 --seed 42

classify:
	$(PY) -m anomaly_lab.cli classify --eval

detect:
	$(PY) -m anomaly_lab.cli detect --detector iqr

evaluate:
	$(PY) -m anomaly_lab.cli evaluate --report reports/latest

compare:
	$(PY) -m anomaly_lab.cli compare

report:
	$(PY) -m anomaly_lab.cli report --out reports/summary.md

serve:
	$(PY) -m anomaly_lab.cli serve --port 8000

compliance-check:
	$(PY) -m anomaly_lab.cli compliance-check

clean:
	rm -rf .pytest_cache .ruff_cache reports data/synthetic data/cache
	find . -name __pycache__ -type d -exec rm -rf {} +
```

- [ ] **Step 4: 写 src/anomaly_lab/contracts.py**

```python
"""贯穿全流程的唯一数据契约（L1 出，L2/L3/L4 都用它）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

LabelSource = Literal["synthetic", "public", "human", "none"]
ScoreType = Literal["zscore", "pvalue", "residual_ratio", "prob"]
MetricClass = Literal[
    "stationary", "periodic", "trending", "step", "high_zero_ratio", "sparse_event"
]


@dataclass(frozen=True, eq=False)
class SeriesBundle:
    """一条时序及其标注与元信息。"""

    series_id: str
    values: np.ndarray
    timestamps: np.ndarray
    freq: str
    labels: np.ndarray | None = None
    label_source: LabelSource = "none"
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.values.ndim != 1:
            raise ValueError("values 必须是一维")
        if len(self.values) != len(self.timestamps):
            raise ValueError("values 与 timestamps 长度不一致")
        if self.labels is not None and len(self.labels) != len(self.values):
            raise ValueError("labels 与 values 长度不一致")

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def has_labels(self) -> bool:
        return self.labels is not None and self.label_source != "none"

    def anomaly_indices(self) -> np.ndarray:
        if self.labels is None:
            return np.zeros(self.n, dtype=bool)
        return self.labels.astype(bool)


@dataclass(frozen=True, eq=False)
class DetectionResult:
    """一次检测的输出。`score_type` 决定分数语义，评估层按语义分桶搜阈值。"""

    series_id: str
    scores: np.ndarray
    score_type: ScoreType
    is_anomaly: np.ndarray
    threshold: float
    detector: str
    elapsed_ms: float

    def __post_init__(self) -> None:
        if len(self.scores) != len(self.is_anomaly):
            raise ValueError("scores 与 is_anomaly 长度不一致")
```

- [ ] **Step 5: 写 src/anomaly_lab/config.py**

```python
"""全局配置：路径、默认参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SEED = 42


@dataclass
class Config:
    root: Path = field(default_factory=lambda: Path.cwd())
    data_dir: Path = field(default_factory=lambda: Path("data"))
    cache_dir: Path = field(default_factory=lambda: Path(".cache"))
    reports_dir: Path = field(default_factory=lambda: Path("reports"))
    seed: int = int(os.environ.get("ANOMALY_LAB_SEED", DEFAULT_SEED))

    @property
    def synthetic_dir(self) -> Path:
        return self.data_dir / "synthetic"

    @property
    def public_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "public"

    @property
    def annotations_dir(self) -> Path:
        return self.data_dir / "annotations"

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.synthetic_dir,
            self.public_cache_dir,
            self.annotations_dir,
            self.reports_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


CONFIG = Config()
```

- [ ] **Step 6: 写 src/anomaly_lab/__init__.py**

```python
"""anomaly-lab：时序异常检测全流程学习项目。"""

__version__ = "0.1.0"
```

- [ ] **Step 7: 写失败测试 tests/test_contracts.py**

```python
import numpy as np
import pytest

from anomaly_lab.contracts import DetectionResult, SeriesBundle


def _bundle(**kw):
    base = dict(
        series_id="s1",
        values=np.arange(10.0),
        timestamps=np.arange(10).astype("datetime64[ns]"),
        freq="1min",
    )
    base.update(kw)
    return SeriesBundle(**base)


def test_series_bundle_roundtrip():
    b = _bundle()
    assert b.n == 10
    assert not b.has_labels
    assert b.anomaly_indices().sum() == 0


def test_series_bundle_rejects_length_mismatch():
    with pytest.raises(ValueError, match="长度不一致"):
        _bundle(labels=np.zeros(3, dtype=np.int8))


def test_series_bundle_rejects_2d_values():
    with pytest.raises(ValueError, match="一维"):
        _bundle(values=np.zeros((3, 3)))


def test_detection_result_rejects_length_mismatch():
    with pytest.raises(ValueError, match="长度不一致"):
        DetectionResult(
            series_id="s1",
            scores=np.zeros(5),
            score_type="zscore",
            is_anomaly=np.zeros(4, dtype=bool),
            threshold=1.0,
            detector="iqr",
            elapsed_ms=1.0,
        )
```

- [ ] **Step 8: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_contracts.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'anomaly_lab'`（包还没装）

- [ ] **Step 9: 安装包并跑测试确认通过**

Run: `uv pip install -e ".[dev]" && .venv/bin/python -m pytest tests/test_contracts.py -v`
Expected: 4 passed

- [ ] **Step 10: 提交**

```bash
git add pyproject.toml Makefile .gitignore src tests
git commit -m "chore: project skeleton, data contracts, config"
```

---

### Task 1.2: 合成数据生成器（6 形态 × 6 异常注入）

**Files:**
- Create: `src/anomaly_lab/data/__init__.py`
- Create: `src/anomaly_lab/data/synthetic.py`
- Create: `tests/data/test_synthetic.py`

**参考实现要点（按此写，不要偏离）：**

6 种基础形态（每条序列默认长度 500，频率 `5min`）：

| 形态 | 生成方式 |
|---|---|
| `stationary` | `normal(mu, sigma)`，可加轻微 AR(1) 噪声 |
| `periodic` | `trend + A*sin(2πt/P + φ) + noise`，周期 P 从 {24, 48, 168} 采样 |
| `trending` | `a*t + b + noise`，a ~ U(0.02, 0.08) |
| `step` | 前段 `mu1`，后段 `mu2`（阶跃点在 30%~70% 之间） |
| `high_zero_ratio` | 以 0 为主（约 70%~90% 为 0），非零处服从正态 |
| `sparse_event` | 99% 为 0，少数点为孤立高斯脉冲（事件） |

6 种异常注入（作用在已生成的基础序列上，**必须记录注入区间**）：

| 异常类型 | 注入方式 |
|---|---|
| `spike` | 单点或连续 1~3 点加 `k*sigma`（k 取 4~8） |
| `contextual` | 在正常波动范围内但相对该时段局部水平明显偏离（如周期型序列的相位跳变） |
| `drift` | 从某点起整体水平线性漂移 |
| `freq_shift` | 周期型序列：从某点起周期变为 P/2 |
| `variance_shift` | 从某点起方差放大 3~6 倍 |
| `flatline` | 一段恒定值（传感器卡死） |

**生成器 API：**

```python
def generate_series(
    metric_class: str,
    n: int = 500,
    seed: int = 42,
    freq: str = "5min",
    n_anomalies: int = 3,
) -> SeriesBundle:
    """生成一条带真值标注的合成序列。异常区间写入 labels（1=异常）。"""
```

内部需要：
- `rng = np.random.default_rng(seed)`（**用 default_rng，不用 legacy RandomState**）
- 基础形态生成 + 注入异常，注入时记录 `meta["anomaly_types"] = [{"type": "spike", "start": 120, "end": 122}]`
- `labels` 为 int8，长度 n
- `meta` 含：`metric_class`、`seed`、`freq`、`base_params`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.data.synthetic import generate_series

CLASSES = ["stationary", "periodic", "trending", "step", "high_zero_ratio", "sparse_event"]


@pytest.mark.parametrize("cls", CLASSES)
def test_generated_series_shape_and_labels(cls):
    s = generate_series(cls, n=500, seed=1)
    assert s.n == 500
    assert s.label_source == "synthetic"
    assert s.labels is not None
    assert s.labels.dtype == np.int8
    assert s.meta["metric_class"] == cls
    # 真值必须非空（注入成功）
    assert s.anomaly_indices().sum() > 0


@pytest.mark.parametrize("cls", CLASSES)
def test_generation_is_reproducible(cls):
    a = generate_series(cls, n=300, seed=7)
    b = generate_series(cls, n=300, seed=7)
    c = generate_series(cls, n=300, seed=8)
    assert np.array_equal(a.values, b.values)
    assert np.array_equal(a.labels, b.labels)
    assert not np.array_equal(a.values, c.values)


def test_anomaly_intervals_match_labels():
    s = generate_series("stationary", n=500, seed=3, n_anomalies=4)
    intervals = s.meta["anomaly_types"]
    assert len(intervals) == 4
    for iv in intervals:
        assert iv["start"] >= 0 and iv["end"] < s.n
        # 标注必须与注入区间一致
        assert s.labels[iv["start"] : iv["end"] + 1].all() == 1


def test_flatline_anomaly_produces_constant_run():
    s = generate_series("stationary", n=400, seed=11, n_anomalies=1,
                        anomaly_types=["flatline"])
    iv = s.meta["anomaly_types"][0]
    seg = s.values[iv["start"] : iv["end"] + 1]
    assert np.allclose(seg, seg[0])


def test_no_anomaly_leaks_into_label_free_region():
    s = generate_series("periodic", n=500, seed=5)
    idx = s.anomaly_indices()
    # 至少 85% 的点应是非异常（保证任务有意义）
    assert idx.mean() < 0.15
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/data/test_synthetic.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'anomaly_lab.data'`

- [ ] **Step 3: 实现 src/anomaly_lab/data/synthetic.py**

实现要点：
- `_base_stationary / _base_periodic / _base_trending / _base_step / _base_high_zero_ratio / _base_sparse_event`，每个接受 `rng` 并返回 `(values, base_params)`
- `_inject_spike / _inject_contextual / _inject_drift / _inject_freq_shift / _inject_variance_shift / _inject_flatline`，每个接受 `(values, rng, **kw)` 并返回 `(values, start, end)`
- `generate_series` 里按 `n_anomalies` 随机选类型（若显式传 `anomaly_types` 则按序使用），**注入区间互不重叠**（重叠时把后一个往后推，推不出就换类型）
- `meta["anomaly_types"]` 记录 `{"type", "start", "end"}`
- timestamps：`np.arange(n).astype("datetime64[m]") * np.timedelta64(5, "m")`（或按 freq 解析）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/data/test_synthetic.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑一遍全量测试 + 提交**

```bash
.venv/bin/python -m pytest
git add src tests
git commit -m "feat: synthetic time-series generator with 6 metric classes and 6 anomaly types"
```

---

### Task 1.3: 形态特征提取

**Files:**
- Create: `src/anomaly_lab/classification/__init__.py`
- Create: `src/anomaly_lab/classification/features.py`
- Create: `tests/classification/test_features.py`

**必须实现的特征（函数级，每个一个职责）：**

| 函数 | 返回 | 说明 |
|---|---|---|
| `adf_statistic(values) -> (stat, pvalue)` | ADF 检验统计量与 p 值 | 用 statsmodels `adfuller`；长度不足或常数序列返回 `(nan, nan)` |
| `acf(values, nlags) -> np.ndarray` | 自相关序列 | 用 statsmodels 或手写 FFT；`nlags` 取 `min(n//4, 200)` |
| `dominant_period(acf_vals) -> int \| None` | 主周期长度 | 找 ACF 在 lag>1 的第一个显著局部峰（> 0.2 且为局部极大） |
| `zero_ratio(values) -> float` | 零值占比 | |
| `sparsity(values) -> float` | 非零占比 | |
| `changepoint_score(values, min_seg=20) -> float` | 变点强度 | 用二分法找使组间均值差最大的切点，归一化 |
| `trend_strength(values) -> float` | 趋势强度 | 线性回归斜率显著性（t 统计量绝对值，归一） |
| `noise_ratio(values, period=None) -> float` | 高频噪声占比 | 去趋势（或去季节）后残差能量 / 总能量 |
| `extract_features(values, freq=None) -> FeatureVector` | 汇总 | 返回 frozen dataclass |

`FeatureVector` 至少含：`adf_pvalue`、`dominant_period`、`zero_ratio`、`sparsity`、`changepoint_score`、`trend_strength`、`noise_ratio`、`mean`、`std`、`acf_peak_lag1`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.classification.features import (
    adf_statistic,
    change_point_score,
    dominant_period,
    extract_features,
    zero_ratio,
)


def test_adf_on_stationary_is_significant():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 400)
    _, p = adf_statistic(x)
    assert p < 0.05


def test_adf_on_trend_is_not_significant():
    t = np.arange(400)
    x = 0.05 * t + np.random.default_rng(1).normal(0, 1, 400)
    _, p = adf_statistic(x)
    assert p > 0.05


def test_dominant_period_detects_sine():
    t = np.arange(1000)
    x = np.sin(2 * np.pi * t / 50)
    assert dominant_period(np.correlate(x - x.mean(), x - x.mean(), "full")[999:]) == 50


def test_zero_ratio():
    x = np.array([0.0, 0.0, 1.0, 0.0, 2.0])
    assert zero_ratio(x) == pytest.approx(0.6)


def test_changepoint_score_high_for_step():
    x = np.concatenate([np.zeros(200), np.ones(200) * 10])
    assert change_point_score(x) > 0.5


def test_extract_features_returns_finite_values():
    rng = np.random.default_rng(2)
    f = extract_features(rng.normal(0, 1, 300))
    for v in (f.adf_pvalue, f.zero_ratio, f.sparsity, f.noise_ratio, f.std):
        assert np.isfinite(v)


def test_extract_features_handles_constant_series():
    f = extract_features(np.ones(100))
    assert f.std == pytest.approx(0.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/classification/test_features.py -v`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现 features.py**

实现要点：
- `adf_statistic` 捕获 `statsmodels` 的异常（长度不足、常数序列）→ 返回 `(nan, nan)`
- `dominant_period` 用 ACF 数组，找 `lag >= 2` 中值 > 0.2 的第一个**局部极大**点；若周期为 1 视为无周期返回 `None`
- `change_point_score`：二分搜索最优切点，`score = |mean_left - mean_right| / (std + eps)`，再归一到 `[0, 1]`（用 `tanh`）
- `extract_features` 组装 `FeatureVector`（frozen dataclass，`eq=False`）
- **禁止**在特征函数里做异常检测（那是 L3 的事）

- [ ] **Step 4: 跑测试确认通过 + 提交**

```bash
.venv/bin/python -m pytest tests/classification/test_features.py -v
git add src tests
git commit -m "feat: metric feature extraction (adf, acf, changepoint, trend, sparsity)"
```

---

### Task 1.4: 形态分类器（6 类）+ 算法推荐

**Files:**
- Create: `src/anomaly_lab/classification/classifier.py`
- Create: `src/anomaly_lab/classification/recommend.py`
- Create: `tests/classification/test_classifier.py`

**分类规则（用 Task 1.3 的特征，按顺序判定，第一个命中即返回）：**

```
1. zero_ratio >= 0.6                    -> high_zero_ratio
2. sparsity >= 0.9 且 非零点数 <= 10      -> sparse_event
3. changepoint_score >= 0.5 且 trend_strength < 0.3  -> step
4. 存在显著主周期（dominant_period is not None）    -> periodic
5. adf_pvalue < 0.05 且 trend_strength < 0.3         -> stationary
6. 否则                                     -> trending
```

**`MetricClass` 判定结果的数据结构：**

```python
@dataclass(frozen=True, eq=False)
class ClassificationResult:
    series_id: str
    metric_class: MetricClass
    confidence: float          # 0~1，用到该规则的"证据强度"
    reasons: list[str]         # 可解释理由，如 "acf 峰在 lag=50 (r=0.81) -> 判为周期型"
    features: FeatureVector
    recommendation: Recommendation
```

**`recommend.py`：**

```python
@dataclass(frozen=True, eq=False)
class Recommendation:
    metric_class: MetricClass
    detectors: list[str]              # 候选检测器，按优先级
    params: dict[str, dict]           # 检测器名 -> 参数域（如 iqr 的 {"k": [1.5, 3.0]}）
    rationale: str
```

映射表（**必须与 DESIGN.md §4.4 一致**）：

| 形态 | detectors | params |
|---|---|---|
| stationary | `["iqr", "mad", "zscore"]` | iqr: k∈[1.5,3.0]；mad: k∈[3,5]；zscore: k∈[2,4] |
| periodic | `["seasonal", "stl_residual", "iqr"]` | seasonal: period←分类器给出，k∈[2,4] |
| trending | `["deseasonalized_iqr", "stl_residual"]` | k∈[1.5,3.0] |
| step | `["changepoint"]` | min_seg∈[10,30] |
| high_zero_ratio | `["iqr"]` | k∈[2,4]（零值单独建模在 v2） |
| sparse_event | `["event_count"]` | —— |

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.classification.classifier import classify
from anomaly_lab.data.synthetic import generate_series


@pytest.mark.parametrize(
    "cls,expected",
    [
        ("stationary", "stationary"),
        ("periodic", "periodic"),
        ("trending", "trending"),
        ("step", "step"),
        ("high_zero_ratio", "high_zero_ratio"),
        ("sparse_event", "sparse_event"),
    ],
)
def test_classifier_recovers_known_class(cls, expected):
    s = generate_series(cls, n=500, seed=17)
    r = classify(s)
    assert r.metric_class == expected


def test_classifier_gives_reasons_and_confidence():
    s = generate_series("periodic", n=500, seed=19)
    r = classify(s)
    assert r.reasons, "必须给出可解释理由"
    assert 0.0 < r.confidence <= 1.0
    assert r.recommendation.detectors


def test_classifier_overall_accuracy_is_at_least_90_percent():
    from anomaly_lab.data.synthetic import generate_series

    total = correct = 0
    for cls in ["stationary", "periodic", "trending", "step", "high_zero_ratio", "sparse_event"]:
        for seed in range(8):
            s = generate_series(cls, n=500, seed=1000 + seed)
            r = classify(s)
            total += 1
            correct += int(r.metric_class == cls)
    acc = correct / total
    assert acc >= 0.90, f"分类准确率 {acc:.2f} < 0.90"


def test_recommendation_matches_class():
    s = generate_series("periodic", n=500, seed=23)
    r = classify(s)
    assert r.recommendation.metric_class == "periodic"
    assert "seasonal" in r.recommendation.detectors
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/classification/test_classifier.py -v`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现 classifier.py 与 recommend.py**

实现要点：
- 规则按顺序判定，每条规则同时产出 `reasons`（如 `"ACF 主峰在 lag=50 (r=0.81) → 周期型"`）与 `confidence`（依据证据强度取 0.5~0.99）
- `confidence` 不允许瞎编：用**判别裕度** —— 例如周期判定用 `acf_peak - 0.2` 归一；统计型用 `min(pvalue_thresh*10, 1)` 之类可解释公式
- `classify()` 内部调用 `extract_features` → 规则 → `recommend_for(metric_class, features)`

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/classification/test_classifier.py -v`
Expected: 全部 PASS。**若"整体准确率 ≥ 90%"失败**：
  - 先看哪些类错了 → 调整**规则的判据阈值**（不是硬编码类别）
  - 仍然不行 → 在 `docs/ROADMAP.md` 记录"分类准确率未达标"并继续（**不要为了过测试而写死类别名**）

- [ ] **Step 5: 提交**

```bash
.venv/bin/python -m pytest
git add src tests
git commit -m "feat: metric-class classifier with explainable rules and detector recommendation"
```

---

### Task 1.5: 数据集落盘与 CLI 骨架（generate / classify）

**Files:**
- Create: `src/anomaly_lab/data/loader.py`（合成集保存/加载）
- Create: `src/anomaly_lab/cli.py`
- Create: `tests/test_cli.py`

**`loader.py` API：**

```python
def save_dataset(series: list[SeriesBundle], out_dir: Path) -> Path:
    """保存为 out_dir/<class>/<series_id>.npz + index.json"""

def load_dataset(data_dir: Path, classes: list[str] | None = None) -> list[SeriesBundle]:
    """加载 index.json 描述的全部序列"""

def build_synthetic_dataset(n_per_class: int = 20, seed: int = 42, out_dir: Path | None = None) -> list[SeriesBundle]:
    """生成 + 保存 + 返回"""
```

落盘格式：`np.savez_compressed` 存 `values` / `timestamps`（int64 纳秒）/ `labels`；`index.json` 存 `series_id` / `metric_class` / `label_source` / `meta` / `freq` / `n`。

**CLI（argparse，标准库，无额外依赖）：**

```
anomaly-lab generate --n 20 --seed 42 [--out data/synthetic]
anomaly-lab classify --eval [--data data/synthetic]
anomaly-lab detect --detector iqr [--data ...]        # Task 2 才实现，Chunk 1 先占位报错
anomaly-lab evaluate --report reports/latest
anomaly-lab compare
anomaly-lab report --out reports/summary.md
anomaly-lab serve --port 8000
anomaly-lab compliance-check
```

Chunk 1 阶段：`generate` 与 `classify` 真实可用；`detect`/`evaluate`/`compare`/`report`/`serve` 打印"未实现，见 PLAN Chunk 2/3/4"并 `sys.exit(2)`；`compliance-check` 真实实现（见 Task 4.6 的简化版：扫描仓库文本命中禁词表）。

- [ ] **Step 1: 写失败测试**

```python
import json
from pathlib import Path

import pytest

from anomaly_lab.cli import main


def test_generate_then_classify(tmp_path: Path, capsys):
    rc = main(["generate", "--n", "2", "--seed", "1", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "index.json").exists()

    rc = main(["classify", "--eval", "--data", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "分类准确率" in out or "accuracy" in out.lower()


def test_unimplemented_command_exits_2(tmp_path: Path):
    with pytest.raises(SystemExit) as e:
        main(["detect", "--data", str(tmp_path)])
    assert e.value.code == 2


def test_compliance_check_passes_on_clean_repo():
    rc = main(["compliance-check"])
    assert rc == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL —— `anomaly_lab.cli` 不存在

- [ ] **Step 3: 实现 loader.py 与 cli.py**

`cli.py` 要点：
- `main(argv=None) -> int` 返回退出码（便于测试直接调用）
- 子命令用 `argparse` 的 `add_subparsers(dest="command", required=True)`
- `generate`：`build_synthetic_dataset` → 打印数量与输出路径
- `classify --eval`：加载数据集 → 逐条 `classify()` → 打印**混淆矩阵**（6×6）与总体准确率；`--eval` 缺省时只打印每条的形态与理由
- `compliance-check`：扫描 `src/`、`docs/`、`README.md` 中的文本，命中禁词表（见 Task 4.6）则打印命中行并 `return 1`

- [ ] **Step 4: 跑测试确认通过 + 提交**

```bash
.venv/bin/python -m pytest
git add src tests
git commit -m "feat: dataset loader and CLI skeleton (generate/classify/compliance-check)"
```

---

### Task 1.6: Chunk 1 收尾 —— 公开集加载器（惰性下载）

**Files:**
- Create: `src/anomaly_lab/data/public.py`
- Create: `tests/data/test_public.py`
- Modify: `docs/ROADMAP.md`（新建）

**UCR 惰性下载设计：**

- 基址常量：`UCR_BASE = "https://www.cs.ucr.edu/~eamonn/time_series_data_2018/"`
- **不拉全量 zip**。按序列下载单文件 URL（实现时先探测真实单文件 URL 形式，见 RESEARCH.md §6）
- 缓存目录 `data/cache/public/<dataset>/<series_name>/`，下载后保存原始文件 + `meta.json`（来源 URL、下载时间、字节数、sha256）
- 断点续传：用 `Range` 头续传未完成的部分（实测服务器支持 206）
- 离线模式：`ANOMALY_LAB_OFFLINE=1` 时只读缓存，缺失则抛 `DatasetUnavailable`（可捕获的异常，不要用 `sys.exit`）
- **公开集只用于泛化验证，不用于调参**（写进模块 docstring）

- [ ] **Step 1: 写失败测试（全部离线可跑，不依赖网络）**

```python
import json
from pathlib import Path

import pytest

from anomaly_lab.data.public import DatasetUnavailable, load_public_series, series_available


def test_offline_mode_raises_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_OFFLINE", "1")
    with pytest.raises(DatasetUnavailable):
        load_public_series("some_series", cache_dir=tmp_path)


def test_offline_mode_reads_existing_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_OFFLINE", "1")
    d = tmp_path / "some_series"
    d.mkdir(parents=True)
    (d / "values.txt").write_text("1.0\n2.0\n3.0\n")
    (d / "meta.json").write_text(json.dumps({
        "source": "test", "n": 3, "freq": "1min",
        "anomaly_intervals": [[1, 1]],
    }))
    s = load_public_series("some_series", cache_dir=tmp_path)
    assert s.n == 3
    assert s.label_source == "public"
    assert s.anomaly_indices().sum() == 1


def test_series_available_reports_false_for_missing(tmp_path: Path):
    assert series_available("nope", cache_dir=tmp_path) is False
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 跑测试通过**

Run: `.venv/bin/python -m pytest tests/data/test_public.py -v`

实现要点：
- `DatasetUnavailable(RuntimeError)`
- `series_available(name, cache_dir) -> bool`
- `load_public_series(name, cache_dir, offline=None) -> SeriesBundle`：`offline` 默认读环境变量 `ANOMALY_LAB_OFFLINE`
- 解析 UCR 文本格式（每行一个值，异常区间在文件头或单独的 annotation 文件）—— **实现时以真实下载到的文件为准，先写一个宽松解析器并注释待校准**
- 公开集标签：`label_source="public"`，`labels` 为区间展开后的 int8 mask

- [ ] **Step 5: 提交**

```bash
.venv/bin/python -m pytest
git add src tests docs/ROADMAP.md
git commit -m "feat: UCR public dataset lazy loader with offline mode and cache"
```

**Chunk 1 完成标志**：`anomaly-lab generate --n 120 --seed 42` 产出 120 条序列；`anomaly-lab classify --eval` 打印混淆矩阵且准确率 ≥ 90%；`pytest` 全绿。

---

## Chunk 2: 检测器 + 评估闭环（★ 核心）

> 产出：`anomaly-lab evaluate` 产出带指标、Bad Case 归因与回归对比的报告。**这一 chunk 结束即达成 DESIGN.md 的 G1/G4。**

### Task 2.1: Detector 协议与分数语义

**Files:**
- Create: `src/anomaly_lab/detectors/__init__.py`
- Create: `src/anomaly_lab/detectors/base.py`
- Create: `tests/detectors/test_base.py`

**API：**

```python
ScoreType = Literal["zscore", "pvalue", "residual_ratio", "prob"]


class Detector(Protocol):
    name: str
    score_type: ScoreType

    def fit(self, series: SeriesBundle) -> "Detector": ...
    def score(self, series: SeriesBundle) -> np.ndarray: ...
    def detect(self, series: SeriesBundle, threshold: float | None = None) -> DetectionResult: ...
```

约定：
- `score()` 返回与输入等长的分数数组，**分数越大越异常**
- `score_type` 必须是 4 种语义之一（**这是 ADR-4 的强制点**）
- `detect()` 未给阈值时用该检测器的默认阈值（由 `evaluation.thresholds` 统一搜索或用内置默认）
- 所有检测器在 `fit` 时把拟合状态存到自身（不得跨序列共享状态）

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.base import VALID_SCORE_TYPES, validate_detector


def _series():
    return SeriesBundle(
        series_id="s",
        values=np.arange(100.0),
        timestamps=np.arange(100).astype("datetime64[ns]"),
        freq="1min",
    )


def test_valid_score_types_are_exactly_four():
    assert set(VALID_SCORE_TYPES) == {"zscore", "pvalue", "residual_ratio", "prob"}


def test_validate_detector_rejects_unknown_score_type():
    class Bad:
        name = "bad"
        score_type = "magic"

        def fit(self, s):
            return self

        def score(self, s):
            return np.zeros(len(s.values))

        def detect(self, s, threshold=None):
            raise NotImplementedError

    with pytest.raises(ValueError, match="score_type"):
        validate_detector(Bad())


def test_validate_detector_accepts_good_detector():
    class Good:
        name = "good"
        score_type = "zscore"

        def fit(self, s):
            return self

        def score(self, s):
            return np.zeros(len(s.values))

        def detect(self, s, threshold=None):
            raise NotImplementedError

    validate_detector(Good())
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: detector protocol with explicit score semantics"
```

---

### Task 2.2: 统计检测器（IQR / MAD / Z-score）

**Files:**
- Create: `src/anomaly_lab/detectors/statistical.py`
- Create: `tests/detectors/test_statistical.py`

**实现：**

```python
class IQRDetector:
    name = "iqr"
    score_type = "zscore"   # 实际用 (x - median) / (IQR / 1.349) 归一成近似 z 分数
    def __init__(self, k: float = 1.5, window: int | None = None): ...


class MADDetector:
    name = "mad"
    score_type = "zscore"   # 0.6745 * (x - median) / MAD
    def __init__(self, k: float = 3.5, window: int | None = None): ...


class ZScoreDetector:
    name = "zscore"
    score_type = "zscore"
    def __init__(self, k: float = 3.0, window: int | None = None): ...
```

规则：
- `window` 为 None → 用全序列统计量（全局阈值）；给了 window → 滚动窗口（**必须用 `pandas.Series.rolling`，且窗口内不含当前点以避免异常点自我拉高阈值**；用 `shift(1)`）
- `score` 返回归一化后的分数，**越大越异常**
- `detect` 用 `threshold`（默认 `k`）二值化
- 常数序列 → 分数全 0，不抛异常

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector, MADDetector, ZScoreDetector


@pytest.mark.parametrize("cls", [IQRDetector, MADDetector, ZScoreDetector])
def test_detector_finds_injected_spike(cls):
    s = generate_series("stationary", n=500, seed=31, n_anomalies=1, anomaly_types=["spike"])
    d = cls()
    res = d.fit(s).detect(s)
    assert res.is_anomaly.sum() > 0
    # 检出的点应与真值高度重合
    truth = s.anomaly_indices()
    hit = (res.is_anomaly & truth).sum()
    assert hit >= 1


@pytest.mark.parametrize("cls", [IQRDetector, MADDetector, ZScoreDetector])
def test_detector_on_clean_series_has_low_false_positive(cls):
    s = generate_series("stationary", n=500, seed=33, n_anomalies=0)
    res = cls().fit(s).detect(s)
    assert res.is_anomaly.mean() < 0.02


def test_iqr_uses_rolling_window_when_given():
    s = generate_series("trending", n=400, seed=35, n_anomalies=0)
    d = IQRDetector(k=1.5, window=100)
    res = d.fit(s).detect(s)
    # 滚动窗口下，趋势序列的误报应明显少于全局阈值
    assert res.is_anomaly.mean() < 0.10


def test_detector_result_metadata():
    s = generate_series("stationary", n=200, seed=37)
    res = IQRDetector().fit(s).detect(s)
    assert res.detector == "iqr"
    assert res.score_type == "zscore"
    assert res.elapsed_ms >= 0
    assert len(res.scores) == s.n
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

实现注意：
- MAD 为 0 时（常数或大量重复）→ 加 `eps` 防除零
- 滚动窗口用 `min_periods=max(10, window//4)`

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: statistical detectors (iqr, mad, zscore) with rolling window support"
```

---

### Task 2.3: 周期性 / 趋势 / 变点检测器

**Files:**
- Modify: `src/anomaly_lab/detectors/statistical.py`
- Create: `tests/detectors/test_advanced_statistical.py`

**实现：**

| 检测器 | name | score_type | 做法 |
|---|---|---|---|
| 周期感知阈值 | `seasonal` | `zscore` | 按"周期内同一相位"分组算中位数与 MAD，score = 偏离量 |
| STL 残差 | `stl_residual` | `residual_ratio` | `statsmodels.STL(period=p).fit()`，score = 残差绝对值 / 残差 MAD |
| 去趋势 IQR | `deseasonalized_iqr` | `zscore` | 先去线性趋势再走 IQR |
| 变点 | `changepoint` | `prob` | 滑窗内均值突变 → 用双样本 t 统计量归一为 `prob`（1 - p 值） |
| 事件计数 | `event_count` | `prob` | 滑动窗口内非零事件数 vs 泊松期望 → 异常概率 |

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import (
    ChangePointDetector,
    DeseasonalizedIQRDetector,
    EventCountDetector,
    SeasonalDetector,
    STLResidualDetector,
)


def test_seasonal_detector_finds_phase_anomaly():
    s = generate_series("periodic", n=1000, seed=41, n_anomalies=1,
                        anomaly_types=["contextual"])
    res = SeasonalDetector(period=50).fit(s).detect(s)
    assert res.is_anomaly.sum() > 0
    assert (res.is_anomaly & s.anomaly_indices()).sum() >= 1


def test_stl_residual_detector_works_on_trend():
    s = generate_series("trending", n=600, seed=43, n_anomalies=1,
                        anomaly_types=["spike"])
    res = STLResidualDetector(period=24).fit(s).detect(s)
    assert res.score_type == "residual_ratio"
    assert (res.is_anomaly & s.anomaly_indices()).sum() >= 1


def test_deseasonalized_iqr_reduces_false_positive_on_trend():
    s = generate_series("trending", n=600, seed=45, n_anomalies=0)
    plain = IQRDetector().fit(s).detect(s).is_anomaly.mean()
    deseason = DeseasonalizedIQRDetector().fit(s).detect(s).is_anomaly.mean()
    assert deseason <= plain


def test_changepoint_detector_detects_step():
    s = generate_series("step", n=500, seed=47, n_anomalies=0)
    res = ChangePointDetector(min_seg=20).fit(s).detect(s)
    assert res.score_type == "prob"
    assert res.is_anomaly.sum() > 0


def test_event_count_detector_on_sparse_series():
    s = generate_series("sparse_event", n=500, seed=49, n_anomalies=1,
                        anomaly_types=["spike"])
    res = EventCountDetector(window=50).fit(s).detect(s)
    assert (res.is_anomaly & s.anomaly_indices()).sum() >= 1
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: seasonal, stl-residual, deseasonalized, changepoint, event-count detectors"
```

---

### Task 2.4: 阈值搜索（按分数语义分桶）

**Files:**
- Create: `src/anomaly_lab/evaluation/__init__.py`
- Create: `src/anomaly_lab/evaluation/thresholds.py`
- Create: `tests/evaluation/test_thresholds.py`

**API：**

```python
@dataclass(frozen=True, eq=False)
class ThresholdResult:
    threshold: float
    precision: float
    recall: float
    f1: float
    n_flagged: int


def search_threshold(
    scores: np.ndarray,
    score_type: str,
    truth: np.ndarray,
    candidates: int = 200,
) -> ThresholdResult:
    """在候选阈值上搜索 F1 最优（并列时取召回更高者）。"""
```

规则：
- **按 `score_type` 分桶生成候选阈值**：
  - `zscore`：在 `[0, max_score]` 上均匀取 `candidates` 个
  - `pvalue` / `prob`：在 `[0, 1]` 上均匀取
  - `residual_ratio`：在 `[0, max_score]` 上均匀取
- 无真值（`truth` 全 None）→ 抛 `ValueError`（阈值搜索必须有真值）
- 精确率分母为 0 → 记 0（不是 1）

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.evaluation.thresholds import ThresholdResult, search_threshold


def test_search_finds_good_threshold():
    scores = np.array([0.0, 0.1, 5.0, 0.2, 6.0, 0.3])
    truth = np.array([0, 0, 1, 0, 1, 0], dtype=np.int8)
    r = search_threshold(scores, "zscore", truth)
    assert isinstance(r, ThresholdResult)
    assert r.recall == pytest.approx(1.0)
    assert r.f1 > 0.9


def test_threshold_search_requires_truth():
    with pytest.raises(ValueError):
        search_threshold(np.zeros(5), "zscore", None)


def test_zero_division_precision_is_zero():
    scores = np.array([1.0, 1.0])
    truth = np.array([0, 0], dtype=np.int8)
    r = search_threshold(scores, "zscore", truth)
    assert r.precision == 0.0


def test_prob_semantics_uses_unit_range():
    scores = np.linspace(0, 1, 50)
    truth = (scores > 0.8).astype(np.int8)
    r = search_threshold(scores, "prob", truth)
    assert 0.0 <= r.threshold <= 1.0
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: threshold search bucketed by score semantics"
```

---

### Task 2.5: 评估指标（点匹配 + 区间重叠）

**Files:**
- Create: `src/anomaly_lab/evaluation/metrics.py`
- Create: `tests/evaluation/test_metrics.py`

**必须实现的指标：**

| 指标 | 用途 |
|---|---|
| `precision_recall_f1(tp, fp, fn)` | 点级基础指标 |
| `point_adjusted_prf(pred, truth, delay=5)` | **点级 + 容忍延迟**（对齐真实告警场景：延迟 N 点内算命中） |
| `range_based_prf(pred_intervals, truth_intervals, beta=2)` | **区间级**（TSB-UAD 风格：命中率 + 误报率 → P/R/F1），对区间标注更公平 |
| `interval_iou(a, b)` | 单区间 IoU |
| `detection_delay(pred, truth)` | 首次检出的延迟（点级） |

区间表示统一用 `list[tuple[int, int]]`（闭区间，含端点）。

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.evaluation.metrics import (
    detection_delay,
    interval_iou,
    point_adjusted_prf,
    precision_recall_f1,
    range_based_prf,
)


def test_perfect_prediction():
    truth = np.array([0, 0, 1, 1, 0], dtype=np.int8)
    p, r, f = precision_recall_f1(pred=truth, truth=truth)
    assert (p, r, f) == (1.0, 1.0, 1.0)


def test_point_adjusted_tolerates_delay():
    truth = np.array([0, 0, 0, 1, 1, 0], dtype=np.int8)
    pred = np.array([0, 0, 0, 0, 1, 0], dtype=np.int8)  # 晚 1 点
    p, r, f = point_adjusted_prf(pred, truth, delay=2)
    assert r == pytest.approx(1.0)


def test_range_based_scores_overlap():
    pred = [(0, 4)]
    truth = [(0, 4)]
    p, r, f = range_based_prf(pred, truth)
    assert f == pytest.approx(1.0)


def test_range_based_penalizes_over_detection():
    pred = [(0, 9)]
    truth = [(0, 4)]
    p, r, f = range_based_prf(pred, truth)
    assert p < 1.0


def test_interval_iou():
    assert interval_iou((0, 10), (0, 10)) == pytest.approx(1.0)
    assert interval_iou((0, 10), (20, 30)) == pytest.approx(0.0)
    assert interval_iou((0, 10), (5, 15)) == pytest.approx(1 / 3)


def test_detection_delay():
    truth = np.array([0, 0, 1, 1], dtype=np.int8)
    pred = np.array([0, 0, 0, 1], dtype=np.int8)
    assert detection_delay(pred, truth) == 1
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: point and range-based evaluation metrics"
```

---

### Task 2.6: 回测器 + Bad Case 归因

**Files:**
- Create: `src/anomaly_lab/evaluation/backtest.py`
- Create: `src/anomaly_lab/evaluation/badcases.py`
- Create: `tests/evaluation/test_backtest.py`

**`backtest.py` API：**

```python
@dataclass(frozen=True, eq=False)
class BacktestRow:
    series_id: str
    metric_class: str
    detector: str
    score_type: str
    threshold: float
    precision: float
    recall: float
    f1: float
    range_f1: float
    n_truth: int
    n_pred: int
    elapsed_ms: float


def backtest_detector(
    series_list: list[SeriesBundle],
    detector_factory,
    use_searched_threshold: bool = True,
) -> list[BacktestRow]:
    """对每条序列跑检测器并计算指标。阈值按每条序列搜索（合成集有真值）。"""
```

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pytest

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.evaluation.badcases import attribute_badcases


def test_backtest_returns_one_row_per_series():
    series = [generate_series(c, n=300, seed=60 + i) for i, c in enumerate(
        ["stationary", "periodic", "trending"])]
    rows = backtest_detector(series, IQRDetector)
    assert len(rows) == 3
    for r in rows:
        assert 0.0 <= r.precision <= 1.0
        assert 0.0 <= r.recall <= 1.0
        assert r.n_truth > 0
        assert r.elapsed_ms >= 0


def test_badcase_attribution_produces_reasons():
    s = generate_series("periodic", n=600, seed=61, n_anomalies=1,
                        anomaly_types=["spike"])
    result = IQRDetector().fit(s).detect(s)
    cases = attribute_badcases(s, result)
    assert isinstance(cases, list)
    for c in cases:
        assert c.kind in {"false_positive", "false_negative"}
        assert c.reason
        assert c.indices is not None


def test_badcase_reasons_are_grouped_by_shape():
    s = generate_series("stationary", n=600, seed=63, n_anomalies=2)
    result = IQRDetector().fit(s).detect(s)
    cases = attribute_badcases(s, result)
    # 误报应能按形态分组（例如"周期性指标上的误报"）
    kinds = {c.group for c in cases}
    assert all(k for k in kinds)
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

**`badcases.py` 归因维度（每条 bad case 至少给出一个 group 与可读 reason）：**
- 位置：异常点位于序列前 10% / 中段 / 后 10%
- 形态：`s.meta["metric_class"]` 或分类器判出的形态
- 分数分布：真值点的分数分位数（说明"分数不够高"）
- 连续性：孤立点 vs 连续段（区分 spike 与 drift/flatline）

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: backtest runner and bad-case attribution"
```

---

### Task 2.7: 回归报告（JSON + Markdown + 图）

**Files:**
- Create: `src/anomaly_lab/evaluation/report.py`
- Create: `tests/evaluation/test_report.py`

**API：**

```python
def build_report(rows: list[BacktestRow], out_dir: Path, title: str = "") -> dict:
    """产出 report.json / report.md / figures/*.png，返回摘要 dict"""

def diff_reports(path_a: Path, path_b: Path) -> str:
    """对比两份 report.json，输出 Markdown 差异表（指标变化）"""
```

`report.json` 结构：
```json
{
  "generated_at": "...",
  "title": "...",
  "summary": {"by_detector": {...}, "by_metric_class": {...}, "overall": {...}},
  "rows": [ ... ]
}
```

`report.md` 含：总体表（按检测器）、分组表（按形态）、最差 10 条序列、Bad Case 摘要、图（每个检测器一张 P/R/F1 柱状图，按形态分组）。

- [ ] **Step 1: 写失败测试**

```python
import json
from pathlib import Path

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.evaluation.report import build_report, diff_reports


def test_build_report_writes_json_md_and_figures(tmp_path: Path):
    series = [generate_series(c, n=300, seed=70 + i) for i, c in enumerate(
        ["stationary", "periodic", "trending"])]
    rows = backtest_detector(series, IQRDetector)
    summary = build_report(rows, tmp_path, title="t")
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "figures").is_dir()
    data = json.loads((tmp_path / "report.json").read_text())
    assert "summary" in data and "rows" in data
    assert "overall" in summary


def test_diff_reports_shows_metric_change(tmp_path: Path):
    series = [generate_series("stationary", n=300, seed=80)]
    rows = backtest_detector(series, IQRDetector)
    build_report(rows, tmp_path / "a", title="a")
    build_report(rows, tmp_path / "b", title="b")
    md = diff_reports(tmp_path / "a" / "report.json", tmp_path / "b" / "report.json")
    assert "F1" in md or "f1" in md.lower()
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: regression report with json/markdown/figures and report diffing"
```

---

### Task 2.8: CLI 打通 detect / evaluate / report

**Files:**
- Modify: `src/anomaly_lab/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 补失败测试**

```python
def test_detect_and_evaluate_pipeline(tmp_path: Path, capsys):
    data = tmp_path / "data"
    out = tmp_path / "reports"
    assert main(["generate", "--n", "2", "--seed", "1", "--out", str(data)]) == 0
    assert main(["detect", "--detector", "iqr", "--data", str(data)]) == 0
    assert main(["evaluate", "--data", str(data), "--report", str(out)]) == 0
    assert (out / "report.json").exists()
    assert (out / "report.md").exists()
    out_text = capsys.readouterr().out
    assert "F1" in out_text or "f1" in out_text.lower()
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 CLI 三个子命令 → 4: 通过**

CLI 行为约定：
- `detect --detector <name>`：跑检测器，把 `DetectionResult` 存到 `data/cache/detections/<detector>/<series_id>.npz`（含 scores + threshold + score_type）
- `evaluate --data ... --report ...`：读检测结果 + 真值 → 回测 → 报告
- `report --out reports/summary.md`：汇总所有 `data/cache/detections/*` 出一张总表

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: CLI detect/evaluate/report commands wired to the evaluation loop"
```

**Chunk 2 完成标志**：`make evaluate` 产出 `reports/latest/report.md`（含总体表 + 分形态表 + Bad Case 摘要 + 图）；改一个检测器参数重跑，`report` 能 diff 出变化。

---

## Chunk 3: 深度模型（自训 + 预训练）

> 产出：TCN / LSTM / Chronos 三方公平对比。**可降级**：Chronos 权重不可达时自动跳过，不阻塞。

### Task 3.1: PyTorch 环境与 TCN 实现

**Files:**
- Create: `src/anomaly_lab/detectors/deep.py`
- Create: `tests/detectors/test_deep.py`
- Modify: `pyproject.toml`（加 `torch` 可选依赖到 dev）

- [ ] **Step 1: 确认 torch 可用**

Run: `.venv/bin/python -c "import torch; print(torch.__version__)"`
Expected: 打印版本号。**若失败** → 按 §0.1 的兜底方案处理，并在 ROADMAP 记录。

- [ ] **Step 2: 写失败测试**

```python
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.deep import TCNDetector, train_tcn


def test_tcn_training_reduces_loss(tmp_path):
    series = [generate_series("stationary", n=500, seed=90 + i, n_anomalies=0) for i in range(8)]
    result = train_tcn(series, epochs=3, seed=1, out_path=tmp_path / "tcn.pt")
    assert result.history[-1] < result.history[0]


def test_tcn_detector_scores_higher_on_anomalies(tmp_path):
    s = generate_series("stationary", n=500, seed=95, n_anomalies=1, anomaly_types=["spike"])
    train_tcn([generate_series("stationary", n=500, seed=100 + i, n_anomalies=0)
               for i in range(8)], epochs=2, seed=1, out_path=tmp_path / "tcn.pt")
    d = TCNDetector(model_path=tmp_path / "tcn.pt").fit(s)
    scores = d.score(s)
    truth = s.anomaly_indices()
    assert scores[truth].mean() > scores[~truth].mean()


def test_tcn_declares_prob_score_type(tmp_path):
    s = generate_series("stationary", n=300, seed=97, n_anomalies=0)
    train_tcn([s], epochs=1, seed=1, out_path=tmp_path / "tcn.pt")
    d = TCNDetector(model_path=tmp_path / "tcn.pt")
    assert d.score_type == "prob"
```

- [ ] **Step 3: 跑测试确认失败 → 4: 实现 → 5: 通过**

实现要点：
- `TCN`：`Conv1d(dilation=1,2,4,8,16)` 膨胀因果卷积 + `BatchNorm1d` + `ReLU` + 1×1 输出层，输入通道 1，隐层 32
- 训练目标：**重构误差**（一维自编码器思路）—— 异常点难以重构 → 重构误差大 → 分数高
- `train_tcn(series, epochs, seed, out_path)` 返回 `TrainingResult(history=[...], final_loss=..., path=...)`
- 训练用 CPU，`torch.manual_seed(seed)` 保证可复现
- `TCNDetector.score` → 逐点重构误差，**归一到 `[0,1]`**，`score_type="prob"`
- **必须缓存模型**（`out_path`），避免每次评估都重训

- [ ] **Step 6: 提交**

```bash
git add src tests pyproject.toml
git commit -m "feat: TCN anomaly detector with CPU training pipeline"
```

---

### Task 3.2: LSTM 对照实现

**Files:**
- Modify: `src/anomaly_lab/detectors/deep.py`
- Modify: `tests/detectors/test_deep.py`

- [ ] **Step 1: 写失败测试**（与 TCN 同构）
- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

实现要点：`LSTM(hidden=32, num_layers=1, batch_first=True)` + 线性头，同样走重构误差；与 TCN 共用训练循环（模板方法，避免重复代码）。

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: LSTM detector sharing the deep training pipeline"
```

---

### Task 3.3: Chronos 适配器（含降级）

**Files:**
- Create: `src/anomaly_lab/detectors/chronos.py`
- Create: `tests/detectors/test_chronos.py`

- [ ] **Step 1: 写失败测试（必须离线可跑）**

```python
import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.chronos import ChronosUnavailable, ChronosDetector, chronos_available


def _series():
    return SeriesBundle(
        series_id="s",
        values=np.sin(np.arange(200) / 10.0),
        timestamps=np.arange(200).astype("datetime64[ns]"),
        freq="1min",
    )


def test_chronos_available_returns_bool():
    assert isinstance(chronos_available(), bool)


def test_detector_raises_typed_error_when_unavailable(monkeypatch):
    monkeypatch.setattr("anomaly_lab.detectors.chronos.chronos_available", lambda: False)
    with pytest.raises(ChronosUnavailable):
        ChronosDetector().fit(_series())


def test_score_type_is_prob():
    assert ChronosDetector.score_type == "prob"
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

实现要点：
- `chronos_available()` → 尝试 `import chronos` **并**检查本地权重缓存（`~/.cache/huggingface/hub/models--amazon--chronos-t5-tiny` 之类）→ 都满足才 True
- `ChronosUnavailable(RuntimeError)`
- `ChronosDetector.score`：`chronos.forecast` 得到预测区间 → 分数 = 预测区间的**宽度**或超出区间的程度 → 归一到 `[0,1]`
- **不要在模块 import 时触发下载**（否则 `pytest` 会卡住）—— 全部延迟到 `fit`

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: chronos detector adapter with graceful degradation when weights unavailable"
```

---

### Task 3.4: 三方公平对比框架

**Files:**
- Create: `src/anomaly_lab/evaluation/compare.py`
- Create: `tests/evaluation/test_compare.py`

**API：**

```python
@dataclass(frozen=True, eq=False)
class CompareRow:
    detector: str
    score_type: str
    metric_class: str
    precision: float
    recall: float
    f1: float
    range_f1: float
    mean_elapsed_ms: float
    params: int | None
    skipped_reason: str | None


def compare_detectors(
    series_list: list[SeriesBundle],
    detector_specs: list[tuple[str, str, str]],
) -> list[CompareRow]:
    """detector_specs: [(display_name, module_path, class_name), ...]"""
```

- [ ] **Step 1: 写失败测试**

```python
from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.evaluation.compare import compare_detectors


def test_compare_returns_rows_for_available_detectors():
    series = [generate_series(c, n=300, seed=110 + i) for i, c in enumerate(
        ["stationary", "periodic", "trending"])]
    rows = compare_detectors(series, [
        ("IQR", "anomaly_lab.detectors.statistical", "IQRDetector"),
        ("MAD", "anomaly_lab.detectors.statistical", "MADDetector"),
    ])
    assert len(rows) >= 3
    for r in rows:
        assert r.detector in {"IQR", "MAD"}
        assert r.skipped_reason is None


def test_compare_records_skipped_reason_for_unavailable():
    series = [generate_series("stationary", n=200, seed=115)]
    rows = compare_detectors(series, [
        ("Chronos", "anomaly_lab.detectors.chronos", "ChronosDetector"),
    ])
    assert any(r.skipped_reason for r in rows)
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

实现要点：
- 动态导入 detector 类（`importlib`），实例化，捕获 `ChronosUnavailable` 与任何异常 → 记 `skipped_reason`
- 记录参数量（深度模型取 `sum(p.numel() for p in model.parameters())`）
- 延迟取平均（每个检测器跑 3 次取均值？**至少 1 次；报告里标注是单次测量**）

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: fair comparison framework across detector families"
```

### Task 3.5: CLI compare 命令

**Files:**
- Modify: `src/anomaly_lab/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 补失败测试** → **2: 确认失败** → **3: 实现** → **4: 通过** → **5: 提交**

`anomaly-lab compare --data ... --out reports/compare.md`：输出三方（可用时）对照表：指标 + 延迟 + 参数量 + 跳过原因。

```bash
git commit -m "feat: CLI compare command for cross-detector benchmark table"
```

**Chunk 3 完成标志**：`make compare` 产出对照表；至少两行（统计 + 自训深度），Chronos 可用则三行。

---

## Chunk 4: Web + 文档

### Task 4.1: FastAPI 骨架与静态资源

**Files:**
- Create: `src/anomaly_lab/web/__init__.py`
- Create: `src/anomaly_lab/web/app.py`
- Create: `src/anomaly_lab/web/templates/base.html`
- Create: `src/anomaly_lab/web/templates/index.html`
- Create: `src/anomaly_lab/web/static/style.css`
- Create: `src/anomaly_lab/web/static/echarts.min.js`（本地 vendor 一份，见 RESEARCH.md §6）
- Create: `tests/web/test_app.py`

- [ ] **Step 1: 写失败测试**

```python
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_index_page_loads():
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "anomaly-lab" in r.text


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/api/health").json() == {"status": "ok"}
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

要点：`create_app()` 返回 FastAPI 实例；`/api/health` 返回固定 JSON；`/api/series` 列出可用序列；模板用 Jinja2。

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: FastAPI skeleton with local echarts asset"
```

### Task 4.2: 标注页（波形 + 刷选标注）

**Files:**
- Modify: `src/anomaly_lab/web/app.py`
- Create: `src/anomaly_lab/web/templates/annotate.html`
- Create: `src/anomaly_lab/web/static/annotate.js`
- Create: `tests/web/test_annotate.py`

- [ ] **Step 1: 写失败测试**

```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_save_annotation_writes_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    r = client.post("/api/annotate/s1", json={
        "intervals": [{"start": 10, "end": 12, "type": "spike"}],
    })
    assert r.status_code == 200
    files = list(tmp_path.rglob("s1.jsonl"))
    assert files
    rec = json.loads(files[0].read_text().splitlines()[0])
    assert rec["start"] == 10 and rec["end"] == 12


def test_list_annotations(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.post("/api/annotate/s2", json={"intervals": [{"start": 1, "end": 2, "type": "drift"}]})
    r = client.get("/api/annotate/s2")
    assert r.status_code == 200
    assert len(r.json()["intervals"]) == 1
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

后端：
- `POST /api/annotate/{series_id}`：body `{"intervals": [{"start","end","type"}]}` → **追加**写入 `data/annotations/{series_id}.jsonl`（每行一条记录，含 `created_at`）
- `GET /api/annotate/{series_id}`：读回全部记录
- `GET /api/series/{series_id}/values`：返回 `{timestamps, values}`（供前端画图）

前端（`annotate.js`）：
- ECharts 折线图 + `dataZoom`（缩略导航）
- 开启 `brush` 框选 → 弹窗选类型 → 调 POST
- 已标注区间用 `markArea` 叠加显示
- **不引任何前端框架**

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: web annotation page with brush selection and jsonl persistence"
```

### Task 4.3: 评估页（指标表 + Bad Case 溯源）

**Files:**
- Modify: `src/anomaly_lab/web/app.py`
- Create: `src/anomaly_lab/web/templates/report.html`
- Create: `src/anomaly_lab/web/static/report.js`
- Create: `tests/web/test_report_page.py`

- [ ] **Step 1: 写失败测试**

```python
from fastapi.testclient import TestClient

from anomaly_lab.web.app import create_app


def test_report_page_loads():
    client = TestClient(create_app())
    assert client.get("/report").status_code == 200


def test_api_summary_returns_rows():
    client = TestClient(create_app())
    r = client.get("/api/summary")
    assert r.status_code == 200
    assert "rows" in r.json()
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

后端：
- `GET /api/summary`：读最近一份 `reports/latest/report.json` → 返回分组汇总
- `GET /api/badcases?series_id=...`：返回该序列的误报/漏报点 + 分数

前端：
- 指标表（按形态 × 检测器）+ 分组柱状图
- Bad Case 列表：点开 → 波形 + 分数曲线 + 阈值线 + 人工标注叠加

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: web evaluation report page with bad-case drill-down"
```

### Task 4.4: CLI serve 与端到端脚本

**Files:**
- Modify: `src/anomaly_lab/cli.py`
- Modify: `Makefile`
- Create: `scripts/smoke.sh`

- [ ] **Step 1: 写脚本 `scripts/smoke.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY -m anomaly_lab.cli generate --n 6 --seed 42 --out data/smoke
$PY -m anomaly_lab.cli classify --eval --data data/smoke
$PY -m anomaly_lab.cli detect --detector iqr --data data/smoke
$PY -m anomaly_lab.cli evaluate --data data/smoke --report reports/smoke
$PY -m anomaly_lab.cli report --out reports/smoke/summary.md
$PY -m anomaly_lab.cli compliance-check
echo "SMOKE OK"
```

- [ ] **Step 2: 跑脚本确认失败 → 3: 实现 serve 与修正 → 4: 通过**

- [ ] **Step 5: 提交**

```bash
chmod +x scripts/smoke.sh
git add scripts Makefile src
git commit -m "feat: serve command and end-to-end smoke script"
```

### Task 4.5: README（含架构图、快速开始、结果表、迭代案例）

**Files:**
- Create: `README.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/ALGORITHMS.md`
- Create: `docs/DATA.md`

- [ ] **Step 1: 写 README 骨架（先占位，结果数字留空）**

README 必须包含：
1. 一句话定位 + 徽章（Python 版本、License、CI）
2. **架构图**（ASCII 或 Mermaid，放在 `docs/ARCHITECTURE.md`，README 引用）
3. **5 分钟快速开始**：clone → `make setup` → `make generate` → `make evaluate` → 看 `reports/latest/report.md`
4. **数据说明**：合成 6 形态 + UCR；强调真值与公开集的角色差异
5. **算法说明**：统计 / 自训深度 / 预训练三族，以及统一分数语义
6. **评测结果表**：真实跑出来的数字（**不留空，不预填**）
7. **一次迭代案例**：真实故事（问题 → 归因 → 改动 → 回归对比数字）
8. **项目边界**：明确不做什么、合成数据结论不等于真实分布
9. **License**

- [ ] **Step 2: 跑通全部命令，把真实数字填进 README**

Run: `make setup && ./scripts/smoke.sh && make evaluate && make compare`
Expected: 全部成功，产出报告

- [ ] **Step 3: 写迭代案例（必须基于真实 bad case）**

做法：
1. 跑一次评估 → 从报告里挑一个**最差形态**（如周期型指标 F1 最低）
2. 打开 Bad Case 列表 → 归因（是周期长度估计错？还是分数语义混用？还是阈值搜索在有标注样本上过拟合？）
3. 做**一处最小改动**（如：把分类器给出的周期长度传给 `seasonal` 检测器，而不是默认值）
4. 重跑 → 用 `diff_reports` 得到前后对比
5. 把「问题 → 归因 → 改动 → 数字变化」写成 README 的一节

**这一节是 README 里最值钱的部分** —— 它证明的是"方法论"，不是"能跑"。

- [ ] **Step 4: 写 LICENSE（MIT）与合规自检**

`LICENSE` 用 MIT，版权行 `Copyright (c) 2026 江梓锋`。

- [ ] **Step 5: 提交**

```bash
git add README.md docs LICENSE
git commit -m "docs: README with architecture, quickstart, real eval results and iteration case"
```

### Task 4.6: 合规自检命令

**Files:**
- Create: `src/anomaly_lab/compliance.py`
- Modify: `src/anomaly_lab/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

```python
from anomaly_lab.compliance import FORBIDDEN_TERMS, scan_forbidden


def test_clean_text_passes():
    assert scan_forbidden("这是一段干净的文本", FORBIDDEN_TERMS) == []


def test_forbidden_term_detected():
    hits = scan_forbidden("引用了某内部平台名", ["某内部平台名"])
    assert len(hits) == 1
```

- [ ] **Step 2: 跑测试确认失败 → 3: 实现 → 4: 通过**

实现要点：
- `FORBIDDEN_TERMS`：从 DESIGN.md §3 的内部名清单转写（Solaris / Metis / 灯塔 / Prism / Halley / 红盘 / 呼呼 / Dify / Jarvis / KubeVirt / Chaos(平台名) / Chronos(服务名) 等）。**注意**：公开可查的技术名词（Chronos 模型、Redis、Kafka）**不在禁词表** —— 只禁**内部系统专名**
- `scan_forbidden(text, terms) -> list[(term, line_no)]`
- CLI `compliance-check`：扫描 `src/`、`tests/`、`docs/`、`README.md`、`notebooks/` → 命中则打印并 `return 1`
- **例外白名单**：`docs/RESEARCH.md` 与 `docs/DESIGN.md` 中讨论"哪些名字不能用"的段落需要豁免 → 实现时对这两个文件跳过或用行内标记豁免

- [ ] **Step 5: 提交**

```bash
git add src tests
git commit -m "feat: compliance self-check for internal system names"
```

### Task 4.7: 最终验收

**Files:**
- Modify: `README.md`（如需微调）
- Create: `docs/ROADMAP.md`（若尚未创建）

- [ ] **Step 1: 跑全量验收**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests
./scripts/smoke.sh
.venv/bin/python -m anomaly_lab.cli compliance-check
```

Expected: 测试全绿、ruff 无错、smoke 打印 `SMOKE OK`、合规检查通过

- [ ] **Step 2: 对照 DESIGN.md §9 的 8 条成功标准逐条确认**

| # | 标准 | 确认方式 |
|---|---|---|
| 1 | 离线可跑通 | `ANOMALY_LAB_OFFLINE=1 ./scripts/smoke.sh` |
| 2 | 形态分类准确率 ≥ 90% | `anomaly-lab classify --eval` |
| 3 | 三方对照表 | `make compare` |
| 4 | 回归可 diff | 改参数跑两次 + `diff_reports` |
| 5 | 标注回路 | Web 页手工走一遍（或 JSONL 等价路径） |
| 6 | README 四要素 | 人工检查 |
| 7 | 测试通过 | pytest |
| 8 | 合规 | compliance-check |

- [ ] **Step 3: 记录未达标项到 `docs/ROADMAP.md`（不掩盖）**

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "chore: v1 acceptance pass, record open items in roadmap"
```

---

## 附录 A: 计划自检表（执行前对照）

| 检查项 | 状态 |
|---|---|
| 每个 Task 都有明确的文件路径 | ✅ |
| 每个 Task 都有失败测试 → 实现 → 通过测试 → 提交 | ✅ |
| 所有命令是可直接复制的具体命令 | ✅ |
| 关键代码（契约 / 协议 / 特征 / 分类规则 / 推荐表）已给出完整实现 | ✅ |
| 外部依赖（statsmodels / torch / chronos / UCR）都有降级路径 | ✅ §0.1 §0.2 |
| 红线写在最前面且有可执行的自检命令 | ✅ §0.3 + Task 4.6 |
| Chunk 划分保证每个 chunk 结束都有可运行产物 | ✅ Chunk1=能造数能分类；Chunk2=能评估；Chunk3=能对比；Chunk4=能演示能交付 |
| 取舍顺序明确（时间不够砍什么） | ✅ DESIGN.md §8.2 |
| 成功标准可量化 | ✅ DESIGN.md §9 + Task 4.7 |
| 范围蔓延防护（新想法入 ROADMAP 不插队） | ✅ §0.4 |

## 附录 B: 关键风险与触发条件

| 触发条件 | 应对 |
|---|---|
| Task 1.4 分类准确率 < 90% | 调整判据阈值；连续两次调整仍不达标 → 记录 ROADMAP，用"分类器 + 人工复核"过渡，不硬凑 |
| Task 2.2 某个检测器召回极低 | 优先检查**分数语义是否与阈值语义一致**（ADR-4 的存在理由），而不是调 k 值 |
| Task 2.7 报告 diff 不出变化 | 检查两次运行是否用了**同一份 detections 缓存** —— 缓存未失效会导致假 diff |
| Task 3.1 CPU 训练过慢 | 减序列数（8→4）、减 epoch、先做一次 10 秒试跑测速再定 |
| Task 3.3 HF 权重始终拉不到 | 标记 skipped，README 写明"预训练模型未纳入本次对比"，**不阻塞交付** |
| 任何任务卡住超过 1 个工作日 | 停下记录到 ROADMAP，**跳到下一个任务**，不要在单点上死磕 |
