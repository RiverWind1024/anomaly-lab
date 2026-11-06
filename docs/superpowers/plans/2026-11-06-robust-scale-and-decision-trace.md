# 检测器稳健性 + 决策可见性 实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「算不出分数」不再被静默写成 0，让用户在建任务前就知道算法会不会失效，并让每次检测的决策过程可回溯。

**Architecture:** 四批独立可发布的工作：① 所有尺度型检测器共用一个带降级链的 `robust_scale`；② 后端提供算法适用性说明 + 数据能力探测，前端用悬停/警告呈现；③ 把每次 run 的决策链落库并做成前端时间线；④ 补齐稀疏/计数型专用的检测器，并修掉 `event_count` 的因果缺陷（用了未来数据）。

**Tech Stack:** Python 3.12 / numpy / scipy / pandas / pytest；React 18 + TypeScript + AntD v5 + TanStack Query。

---

## 背景：要修的是什么

### 现象

`job-runs`（稀疏事件指标，值 0/1/2…）上选 `iqr`，界面显示「一切正常」，一条告警都没有。

### 根因（三处，逐层）

1. **尺度为 0**：零值占比 >75% 时 `q3 - q1 = 0`，`score = |x - median| / 0 = NaN`；
2. **NaN 被当成 0**：`_WindowedDetector.score()` 里 `np.where(isfinite, scores, 0.0)` 把「算不出来」翻译成「不异常」；
3. **没有任何提示**：推荐层给 `high_zero_ratio` 推的就是 `iqr`（`recommend.py:60`），界面上也没有适用性说明。

### 关键决定（已与用户确认）

| 决定 | 结论 |
|---|---|
| MAD 能否替代 IQR | **不能**。零值 >50% 时 MAD 就归零，比 IQR（>75%）更早失效 |
| 非零子集 IQR | 单独成检测器 `zero_inflated_iqr`，不给 `iqr` 打补丁（否则阈值语义说不清） |
| 计数型数据 | 单独成检测器 `poisson_count`（泊松率检验），**也要做** |
| 适用性提示 | 内容由**后端** catalog 提供，前端只渲染，避免两处漂移 |
| `event_count` 的 `center=True` | **修**（优先正确性）。改成因果窗口 + 有效窗口长度算 λ |
| 顺序 | 1 → 2 → 3 → 4，每批独立可发布 |

---

## 文件结构

### 新增

| 文件 | 职责 |
|---|---|
| `src/anomaly_lab/detectors/scale.py` | `robust_scale` / `pick_scale` / `majority_source` |
| `src/anomaly_lab/detectors/zero_inflated.py` | `PoissonCountDetector` + `ZeroInflatedIQRDetector` |
| `src/anomaly_lab/platform/capability.py` | 数据能力探测 |
| `src/anomaly_lab/platform/decisions.py` | `DecisionTrace` 六段结构 |
| `frontend/src/features/jobs/AlgorithmGuide.tsx` | 算法 ⓘ 提示 |
| `frontend/src/features/jobs/CapabilityWarning.tsx` | 试跑结果里的失效警告 |
| `frontend/src/features/evaluation/DecisionTraceTimeline.tsx` | 决策链时间线（**注意不叫 `DecisionTrace`，避免和类型同名**） |
| `tests/detectors/test_scale.py` | 降级链 |
| `tests/detectors/test_zero_inflated.py` | 两个新检测器 |
| `tests/detectors/test_event_count.py` | 因果修正回归 |
| `tests/platform/test_capability.py` | 能力探测 |
| `tests/platform/test_decision_trace.py` | 决策链落库/读回 |
| `tests/platform/test_detector_registry.py` | 新检测器已注册 |
| `tests/web/test_scale_source.py` | `scale_source` 贯通到 API |
| `tests/classification/test_recommend.py` | 推荐规则 |
| `frontend/src/features/jobs/algorithmGuide.test.tsx` | ⓘ 渲染 |
| `frontend/src/features/jobs/capabilityWarning.test.tsx` | 警告渲染 |
| `frontend/src/features/evaluation/decisionTrace.test.tsx` | 时间线渲染 |

### 修改

| 文件 | 改什么 |
|---|---|
| `src/anomaly_lab/contracts.py:78-88` | `DetectionResult` 加 `scale_source` / `status` |
| `src/anomaly_lab/detectors/base.py:45-67,96-113` | `make_result` 透传；`_timed_detect` 读 `_last_scale_source` |
| `src/anomaly_lab/detectors/statistical.py:18-121,440-478` | IQR/MAD/ZScore 接入降级链；修 `event_count` |
| `src/anomaly_lab/platform/detectors.py:33-45,268-309` | 注册新检测器；`DETECTOR_GUIDE`；catalog 带 guide |
| `src/anomaly_lab/platform/runner.py:300-345` | 写 `scale_source` / `status` / `decision` |
| `src/anomaly_lab/platform/store.py:117-139,500-540,1171-1208` | `run_series` 加 `decision_json`（带迁移） |
| `src/anomaly_lab/web/platform_routes.py:684-815` | preview 返回 `scale_source` / `status` / `capability` |
| `src/anomaly_lab/web/app.py:322-360` | run series 详情返回 `scale_source` / `status` / `decision` |
| `src/anomaly_lab/classification/recommend.py:60-74` | 高零值/稀疏事件改推荐 |
| `frontend/src/api/types.ts` | `CatalogDetector.guide?`、`Capability`、`DecisionTraceData` |
| `frontend/src/lib/detectorLabels.ts` | 新检测器的中文名（**必须与后端同步**） |
| `frontend/src/features/jobs/JobForm.tsx:183-190` | 算法 label 加 ⓘ |
| `frontend/src/features/jobs/TestRunPanel.tsx` | 渲染 capability 警告 |
| `frontend/src/pages/job/JobDetectionsPanel.tsx` | 显示尺度标签 |
| `docs/ALGORITHMS.md` / `docs/PITFALLS.md` | 记录降级链、MAD 更早失效、因果修正 |

---

# Chunk 1：尺度不变式（批次 A）

> 目标：**正常数据的分数一个都不变**，但「分母是 0」时不再输出 0 分。

### Task 1.1：`robust_scale` 降级链

**Files:**
- Create: `src/anomaly_lab/detectors/scale.py`
- Test: `tests/detectors/test_scale.py`

- [ ] **Step 1: 写失败测试**

```python
"""尺度降级链：IQR → MAD → std → 不可判。"""

import numpy as np

from anomaly_lab.detectors.scale import majority_source, pick_scale, robust_scale


def test_正常数据用首选尺度():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    est = robust_scale(values, prefer="iqr")
    assert est.source == "iqr"
    assert est.value == np.percentile(values, 75) - np.percentile(values, 25)


def test_iqr和mad都为零时退回std():
    # ⚠️ 80% 零：q75=0 → IQR=0；MAD 也=0（>50% 零）→ 必须继续降级到 std
    #    （60% 零时 IQR 还有 1.75，测不到降级 —— 这是实际算过的）
    values = np.array([0.0] * 8 + [1.0, 2.0])
    est = robust_scale(values, prefer="iqr")
    assert est.source == "std"
    assert est.value == np.std(values)


def test_全常数序列不可判():
    est = robust_scale(np.ones(50), prefer="iqr")
    assert est.source == "none"
    assert est.value == 0.0


def test_pick_scale逐点挑第一个正值():
    scale, source = pick_scale(
        prefer="iqr",
        candidates={
            "iqr": np.array([0.0, 2.0, 0.0, 0.0]),
            "mad": np.array([0.0, 0.0, 1.5, 0.0]),
            "std": np.array([0.0, 0.0, 0.0, 3.0]),
        },
    )
    assert list(scale) == [0.0, 2.0, 1.5, 3.0]
    assert list(source) == ["none", "iqr", "mad", "std"]


def test_pick_scale优先级是首选在前():
    # ⚠️ 三个候选同时为正时，必须选首选的那个。
    #    写成 reversed() 会让 std 永远赢 —— 正常数据的分数会全变。
    scale, source = pick_scale(
        prefer="iqr",
        candidates={
            "iqr": np.array([2.0]),
            "mad": np.array([1.0]),
            "std": np.array([3.0]),
        },
    )
    assert list(scale) == [2.0]
    assert list(source) == ["iqr"]


def test_数值噪声不算尺度():
    # ⚠️ 常数序列经过 polyfit/STL 后残差是 1e-16 量级，不是精确 0
    est = robust_scale(np.full(100, 5.0) + 1e-16 * np.arange(100))
    assert est.source == "none"


def test_pick_scale容忍缺失候选():
    # ⚠️ ZScore 只提供 std —— 不能因为它没给 iqr 就 KeyError
    scale, source = pick_scale(prefer="std", candidates={"std": np.array([0.0, 2.0])})
    assert list(scale) == [0.0, 2.0]
    assert list(source) == ["none", "std"]


def test_majority_source忽略none():
    source = np.array(["none", "iqr", "iqr", "std"], dtype=object)
    assert majority_source(source) == "iqr"
    assert majority_source(np.array(["none", "none"], dtype=object)) == "none"
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/python -m pytest tests/detectors/test_scale.py -q
```

预期：`ModuleNotFoundError: No module named 'anomaly_lab.detectors.scale'`

- [ ] **Step 3: 实现**

```python
"""稳健尺度估计 —— 所有「|x - center| / scale」型检测器共用。

⚠️ 为什么需要降级链：
    IQR / MAD 在零膨胀或全常数序列上会算出 0，
    而 score = 偏差 / 0 的 NaN 一旦被写成 0，
    「算不出来」就被翻译成了「一切正常」—— 这是静默失效。

⚠️ 降级顺序是有依据的，不是随便排的：
    - 零值 >75%：IQR = q75 − q25 = 0
    - 零值 >50%：MAD = median(|x − med|) = 0（比 IQR 更早失效）
    - std 在零膨胀数据上仍有值（10% 非零、幅度 25 → std ≈ 7.5）
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

_ORDER = ("iqr", "mad", "std")


@dataclass(frozen=True)
class ScaleEstimate:
    value: float
    #: iqr / mad / std / none
    source: str
    #: 每个候选的原始值（诊断用）
    probe: dict[str, float] = field(default_factory=dict)


def _candidates(values: np.ndarray) -> dict[str, float]:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return {"iqr": 0.0, "mad": 0.0, "std": 0.0}
    q1, q3 = np.percentile(v, [25, 75])
    med = np.median(v)
    return {
        "iqr": float(q3 - q1),
        "mad": float(np.median(np.abs(v - med)) * 1.4826),
        "std": float(np.std(v)),
    }


def _ordered(prefer: str) -> list[str]:
    if prefer not in _ORDER:
        raise ValueError(f"未知尺度: {prefer}")
    return [prefer, *(name for name in _ORDER if name != prefer)]


def numeric_floor(values: np.ndarray) -> float:
    """低于这个值的尺度差异是浮点误差，不是信号。

    ⚠️ 常数序列经过 polyfit / STL 之后残差不是精确的 0，而是 1e-16 量级。
       直接拿它当尺度，会把数值噪声放大成几十倍的分数 —— 常数序列报出一堆假告警。
    """
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return 0.0
    return 1e-12 * max(1.0, float(np.max(np.abs(v))))


def robust_scale(values: np.ndarray, *, prefer: str = "iqr") -> ScaleEstimate:
    """整段序列的尺度：按顺序挑第一个大于数值噪声的候选。"""
    candidates = _candidates(values)
    floor = numeric_floor(values)
    for name in _ordered(prefer):
        if candidates[name] > floor:
            return ScaleEstimate(candidates[name], name, candidates)
    return ScaleEstimate(0.0, "none", candidates)


def pick_scale(
    *, prefer: str, candidates: dict[str, np.ndarray], floor: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """逐点挑尺度（滚动检测器用）。

    ⚠️ **只考虑 candidates 里真的给了的候选** ——
       ZScore 只提供 std，不能因为链里有 iqr 就 KeyError。

    返回 `(scale, source)`；`source` 是 object 数组，值为候选名或 "none"。
    """
    names = [name for name in _ordered(prefer) if name in candidates]
    arrays = {name: np.asarray(candidates[name], dtype=float) for name in names}
    if not arrays:
        raise ValueError("candidates 不能为空")

    n = max(arr.size for arr in arrays.values())
    scale = np.zeros(n, dtype=float)
    source = np.full(n, "none", dtype=object)
    # ⚠️ 必须按**优先级从高到低**写，且只在还是 none 的位置写。
    #    写成 reversed() 会让最低优先级的 std 永远赢 —— 正常数据的分数会全变。
    for name in names:
        arr = np.broadcast_to(arrays[name], (n,))
        use = np.isfinite(arr) & (arr > floor) & (source == "none")
        scale[use] = arr[use]
        source[use] = name
    return scale, source


def majority_source(source: np.ndarray) -> str:
    """逐点来源 → 一个代表值（忽略 none）。"""
    values = [item for item in source if item != "none"]
    if not values:
        return "none"
    return Counter(values).most_common(1)[0][0]
```

- [ ] **Step 4: 运行，确认通过**

```bash
.venv/bin/python -m pytest tests/detectors/test_scale.py -q
```

预期：`6 passed`

- [ ] **Step 5: 提交**

```bash
git add src/anomaly_lab/detectors/scale.py tests/detectors/test_scale.py
git commit -m "feat(detectors): 稳健尺度降级链 IQR → MAD → std → 不可判"
```

---

### Task 1.2：IQR / MAD / ZScore 接入降级链

> ⚠️ **不改 `_center_scale` 的签名**。它仍返回 `(center, scale)` ——
> 全库有 3 处解包（`score()`、`_WindowedDetector.bands()`、
> `TrendResidualIQRDetector.bands()`），改签名会漏改。
> 尺度来源用实例属性 `_last_scale_source` 传递。

**Files:**
- Modify: `src/anomaly_lab/contracts.py:78-88`
- Modify: `src/anomaly_lab/detectors/base.py:45-67,96-113`
- Modify: `src/anomaly_lab/detectors/statistical.py:18-130`
- Test: `tests/detectors/test_scale.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_iqr在零膨胀数据上不再恒为0分():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    values = np.zeros(200)
    values[50] = 25.0
    values[150] = 25.0
    series = SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(200).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector(k=2.5).detect(series)
    assert result.scale_source == "std"
    assert result.scores[50] > 2.5          # 必须能报出来
    assert result.scores[0] == 0.0


def test_全常数序列标记为无法判定():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import IQRDetector

    series = SeriesBundle(
        series_id="s",
        values=np.full(100, 7.0),
        timestamps=np.arange(100).astype("datetime64[m]"),
        freq="1min",
    )
    result = IQRDetector().detect(series)
    assert result.status == "undetermined"
    assert not result.is_anomaly.any()
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/python -m pytest tests/detectors/test_scale.py -q
```

预期：`AttributeError: 'DetectionResult' object has no attribute 'scale_source'`

- [ ] **Step 3: 给 `DetectionResult` 加两个带默认值的字段**

`src/anomaly_lab/contracts.py`（放在 `band_kind` 之后 —— 它已经是最后一个有默认值的字段）：

```python
    scale_source: str | None = None
    """这一窗实际用的尺度：iqr / mad / std / none。

    ⚠️ 降级必须**可见** —— 否则「用 std 兜底」也是一种静默。
    """

    status: str = "ok"
    """ok / undetermined。

    ⚠️ `undetermined` = 数据里没有可用的尺度（全常数序列），
       不是「一切正常」。前端要显示成「无法判定」。
    """
```

- [ ] **Step 4: `make_result` 透传**

`src/anomaly_lab/detectors/base.py`：

```python
def make_result(
    series: SeriesBundle,
    scores: np.ndarray,
    score_type: str,
    threshold: float,
    detector: str,
    elapsed_ms: float,
    bands: Bands | None = None,
    scale_source: str | None = None,
    status: str = "ok",
) -> DetectionResult:
    ...
    return DetectionResult(
        ...,
        scale_source=scale_source,
        status=status,
    )
```

- [ ] **Step 5: `_timed_detect` 统一读实例属性**

放在 `TimedDetector`（不是 `_WindowedDetector`）—— 这样 `PoissonCountDetector` /
`ZeroInflatedIQRDetector` 也能用：

```python
    def _timed_detect(self, series, threshold=None):
        started = time.perf_counter()
        scores = self.score(series)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        chosen = self.default_threshold if threshold is None else float(threshold)
        bands = self.bands(series, chosen)

        source = getattr(self, "_last_scale_source", None)
        status = getattr(self, "_last_status", None) or (
            "undetermined" if source == "none" else "ok"
        )
        return make_result(
            series, scores, self.score_type, chosen, self.name, elapsed_ms,
            bands=bands, scale_source=source, status=status,
        )
```

- [ ] **Step 6: `_WindowedDetector` 接入 `pick_scale`**

```python
class _WindowedDetector(TimedDetector):
    #: 降级链的起点
    prefer_scale = "iqr"

    def _center_scale(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """返回 `(center, scale)`；**同时**把来源写进 `_last_scale_source`。"""
        raise NotImplementedError

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        center, scale = self._center_scale(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.abs(values - center) / scale
        # NaN 仍然写 0（保持既有分数语义），但 `status` 由 `_last_scale_source` 决定，
        # 所以「算不出来」不会被当成「一切正常」。
        return np.where(np.isfinite(scores), scores, 0.0)
```

IQR：

```python
class IQRDetector(_WindowedDetector):
    prefer_scale = "iqr"

    def _center_scale(self, values):
        if self.window is None:
            center = np.full_like(values, np.median(values))
            med = np.median(values)
            cand = {
                "iqr": np.full_like(values, np.percentile(values, 75) - np.percentile(values, 25)),
                "mad": np.full_like(values, np.median(np.abs(values - med)) * 1.4826),
                "std": np.full_like(values, np.std(values)),
            }
        else:
            center = _rolling_quantile(values, self.window, 0.5)
            cand = {
                "iqr": _rolling_quantile(values, self.window, 0.75)
                       - _rolling_quantile(values, self.window, 0.25),
                "mad": _rolling_mad(values, self.window),
                "std": _rolling_std(values, self.window),
            }
        scale, source = pick_scale(
            prefer=self.prefer_scale,
            candidates=cand,
            floor=numeric_floor(values),
        )
        self._last_scale_source = majority_source(source)
        return center, scale
```

MAD：`prefer_scale = "mad"`，候选同上（**注意：MAD 的降级链也包含 iqr，但起点是 mad**）。

ZScore：只提供 `{"std": ...}`，`prefer_scale = "std"`：

```python
        scale, source = pick_scale(
            prefer="std",
            candidates={"std": std_values},
            floor=numeric_floor(values),
        )
        self._last_scale_source = majority_source(source)
```

新增滚动辅助（**std 必须 `ddof=0`**，与现有 `np.std` 一致，否则正常数据分数会变）：

```python
def _rolling_std(values, window):
    return (
        pd.Series(values).rolling(window, min_periods=window)
        .std(ddof=0).shift(1).to_numpy()
    )


def _rolling_mad(values, window):
    med = _rolling_quantile(values, window, 0.5)
    abs_dev = np.abs(values - med)
    return (
        pd.Series(abs_dev).rolling(window, min_periods=window)
        .median().shift(1).to_numpy() * 1.4826
    )
```

- [ ] **Step 7: `bands()` 不用改**

`_center_scale` 签名没变，`_WindowedDetector.bands()` 与
`TrendResidualIQRDetector.bands()` 都不动。scale=0 时 `lower == upper == center`，
不会崩，也不会凭空产生告警 —— 这正是「不可判」应有的表现。

- [ ] **Step 8: 回归**

```bash
.venv/bin/python -m pytest -q
```

预期：`818 passed`（原 810 + Task 1.1 的 6 条 + Task 1.2 的 2 条）。

再手工确认「正常数据分数逐点不变」：

```bash
.venv/bin/python - <<'PY'
import numpy as np
from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector
s = generate_series("periodic", n=500, seed=1)
print(IQRDetector().score(s)[:5])   # 与实施前保存的值对比
PY
```

- [ ] **Step 9: 提交**

```bash
git add src/anomaly_lab/contracts.py src/anomaly_lab/detectors/base.py \
        src/anomaly_lab/detectors/statistical.py tests/detectors/test_scale.py
git commit -m "fix(detectors): 尺度为 0 时降级到 std，全常数序列标记为无法判定"
```

---

### Task 1.3：`scale_source` / `status` 贯通到产物与 API

**Files:**
- Modify: `src/anomaly_lab/platform/runner.py:300-345`
- Modify: `src/anomaly_lab/web/platform_routes.py:760-815`
- Modify: `src/anomaly_lab/web/app.py:322-360`
- Modify: `frontend/src/api/types.ts`（`SeriesEntry` / `Preview` / `RunSeriesDetail`）
- Modify: `frontend/src/features/detections/DetectionsPage.tsx`（或 `JobDetectionsPanel`）
- Test: `tests/web/test_scale_source.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""尺度来源与「无法判定」必须一路传到 API。"""

from fastapi.testclient import TestClient

from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.web.app import create_app


def _make_job(tmp_path):
    """⚠️ tests/ 不是 package，不能跨文件 import helper —— 就地复制建库代码。"""
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="cpu",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


def test_预览返回尺度来源(tmp_path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    store, job_id = _make_job(tmp_path)
    # 源库：60 个点，全为常数 → 触发 undetermined
    import sqlite3

    from anomaly_lab.platform.timeutil import to_iso, utcnow
    from datetime import timedelta

    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (ts TEXT, value REAL)")
    end = utcnow().replace(second=0, microsecond=0)
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [(to_iso(end - timedelta(minutes=5 * (59 - i))), 7.0) for i in range(60)],
    )
    conn.commit()
    conn.close()
    execute_job(store, job_id, data_root=tmp_path)

    client = TestClient(create_app())
    body = client.get(f"/api/platform/jobs/{job_id}/preview").json()
    # ⚠️ 这个 fixture 是 60 个完全相同的点 —— 结果**确定**是不可判，
    #    不能用 `in {...}` 这种宽松断言，否则接口兜底默认值也能通过。
    assert body["scale_source"] == "none"
    assert body["status"] == "undetermined"
```

- [ ] **Step 2: 运行，确认失败**

```bash
.venv/bin/python -m pytest tests/web/test_scale_source.py -q
```

预期：`KeyError: 'scale_source'`

- [ ] **Step 3: runner 写进 entry 与 npz**

`SeriesOutcome.entry` 增加：

```python
"scale_source": result.scale_source or "",
"status": result.status,
```

`arrays` 增加：

```python
"scale_source": np.array(result.scale_source or ""),
"status": np.array(result.status),
```

- [ ] **Step 4: 两个读路径都返回**

`platform_routes.py` 的 `preview()` 正常分支：

```python
"scale_source": entry.get("scale_source", ""),
"status": entry.get("status", "ok"),
```

`app.py` 的 `/api/runs/{run_id}/series/{series_id}` 同理。

- [ ] **Step 5: 前端**

`types.ts`：

```ts
// SeriesEntry 追加
scale_source?: string
status?: 'ok' | 'undetermined'
// Preview 追加
scale_source: string
status: 'ok' | 'undetermined'
// RunSeriesDetail 追加
scale_source: string
status: 'ok' | 'undetermined'
```

`JobDetectionsPanel`（它消费 `Preview`）在序列标题旁：

```tsx
{preview.status === 'undetermined' && <Tag color="orange">无法判定</Tag>}
{preview.scale_source === 'std' && (
  <Tooltip title="IQR/MAD 为 0，本窗退回标准差">
    <Tag>尺度降级 · std</Tag>
  </Tooltip>
)}
```

- [ ] **Step 6: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/web/test_scale_source.py -q
cd frontend && npx tsc -b && npx vitest run
git add -A && git commit -m "feat(platform): 检测结果展示尺度来源与无法判定状态"
```

---

### Task 1.4：其余检测器的尺度来源

> 为什么还要这一步：`trend_residual_iqr` 把残差交给**临时** `IQRDetector` 打分，
> `_last_scale_source` 落在临时实例上，外层结果永远是 `None`；
> `stl_residual` 在残差 MAD=0 时直接返回全 0 且 `status="ok"`；
> `seasonal` 已有全局兜底，但没记来源。
> 三者都不会崩，但违背 Chunk 1 的目标 —— **算不出来必须可见**。

**Files:**
- Modify: `src/anomaly_lab/detectors/statistical.py:173-240,257-320,332-368`
- Test: `tests/detectors/test_scale.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_趋势残差检测器透传尺度来源():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import TrendResidualIQRDetector

    # 全是同一个值 → 去趋势后残差恒为 0 → 不可判
    series = SeriesBundle(
        series_id="s",
        values=np.full(100, 5.0),
        timestamps=np.arange(100).astype("datetime64[m]"),
        freq="1min",
    )
    result = TrendResidualIQRDetector().detect(series)
    assert result.scale_source == "none"
    assert result.status == "undetermined"


def test_STL残差恒定时标记不可判():
    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.detectors.statistical import STLResidualDetector

    series = SeriesBundle(
        series_id="s",
        values=np.full(120, 5.0),
        timestamps=np.arange(120).astype("datetime64[m]"),
        freq="1min",
    )
    result = STLResidualDetector(period=24).detect(series)
    assert result.scale_source == "none"
    assert result.status == "undetermined"
```

- [ ] **Step 2: 实现（三处）**

`TrendResidualIQRDetector.score()` —— 留住内部实例：

```python
    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        _, residuals = self._trend_and_residual(values)
        inner = IQRDetector(k=self.k)          # ⚠️ 留着引用，才能拿到尺度来源
        scores = inner.score(
            SeriesBundle(
                series_id=series.series_id,
                values=residuals,
                timestamps=series.timestamps,
                freq=series.freq,
            )
        )
        self._last_scale_source = inner._last_scale_source
        return scores
```

`STLResidualDetector` —— 在 `_residual_parts()` 里记来源：

```python
        from anomaly_lab.detectors.scale import numeric_floor

        floor = numeric_floor(abs_resid)
        mad = float(np.median(np.abs(abs_resid - np.median(abs_resid)))) * 1.4826
        if mad > floor:
            self._last_scale_source = "mad"
        else:
            mad = float(np.std(abs_resid))
            if mad > floor:
                self._last_scale_source = "std"
            else:
                mad = 0.0                 # ⚠️ 1e-16 的尺度会把噪声放大成假告警
                self._last_scale_source = "none"
```

`score()` 里标状态：

```python
        if mad <= 0:
            self._last_status = "undetermined"
            return np.zeros_like(values)
        self._last_status = "ok"
        return abs_resid / mad
```

`SeasonalDetector._global_scale()` —— 去掉 `@staticmethod`，顺手记来源：

```python
    def _global_scale(self, values: np.ndarray) -> float:
        if len(values) == 0:
            self._last_scale_source = "none"
            return 0.0
        mad = float(np.median(np.abs(values - np.median(values)))) * 1.4826
        if mad > 0:
            self._last_scale_source = "mad"
            return mad
        std = float(np.std(values))
        self._last_scale_source = "std" if std > 0 else "none"
        return std
```

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/detectors/test_scale.py -q
.venv/bin/python -m pytest -q
git add -A && git commit -m "fix(detectors): 趋势残差/STL/季节性的尺度来源也透传"
```

---

# Chunk 2：配置前就知道（批次 B + C）

> 目标：选算法时能看到「它什么时候会失效」，试跑后能看到「你的数据会不会让它失效」。

### Task 2.1：`DETECTOR_GUIDE` + catalog

**Files:**
- Modify: `src/anomaly_lab/platform/detectors.py:268-309`
- Test: `tests/web/test_api_contract.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_catalog_每个算法都有适用性说明():
    client = TestClient(create_app())          # 与文件里其它用例一致
    catalog = client.get("/api/platform/catalog").json()
    for det in catalog["detectors"]:
        guide = det.get("guide") or {}
        assert guide.get("good_for"), det["name"]
        assert guide.get("bad_for"), det["name"]
        assert guide.get("score"), det["name"]
```

- [ ] **Step 2: 加数据**

```python
DETECTOR_GUIDE: dict[str, dict[str, str]] = {
    "iqr": {
        "good_for": "平稳、连续、非零值占多数",
        "bad_for": "零值超过 75%（Q3−Q1=0，会退回 std，对零膨胀不稳健）",
        "score": "偏离中位数多少个 IQR",
        "needs": "非零值 > 25%",
    },
    "mad": {
        "good_for": "有离群点的平稳数据",
        "bad_for": "零值超过 50%（MAD=0，比 IQR 更早退回 std）；全常数序列",
        "score": "偏离中位数多少个 1.4826×MAD",
        "needs": "非零值 > 50%",
    },
    "zscore": {
        "good_for": "近似正态、没有尖峰",
        "bad_for": "有尖峰（均值/方差被拉偏）；零膨胀",
        "score": "偏离均值多少个标准差",
        "needs": "方差 > 0",
    },
    "seasonal": {
        "good_for": "稳定周期，窗口至少覆盖 3 个周期",
        "bad_for": "无周期；趋势型（相位分组会把趋势算成异常）",
        "score": "同相位组内的稳健偏离",
        "needs": "周期可识别",
    },
    "stl_residual": {
        "good_for": "周期明显（日/周）",
        "bad_for": "无周期 —— 会估出伪周期（实测 500 点趋势序列报 2032 个点）",
        "score": "STL 残差多少个残差 MAD",
        "needs": "真实周期",
    },
    "trend_residual_iqr": {
        "good_for": "线性趋势",
        "bad_for": "非线性趋势；强周期",
        "score": "去趋势后残差多少个 IQR",
        "needs": "趋势近似线性",
    },
    "theil_sen": {
        "good_for": "线性趋势 + 有离群点",
        "bad_for": "非线性趋势；强周期",
        "score": "Theil-Sen 残差多少个 MAD",
        "needs": "趋势近似线性；点数 ≥ 8",
    },
    "changepoint": {
        "good_for": "阶跃、水平漂移",
        "bad_for": "点级尖峰（它是区段法，会把整段标成异常）",
        "score": "滑动窗口双样本 t 检验的 1−p",
        "needs": "有足够长的平稳段",
    },
    "event_count": {
        "good_for": "稀疏事件，看「多久发生一次」",
        "bad_for": "单点幅度爆发（1 次和 10 次被当成一样）；连续值",
        "score": "窗口内非零点数相对泊松期望的累计概率",
        "needs": "0 与非 0 有业务含义",
    },
    "poisson_count": {
        "good_for": "计数型指标（每分钟 error 数、重试数）",
        "bad_for": "非整数（率、延迟、金额）；强过度离散",
        "score": "计数值相对泊松期望的累计概率",
        "needs": "非负整数",
    },
    "zero_inflated_iqr": {
        "good_for": "大部分为 0、非零是有幅度的值（交易额、消息大小）",
        "bad_for": "非零点太少（<30，幅度估不准）；连续值",
        "score": "非零部分偏离中位数多少个非零 IQR",
        "needs": "非零样本 ≥ 30",
    },
    "chronos": {
        "good_for": "没有历史基线的冷启动",
        "bad_for": "慢（秒级/序列）；分数是 [0,1] 相对量；窗口短于 8 点",
        "score": "预测区间越界的相对程度",
        "needs": "本地权重 + 足够上下文",
    },
    "auto": {
        "good_for": "不确定用哪个算法时",
        "bad_for": "要求算法固定可复现的场景（逐窗会换算法）",
        "score": "取决于当窗选中的算法",
        "needs": "无",
    },
}
```

`detector_catalog()` 每行加 `"guide": DETECTOR_GUIDE.get(name, {})`。

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/web/test_api_contract.py -q
git add src/anomaly_lab/platform/detectors.py tests/web/test_api_contract.py
git commit -m "feat(platform): 检测器清单带上适用性说明"
```

---

### Task 2.2：算法选择旁的 ⓘ

**Files:**
- Create: `frontend/src/features/jobs/AlgorithmGuide.tsx`
- Modify: `frontend/src/features/jobs/JobForm.tsx:183-190`
- Modify: `frontend/src/api/types.ts`
- Test: `frontend/src/features/jobs/algorithmGuide.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AlgorithmGuide } from './AlgorithmGuide'

describe('AlgorithmGuide', () => {
  it('有说明时渲染问号图标', () => {
    render(<AlgorithmGuide guide={{ good_for: '平稳连续值', bad_for: '零值 >75%' }} />)
    expect(screen.getByLabelText('算法适用性')).toBeInTheDocument()
  })

  it('没有说明时什么都不渲染', () => {
    const { container } = render(<AlgorithmGuide guide={{}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
```

- [ ] **Step 2: 类型（必须是可选字段）**

`frontend/src/api/types.ts`：

```ts
export interface CatalogDetector {
  ...
  /** 适用性说明；老后端可能没有。 */
  guide?: { good_for?: string; bad_for?: string; score?: string; needs?: string }
}
```

⚠️ 不能写成必填：`JobForm.test.tsx` / `JobForm.draft.test.tsx` /
`JobConfigPanel.test.tsx` 里的 `CatalogDetector` 字面量都没有 `guide`，
必填会让 `tsc -b` 直接失败。

- [ ] **Step 3: 实现**

```tsx
import { Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'

export interface AlgorithmGuideProps {
  guide: { good_for?: string; bad_for?: string; score?: string; needs?: string }
}

/** 算法的适用性说明 —— 悬停才看得到，不占版面。 */
export function AlgorithmGuide({ guide }: AlgorithmGuideProps) {
  if (!guide.good_for && !guide.bad_for) return null
  return (
    <Tooltip
      title={
        <div className="algorithm-guide">
          <div><b>适合</b>　{guide.good_for}</div>
          <div><b>失效</b>　{guide.bad_for}</div>
          <div><b>分数</b>　{guide.score}</div>
          {guide.needs ? <div><b>要求</b>　{guide.needs}</div> : null}
        </div>
      }
    >
      <QuestionCircleOutlined aria-label="算法适用性" className="field-hint__icon" />
    </Tooltip>
  )
}
```

`JobForm.tsx`：

```tsx
const selectedDetector = useMemo(
  () => detectors.find((d) => d.name === selectedDetectorName),
  [detectors, selectedDetectorName],
)
...
<Form.Item
  name="detector"
  label={
    <span className="field-hint">
      检测算法
      <AlgorithmGuide guide={selectedDetector?.guide ?? {}} />
    </span>
  }
  ...
>
```

- [ ] **Step 4: 验证 + 提交**

```bash
cd frontend && npx tsc -b && npx vitest run src/features/jobs
git add -A && git commit -m "feat(frontend): 算法选择旁加适用性提示"
```

---

### Task 2.3：能力探测（capability）

**Files:**
- Create: `src/anomaly_lab/platform/capability.py`
- Test: `tests/platform/test_capability.py`

- [ ] **Step 1: 写失败测试**

```python
"""数据能力探测：这个指标会让哪些算法失效。"""

import numpy as np

from anomaly_lab.platform.capability import probe


def test_零膨胀判iqr不适用():
    values = np.zeros(200)
    values[[10, 60, 110, 160]] = [1.0, 2.0, 1.0, 3.0]   # 98% 零
    cap = probe(values)
    assert cap.zero_ratio == 0.98
    assert cap.n_nonzero == 4
    assert cap.verdict == "unsuitable"
    names = {w.detector for w in cap.warnings}
    assert "iqr" in names and "mad" in names


def test_计数型能识别():
    values = np.array([0, 0, 1, 0, 2, 0, 0, 1, 0, 10], dtype=float)
    cap = probe(values)
    assert cap.looks_like_counts is True


def test_连续值不判失效():
    cap = probe(np.random.default_rng(0).normal(10, 2, 500))
    assert cap.verdict == "ok"
    assert cap.warnings == []


def test_全常数序列不可判():
    cap = probe(np.full(100, 3.0))
    assert cap.verdict == "undetermined"
```

- [ ] **Step 2: 实现**

```python
"""数据能力探测 —— 这个指标会让哪些算法失效。

⚠️ 只**报告**，不修数据。和 lab 的体检一样：
   看到的就是检测器实际会拿到的，不做二次清洗。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

IQR_MIN_NONZERO = 0.25      # 非零比例低于它 → IQR=0
MAD_MIN_NONZERO = 0.50      # 非零比例低于它 → MAD=0
MIN_NONZERO_SAMPLES = 30    # 非零样本少于它 → 幅度估不准


@dataclass(frozen=True)
class Warning:
    detector: str
    reason: str


@dataclass(frozen=True)
class Capability:
    n: int
    zero_ratio: float
    n_nonzero: int
    looks_like_counts: bool
    scale_probe: dict[str, float]
    verdict: str                      # ok / unsuitable / undetermined
    warnings: list[Warning] = field(default_factory=list)
    message: str = ""


def probe(values: np.ndarray) -> Capability:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = int(v.size)
    if n == 0:
        return Capability(0, 0.0, 0, False, {}, "undetermined", [], "没有有效数据")

    nonzero = v != 0
    n_nonzero = int(nonzero.sum())
    zero_ratio = 1.0 - n_nonzero / n

    probe_scales = {
        "iqr": float(np.percentile(v, 75) - np.percentile(v, 25)),
        "mad": float(np.median(np.abs(v - np.median(v))) * 1.4826),
        "std": float(np.std(v)),
    }
    looks_like_counts = bool(
        n_nonzero > 0
        and np.all(v >= 0)
        and np.all(np.equal(np.mod(v, 1), 0))
        and n_nonzero < n
    )

    if n_nonzero == 0 or all(x == 0 for x in probe_scales.values()):
        return Capability(
            n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
            "undetermined", [], "整段没有变化（或全为 0），无法判定",
        )

    warnings: list[Warning] = []
    if zero_ratio >= 1 - IQR_MIN_NONZERO:
        warnings.append(
            Warning("iqr", f"零值占 {zero_ratio:.1%}，Q3−Q1 = 0，会退回标准差（对零膨胀不稳健）")
        )
    if zero_ratio >= 1 - MAD_MIN_NONZERO:
        warnings.append(
            Warning("mad", f"零值占 {zero_ratio:.1%}，MAD = 0（比 IQR 更早退回标准差）")
        )
    if n_nonzero < MIN_NONZERO_SAMPLES:
        warnings.append(
            Warning("zero_inflated_iqr", f"非零点只有 {n_nonzero} 个（< {MIN_NONZERO_SAMPLES}），幅度估不准")
        )
    if looks_like_counts:
        warnings.append(Warning("zscore", "计数型数据近似泊松，用标准差标准化会失真"))

    if not warnings:
        return Capability(n, zero_ratio, n_nonzero, looks_like_counts, probe_scales, "ok", [], "")
    return Capability(
        n, zero_ratio, n_nonzero, looks_like_counts, probe_scales,
        "unsuitable", warnings, "；".join(w.reason for w in warnings),
    )
```

- [ ] **Step 3: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/platform/test_capability.py -q
git add src/anomaly_lab/platform/capability.py tests/platform/test_capability.py
git commit -m "feat(platform): 数据能力探测（零膨胀/计数型/不可判）"
```

---

### Task 2.4：试跑返回 capability，前端显示警告

**Files:**
- Modify: `src/anomaly_lab/web/platform_routes.py:527-620`
- Create: `frontend/src/features/jobs/CapabilityWarning.tsx`
- Modify: `frontend/src/features/jobs/TestRunPanel.tsx`（**不是 JobConfigPanel** —— 它没有试跑数据）
- Modify: `frontend/src/api/types.ts`
- Test: `tests/web/test_test_run_api.py`（追加）
- Test: `frontend/src/features/jobs/capabilityWarning.test.tsx`

- [ ] **Step 1: 写失败测试（后端）**

```python
def test_试跑返回能力警告(tmp_path):
    # ⚠️ 本文件的 helper 是 `_client`（返回 client/store/job_id），不是 `_make_store`
    client, _store, job_id = _client(tmp_path)
    body = client.post(f"/api/platform/jobs/{job_id}/test-run").json()
    # ⚠️ 前端 TestRunPanel 渲染的是 `results`（不是 `series`）—— 两处都要带
    caps = [item.get("capability") for item in body["results"]]
    assert caps and caps[0]["verdict"] in {"ok", "unsuitable", "undetermined"}
```

- [ ] **Step 2: 后端算并返回**

在 `test-run` 里对每条序列：

```python
from anomaly_lab.platform.capability import probe

cap = probe(values)
cap_payload = {
    "zero_ratio": cap.zero_ratio,
    "n_nonzero": cap.n_nonzero,
    "verdict": cap.verdict,
    "warnings": [{"detector": w.detector, "reason": w.reason} for w in cap.warnings],
    "message": cap.message,
}
entry["capability"] = cap_payload
# ⚠️ `results` 与 `series` 是两份数据，且 `results` 是**内联 dict**（没有变量名）。
#    在正常分支的 `results.append({...})` 里直接加一行：
#        "capability": cap_payload,
#    数据不足分支没有 values，无法 probe —— 不加（前端只在 sufficient 时读）。
```

- [ ] **Step 3: 写失败测试（前端）**

```tsx
it('命中所选算法时显示警告', () => {
  render(
    <CapabilityWarning
      detector="iqr"
      capability={{
        verdict: 'unsuitable',
        warnings: [{ detector: 'iqr', reason: '零值占 97.6%，Q3−Q1 = 0' }],
      }}
    />,
  )
  expect(screen.getByText(/零值占 97.6%/)).toBeInTheDocument()
})

it('警告不是当前算法时不显示', () => {
  const { container } = render(
    <CapabilityWarning
      detector="seasonal"
      capability={{ verdict: 'unsuitable', warnings: [{ detector: 'iqr', reason: 'x' }] }}
    />,
  )
  expect(container).toBeEmptyDOMElement()
})
```

- [ ] **Step 4: 前端实现并挂到 TestRunPanel**

```tsx
import { Alert } from 'antd'

export interface CapabilityWarningProps {
  detector: string
  capability: {
    verdict: string
    warnings: { detector: string; reason: string }[]
  } | null | undefined
}

export function CapabilityWarning({ detector, capability }: CapabilityWarningProps) {
  if (!capability || capability.verdict === 'ok') return null
  const hit = capability.warnings.find((w) => w.detector === detector)
  if (!hit) return null
  return (
    <Alert
      type="warning"
      showIcon
      message={`当前算法在这个指标上不可靠：${hit.reason}`}
      description="它会退回标准差兜底：能跑，但对零膨胀数据不稳健，容易漏报或误报。"
    />
  )
}
```

在 `TestRunPanel` 结果区顶部渲染 `<CapabilityWarning detector={...} capability={...} />`。

- [ ] **Step 5: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/web/test_test_run_api.py -q
cd frontend && npx tsc -b && npx vitest run
git add -A && git commit -m "feat: 试跑返回数据能力警告，结果区直接提示算法会失效"
```

---

# Chunk 3：决策链（批次 D）

> 目标：每次 run 都能回答「为什么选这个算法、阈值怎么定的、用了哪个尺度」。

### Task 3.1：`DecisionTrace` 结构 + 落库

**Files:**
- Create: `src/anomaly_lab/platform/decisions.py`
- Modify: `src/anomaly_lab/platform/runner.py:280-345`
- Modify: `src/anomaly_lab/platform/store.py`（schema + migrate + record）
- Test: `tests/platform/test_decision_trace.py`

- [ ] **Step 1: 写失败测试**

```python
import json

from anomaly_lab.platform.decisions import DecisionTrace


def test_决策链只保留非空段():
    trace = DecisionTrace(
        classify={"metric_class": "sparse_event", "confidence": 0.9},
        select={"detector": "event_count", "requested": "auto"},
    )
    data = trace.to_dict()
    assert set(data) == {"classify", "select"}
    assert data["select"]["detector"] == "event_count"


def test_运行结果落库后能读回决策链(tmp_path):
    from anomaly_lab.platform.store import PlatformStore

    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id, name="cpu",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts", value_column="value",
    )
    job = store.add_job(
        metric_id=metric.id, name="job", detector="iqr",
        alert_threshold=2.5, critical_threshold=4.0,
        window_points=60, interval_seconds=300,
    )
    # ⚠️ run_series 有外键，必须先有 runs 行
    run = store.create_run(job.id)
    store.finish_run(run.id, "success", n_series=1, n_alerts=0)
    store.record_run_series(
        run.id,
        # ⚠️ file 不能为空 —— detection_records() 的 SQL 带 `WHERE rs.file <> ''`
        [{"series_id": "s", "file": "x.npz", "decision": {"select": {"detector": "iqr"}}}],
    )

    rows = store.detection_records()
    assert json.loads(rows[0]["decision_json"])["select"]["detector"] == "iqr"
```

- [ ] **Step 2: 实现结构**

```python
"""一次检测的决策链 —— 跑的时候填充，不重算。

⚠️ 原则：**记录的是「屏幕上看到的那份结果」**。
   trace 的每一段都必须来自本次 run 实际用到的对象，
   不能事后根据配置推断（配置改过就对不上了）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionTrace:
    quality: dict[str, Any] = field(default_factory=dict)
    capability: dict[str, Any] = field(default_factory=dict)
    classify: dict[str, Any] = field(default_factory=dict)
    select: dict[str, Any] = field(default_factory=dict)
    threshold: dict[str, Any] = field(default_factory=dict)
    detect: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value}
```

- [ ] **Step 3: runner 填充（**关键：先 probe**）**

在 `_compute_job` 的序列循环里，拿到 `values` 之后、检测之前：

```python
from anomaly_lab.platform.capability import probe

cap = probe(series.values)
```

序列处理完后组装：

```python
trace = DecisionTrace(
    quality={
        "n": series.n,
        "n_missing": int(series.meta.get("n_missing", 0)),
        "zero_ratio": round(cap.zero_ratio, 4),
        "n_nonzero": cap.n_nonzero,
    },
    capability={
        "verdict": cap.verdict,
        "scale_probe": cap.scale_probe,
        "warnings": [{"detector": w.detector, "reason": w.reason} for w in cap.warnings],
    },
    classify={
        "metric_class": resolution.metric_class,
        "confidence": resolution.confidence,
        "reasons": resolution.reasons,
        "candidates": resolution.candidates,
    },
    select={
        "detector": resolution.detector,
        "requested": resolution.requested,
        "fallback": resolution.fallback,
        "rationale": resolution.rationale,
    },
    threshold={
        "scale_source": result.scale_source,
        "status": result.status,
        "rules": rules_to_dicts(rules),
    },
    detect={
        "n_alerts": int((severity > SEVERITY_NORMAL).sum()),
        "n_p0": int((severity == top_level).sum()),
    },
)
entry["decision"] = trace.to_dict()
```

- [ ] **Step 4: 落库（带迁移）**

`_SCHEMA` 的 `run_series` 增加：

```sql
  decision_json TEXT NOT NULL DEFAULT '',
```

`_migrate` 增加（照抄现有 `run_series` 列迁移的写法）：

```python
run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(run_series)")}
if "decision_json" not in run_columns:
    conn.execute(
        "ALTER TABLE run_series ADD COLUMN decision_json TEXT NOT NULL DEFAULT ''"
    )
```

`record_run_series` 增加一列（注意占位符数量从 16 变 17）：

```python
str(json.dumps(entry.get("decision") or {}, ensure_ascii=False)),
```

- [ ] **Step 5: `detection_records` 读出来**

`store.detection_records()` 的 SELECT 里加上 `decision_json`。

- [ ] **Step 6: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/platform/test_decision_trace.py -q
.venv/bin/python -m pytest -q
git add -A && git commit -m "feat(platform): 记录每次检测的决策链"
```

---

### Task 3.2：前端时间线

**Files:**
- Create: `frontend/src/features/evaluation/DecisionTraceTimeline.tsx`
- Modify: `src/anomaly_lab/web/platform_routes.py:760-815`（preview 返回 `decision`）
- Modify: `frontend/src/api/types.ts`（`Preview.decision`、`DecisionTraceData`）
- Modify: `frontend/src/pages/job/JobDetectionsPanel.tsx`
- Test: `frontend/src/features/evaluation/decisionTrace.test.tsx`

- [ ] **Step 1: 后端返回 + 类型**

`preview()` 只有**两个** return 分支（数据不足 / 正常）。

- 正常分支：加 `"decision": entry.get("decision") or {}`；
- 数据不足分支：没有检测结果，加 `"decision": {}` 即可（前端会整块不渲染）。

```ts
/** 一次检测的决策链。各段按需存在，老数据可能没有。 */
export interface DecisionTraceData {
  quality?: Record<string, unknown>
  capability?: Record<string, unknown>
  classify?: Record<string, unknown>
  select?: Record<string, unknown>
  threshold?: Record<string, unknown>
  detect?: Record<string, unknown>
}
```

- [ ] **Step 2: 组件（带签名）**

```tsx
import type { ReactNode } from 'react'
import type { DecisionTraceData } from '../../api/types'

type StepKey = keyof DecisionTraceData

const STEPS: ReadonlyArray<readonly [StepKey, string]> = [
  ['quality', '数据质量'],
  ['capability', '能力探测'],
  ['classify', '形态判断'],
  ['select', '算法选择'],
  ['threshold', '阈值与分级'],
  ['detect', '结果'],
]

/** 每一步的一行人话摘要。缺字段时返回 null（整步不显示）。 */
function summary(key: StepKey, step: Record<string, unknown>): ReactNode {
  switch (key) {
    case 'quality':
      return `${step.n} 点 · 零值 ${(Number(step.zero_ratio) * 100).toFixed(1)}% · 缺 ${step.n_missing}`
    case 'capability': {
      if (step.verdict === 'ok') return '无失效风险'
      // ⚠️ Record<string, unknown> 下必须先收窄，否则 TS7053
      const warnings = Array.isArray(step.warnings) ? step.warnings : []
      const first = warnings[0] as { reason?: string } | undefined
      return first?.reason ?? String(step.verdict ?? '')
    }
    case 'classify':
      return `${String(step.metric_class ?? '—')}（${Number(step.confidence ?? 0).toFixed(2)}）`
    case 'select':
      return `${String(step.requested ?? '')} → ${String(step.detector ?? '')}${step.fallback ? '（回退）' : ''}`
    case 'threshold':
      return `尺度 ${String(step.scale_source ?? '—')} · ${step.status === 'undetermined' ? '无法判定' : '正常'}`
    case 'detect':
      return `${step.n_alerts ?? 0} 个告警点 · ${step.n_p0 ?? 0} 条 P0`
    default:
      return null
  }
}

function isWarn(key: StepKey, step: Record<string, unknown>): boolean {
  if (key === 'capability') return step.verdict !== 'ok'
  if (key === 'select') return Boolean(step.fallback)
  if (key === 'threshold') return step.status === 'undetermined' || step.scale_source === 'std'
  return false
}

export function DecisionTraceTimeline({ trace }: { trace: DecisionTraceData }) {
  return (
    <ol className="decision-trace">
      {STEPS.map(([key, title]) => {
        const step = trace[key]
        if (!step) return null
        return (
          <li
            key={key}
            className={`decision-trace__step${isWarn(key, step) ? ' decision-trace__step--warn' : ''}`}
          >
            <strong>{title}</strong>
            <span className="decision-trace__summary">{summary(key, step)}</span>
            <details>
              <summary>原始数字</summary>
              <pre className="mono">{JSON.stringify(step, null, 2)}</pre>
            </details>
          </li>
        )
      })}
    </ol>
  )
}
```

⚠️ `step.warnings?.[0]?.reason` 在 `Record<string, unknown>` 下需要收窄：

```tsx
const warnings = Array.isArray(step.warnings) ? step.warnings : []
const first = warnings[0] as { reason?: string } | undefined
```

- [ ] **Step 3: 测试 + 挂载**

```tsx
it('渲染六段并高亮回退', () => {
  render(<DecisionTraceTimeline trace={{ select: { requested: 'auto', detector: 'iqr', fallback: true } }} />)
  expect(screen.getByText('算法选择')).toBeInTheDocument()
  expect(document.querySelector('.decision-trace__step--warn')).not.toBeNull()
})
```

在 `JobDetectionsPanel` 的详情区渲染 `<DecisionTraceTimeline trace={preview.decision ?? {}} />`。

- [ ] **Step 4: 验证 + 提交**

```bash
cd frontend && npx tsc -b && npx vitest run src/features/evaluation
git add -A && git commit -m "feat(frontend): 检测记录展示决策链时间线"
```

---

# Chunk 4：算法补强（批次 E + F）

### Task 4.1：`poisson_count`

**Files:**
- Create: `src/anomaly_lab/detectors/zero_inflated.py`
- Test: `tests/detectors/test_zero_inflated.py`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.zero_inflated import PoissonCountDetector


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle(
        series_id="s",
        values=values,
        timestamps=np.arange(len(values)).astype("datetime64[m]"),
        freq="1min",
    )


def test_一次是正常抖动十次才算异常():
    # 每 30 分钟出现一次 1（正常抖动），第 200 点出现 10 次
    values = np.zeros(300)
    values[::30] = 1.0
    values[200] = 10.0

    result = PoissonCountDetector(window=30).detect(_series(values))

    assert not result.is_anomaly[100]      # 1 次不报
    assert result.is_anomaly[200]          # 10 次必报


def test_连续小突发靠窗口累计():
    values = np.zeros(300)
    values[::30] = 1.0
    values[100:105] = 2.0                  # 连续 5 分钟各 2 次

    result = PoissonCountDetector(window=10).detect(_series(values))

    assert result.is_anomaly[100:105].any()


def test_零值不会被误报():
    values = np.zeros(100)
    result = PoissonCountDetector(window=10).detect(_series(values))
    assert not result.is_anomaly.any()
```

- [ ] **Step 2: 实现**

```python
"""稀疏 / 计数型数据的专用检测器。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.base import TimedDetector
from anomaly_lab.detectors.scale import robust_scale


class PoissonCountDetector(TimedDetector):
    """计数值 vs 泊松期望 —— 单点 + 窗口累计，取较大者。

    ⚠️ 和 `event_count` 的区别：
       `event_count` 先二值化，只数「有几个点非零」——
       1 次和 10 次完全一样；
       这里直接用**值本身**当计数，所以强度是看得见的。

    ⚠️ 分数是 **P(X < 观测值)**（累计概率），越大越异常 ——
       与项目「分数越大越异常」的约定一致。
       ⚠️ 不要用 `poisson.sf`：它返回的是 p 值，越小越异常，
          方向正好相反，而且 value=0 时恒等于 1。
    """

    name = "poisson_count"
    score_type = "prob"
    default_threshold = 0.99

    def __init__(self, window: int = 10, threshold: float = 0.99) -> None:
        if window < 2:
            raise ValueError("window 至少为 2")
        self.window = int(window)
        self.default_threshold = float(threshold)
        self._last_scale_source = "poisson"

    def fit(self, series: SeriesBundle) -> PoissonCountDetector:
        return self

    def detect(self, series: SeriesBundle, threshold: float | None = None):
        return self._timed_detect(series, threshold)

    def score(self, series: SeriesBundle) -> np.ndarray:
        from scipy.stats import poisson

        values = np.asarray(series.values, dtype=float)
        # 基线 λ：扩张均值 + shift(1) —— 因果，不含当前点也不含未来
        fallback = float(values.mean()) if values.size else 0.0
        rate = (
            pd.Series(values)
            .expanding(min_periods=2)
            .mean()
            .shift(1)
            .fillna(fallback)
            .clip(lower=1e-3)          # λ=0 会让第一次出现变成「无穷倍」
            .to_numpy()
        )

        # ① 单点：这一分钟爆了
        p_point = poisson.cdf(values - 1, rate)

        # ② 窗口累计：这几分钟一直在出（λ 随有效窗口长度缩放）
        sums = pd.Series(values).rolling(self.window, min_periods=1).sum().to_numpy()
        effective = (
            pd.Series(values).rolling(self.window, min_periods=1).count().to_numpy()
        )
        p_window = poisson.cdf(sums - 1, rate * effective)

        return np.maximum(p_point, p_window)
```

- [ ] **Step 3: 运行，确认通过**

```bash
.venv/bin/python -m pytest tests/detectors/test_zero_inflated.py -q
```

预期：`3 passed`（若 `test_一次是正常抖动十次才算异常` 的 `[100]` 被判异常，
把 `clip(lower=1e-3)` 调到 `0.02` —— 0.02 时 `cdf(0, 0.02)=0.980`，仍低于 0.99）。

- [ ] **Step 4: 提交**

```bash
git add src/anomaly_lab/detectors/zero_inflated.py tests/detectors/test_zero_inflated.py
git commit -m "feat(detectors): 泊松计数检测器（单点爆发 + 窗口累计）"
```

---

### Task 4.2：`zero_inflated_iqr`

**Files:**
- Modify: `src/anomaly_lab/detectors/zero_inflated.py`
- Test: `tests/detectors/test_zero_inflated.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_非零幅度异常能报出来():
    from anomaly_lab.detectors.zero_inflated import ZeroInflatedIQRDetector

    # ⚠️ 非零点必须 ≥ 30（实现的门槛），且幅度要有变化（否则 IQR=0）
    values = np.zeros(300)
    idx = np.arange(0, 300, 4)[:60]              # 60 个非零点
    values[idx] = 4 + (np.arange(60) % 4)        # 4/5/6/7 循环 → IQR > 0
    values[idx[30]] = 50.0                       # 一个幅度异常

    result = ZeroInflatedIQRDetector(k=3.0).detect(_series(values))
    assert result.is_anomaly[idx[30]]
    assert not result.is_anomaly[idx[10]]


def test_非零点太少时标记无法判定():
    from anomaly_lab.detectors.zero_inflated import ZeroInflatedIQRDetector

    values = np.zeros(300)
    values[10] = values[20] = 5.0               # 只有 2 个非零点
    result = ZeroInflatedIQRDetector().detect(_series(values))
    assert result.status == "undetermined"
```

- [ ] **Step 2: 实现**

```python
MIN_NONZERO_SAMPLES = 30


class ZeroInflatedIQRDetector(TimedDetector):
    """零膨胀两段模型：零点不判，非零部分用 IQR 估幅度。

    ⚠️ 为什么不能直接用 iqr：
       零值 >75% 时 IQR = 0；零值 >50% 时 MAD = 0。
       把非零子集单独拿出来估，分母才有意义。

    ⚠️ 非零点 < 30 时**不装懂** —— 分位数估不准，标「无法判定」。
    """

    name = "zero_inflated_iqr"
    score_type = "zscore"
    default_threshold = 3.0

    def __init__(self, k: float = 3.0) -> None:
        self.k = float(k)
        self.default_threshold = float(k)

    def fit(self, series: SeriesBundle) -> ZeroInflatedIQRDetector:
        return self

    def detect(self, series: SeriesBundle, threshold: float | None = None):
        return self._timed_detect(series, threshold)

    def score(self, series: SeriesBundle) -> np.ndarray:
        values = np.asarray(series.values, dtype=float)
        mask = values != 0
        n_nonzero = int(mask.sum())
        scores = np.zeros_like(values)

        if n_nonzero < MIN_NONZERO_SAMPLES:
            self._last_scale_source = "none"
            self._last_status = "undetermined"
            return scores

        sub = values[mask]
        med = float(np.median(sub))
        est = robust_scale(sub, prefer="iqr")
        self._last_scale_source = est.source
        self._last_status = "ok" if est.source != "none" else "undetermined"
        if est.source == "none":
            return scores

        scores[mask] = np.abs(sub - med) / est.value
        return scores
```

> ⚠️ `_last_status` 由 `TimedDetector._timed_detect` 读取（Task 1.2 Step 5），
> 不需要覆盖 `detect()` 之外的东西。

- [ ] **Step 3: 运行，确认通过**

```bash
.venv/bin/python -m pytest tests/detectors/test_zero_inflated.py -q
```

预期：`5 passed`

- [ ] **Step 4: 提交**

```bash
git add -A && git commit -m "feat(detectors): 零膨胀 IQR（非零子集估幅度）"
```

---

### Task 4.3：注册三个检测器（`event_count` 目前平台不可选）

**Files:**
- Modify: `src/anomaly_lab/platform/detectors.py:1-45,268-309`（注册 + 模块头说明）
- Modify: `frontend/src/lib/detectorLabels.ts`
- Modify: `tests/platform/test_auto_detector.py`
- Modify: `tests/evaluation/test_auto_validation.py`
- Test: `tests/platform/test_detector_registry.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
from anomaly_lab.platform.detectors import detector_catalog


def test_新检测器都在平台清单里():
    rows = {row["name"]: row for row in detector_catalog()}
    for name in ("event_count", "poisson_count", "zero_inflated_iqr"):
        assert name in rows, name
        assert rows[name]["available"] is True, name
```

- [ ] **Step 2: 注册**

```python
from anomaly_lab.detectors.statistical import EventCountDetector
from anomaly_lab.detectors.zero_inflated import (
    PoissonCountDetector,
    ZeroInflatedIQRDetector,
)

DETECTOR_FACTORIES = {
    ...,
    "event_count": EventCountDetector,
    "poisson_count": PoissonCountDetector,
    "zero_inflated_iqr": ZeroInflatedIQRDetector,
}

DETECTOR_LABELS = {
    ...,
    "event_count": "事件计数",
    "poisson_count": "泊松计数",
    "zero_inflated_iqr": "零膨胀 IQR",
}
```

同时**改模块头的说明**。它现在写着「只有能给出基线+双向上下界的算法才进入平台」
「分数统一是稳健 z 分数」，并说 Chronos 是唯一例外。新增三个检测器后这句话不再成立：

```python
"""检测器注册表与可用性探测。

⚠️ 平台上的检测器分两类：
    - **带基线**（iqr / mad / zscore / seasonal / stl_residual /
      trend_residual_iqr / theil_sen）：`bands()` 给出 expected/lower/upper，
      前端能画「实际 vs 基线 ± 容忍带」；
    - **无基线**：
      · `event_count` / `poisson_count` / `chronos` —— prob 族，分数是累计概率，
        阈值是 0.99 量级，**不能**和尺度族混用；
      · `zero_inflated_iqr` —— 仍是 z 分数（尺度族），只是不提供 `bands()`。

⚠️ Chronos 不是唯一例外了 —— 别再按「唯一例外」理解这段。
"""
```

- [ ] **Step 3: 更新 auto 断言（注册后行为变了）**

`tests/platform/test_auto_detector.py` 里把那条测试**改名并改断言**：

```python
def test_auto_picks_the_recommended_detector_when_supported():
    """首选算法现在平台支持了 —— 不该再回退到 iqr。"""
    from anomaly_lab.classification.classifier import classify

    sparse = np.zeros(240)
    sparse[::60] = 5.0
    assert classify(_bundle(sparse)).recommendation.detectors == [
        "event_count",
        "iqr",
    ]
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(sparse))
    assert resolution.detector == "event_count"
    assert resolution.fallback is False
```

- [ ] **Step 4: 更新评测集合的断言**

`tests/evaluation/test_auto_validation.py::test_validation_reports_per_detector_means`
断言集合**恰好**是 7 个名字；注册后 `DEFAULT_DETECTOR_SET` 变成 10 个，会红。
把期望集合补上三个：

```python
    assert set(report.detector_mean_f1) == {
        "iqr", "mad", "zscore", "seasonal", "stl_residual",
        "trend_residual_iqr", "theil_sen",
        "event_count", "poisson_count", "zero_inflated_iqr",
    }
```

- [ ] **Step 5: 前端标签同步**

后端注释写明前端另有一份同源映射，**两份要一起改**：

```ts
  event_count: '事件计数',
  poisson_count: '泊松计数',
  zero_inflated_iqr: '零膨胀 IQR',
```

- [ ] **Step 6: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/platform tests/evaluation -q
cd frontend && npx tsc -b && npx vitest run
git add -A && git commit -m "fix(platform): 注册事件计数/泊松计数/零膨胀 IQR"
```

---

### Task 4.4：`event_count` 因果修正

**Files:**
- Modify: `src/anomaly_lab/detectors/statistical.py:440-478`
- Test: `tests/detectors/test_event_count.py`（新建）
- Modify: `docs/PITFALLS.md`

- [ ] **Step 1: 写失败测试（必须能区分 center=True / False）**

> ⚠️ 关键：把爆发放在 190，断言 **185** 的分数。
> 185 的居中窗口是 175–195（含爆发），因果窗口是 166–185（不含）。
> 断言 100 这种点区分不出来 —— 两种实现都是 0。

```python
import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.statistical import EventCountDetector


def _series(values):
    values = np.asarray(values, dtype=float)
    return SeriesBundle("s", values, np.arange(len(values)).astype("datetime64[m]"), "1min")


def test_不使用未来数据():
    values = np.zeros(200)
    values[190:200] = 1.0
    result = EventCountDetector(window=20).detect(_series(values))

    assert result.scores[185] == 0.0      # ⚠️ 居中窗口会把 190–195 算进来
    assert result.scores[195] > 0.0       # 因果窗口能看到刚发生的爆发


def test_有效窗口长度参与期望():
    values = np.ones(50)
    result = EventCountDetector(window=20).detect(_series(values))
    assert not result.is_anomaly.any()
```

- [ ] **Step 2: 改实现**

```python
        counts = (
            pd.Series(nonzero)
            .rolling(window=self.window, min_periods=1)          # ⚠️ 去掉 center=True
            .sum()
            .to_numpy()
        )
        effective = (
            pd.Series(nonzero)
            .rolling(window=self.window, min_periods=1)
            .count()
            .to_numpy()
        )
        # λ 也必须是因果的：扩张均值 + shift(1)，第一个点用全局率兜底
        fallback = float(nonzero.mean())
        rate = (
            pd.Series(nonzero)
            .expanding(min_periods=2)
            .mean()
            .shift(1)
            .fillna(fallback)
            .to_numpy()
        )
        return poisson.cdf(counts - 1, np.maximum(rate * effective, 1e-6))
```

- [ ] **Step 3: 记录评估会下降**

`docs/PITFALLS.md`：

```markdown
## `event_count` 用过未来数据（2026-11-06 修）

`rolling(..., center=True)` 给 t 点打分时包含了 t+1…t+25。
离线评估因此**偏高**，上线后最后 25 点行为不一致。

改成因果窗口后，评估数字会下降 —— 这是**修正**，不是回归。
代价：爆发结束后窗口计数仍保留 w 个点（尾部拖长），属预期。
```

- [ ] **Step 4: 验证 + 提交**

```bash
.venv/bin/python -m pytest tests/detectors/test_event_count.py -q
git add -A && git commit -m "fix(detectors): event_count 改用因果窗口，λ 改用扩张均值"
```

---

### Task 4.5：修推荐规则

> ⚠️ 放在 Chunk 4 最后：`zero_inflated_iqr` / `poisson_count` 要先注册，
> 否则中间版本会走回退分支并在 rationale 里写「平台不支持」。

**Files:**
- Modify: `src/anomaly_lab/classification/recommend.py:60-74`
- Test: `tests/classification/test_recommend.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
from anomaly_lab.classification.recommend import recommend_for


def test_高零值比例不推荐iqr():
    # ⚠️ MetricClass 是 Literal 类型别名，不是 Enum —— 直接用字符串
    rec = recommend_for("high_zero_ratio")
    assert rec.detectors[0] == "zero_inflated_iqr"


def test_稀疏事件推荐泊松计数():
    rec = recommend_for("sparse_event")
    assert rec.detectors[0] == "poisson_count"
```

- [ ] **Step 2: 改规则（参数写全，不留占位符）**

```python
    "high_zero_ratio": (
        ["zero_inflated_iqr", "event_count", "iqr"],
        {
            "zero_inflated_iqr": {"k": [2.0, 4.0]},
            "event_count": {"window": [20, 100]},
            "iqr": {"k": [2.0, 4.0]},
        },
        "零值会破坏 IQR/MAD 的分母；先看非零部分的幅度，或看事件频率",
    ),
    "sparse_event": (
        ["poisson_count", "event_count", "zero_inflated_iqr"],
        {
            "poisson_count": {"window": [10, 100]},
            "event_count": {"window": [20, 100]},
            "zero_inflated_iqr": {"k": [2.0, 4.0]},
        },
        "稀疏事件先看「发生了多少次」（泊松），幅度只有在非零点足够多时才估得准",
    ),
```

- [ ] **Step 3: 再更新一次 auto 断言**

推荐表变了，`tests/platform/test_auto_detector.py` 会再次变红：

```python
    assert classify(_bundle(sparse)).recommendation.detectors == [
        "poisson_count",
        "event_count",
        "zero_inflated_iqr",
    ]
    resolution = resolve_detector(AUTO_DETECTOR, _bundle(sparse))
    assert resolution.detector == "poisson_count"
    assert resolution.fallback is False
```

> ⚠️ 只在 `tests/classification` 下跑是发现不了这条的 —— Step 4 必须跑全量。

- [ ] **Step 4: 验证 + 提交**

```bash
.venv/bin/python -m pytest -q            # ⚠️ 全量，不是只跑 classification
cd frontend && npx vitest run
git add -A && git commit -m "fix(classification): 高零值/稀疏事件改推零膨胀 IQR 与泊松计数"
```

---

## 验收清单

### 每批结束时都要跑

```bash
.venv/bin/python -m pytest -o addopts="" -p no:warnings -q
.venv/bin/ruff check scripts src tests
.venv/bin/python -m anomaly_lab.cli compliance-check
cd frontend && npx tsc -b && npx vitest run && npx vite build
```

### 全部完成后

- [ ] `job-runs` 上选 `iqr`：显示「尺度降级」或「无法判定」，不再是「一切正常」
- [ ] 建任务时选中 `iqr`，ⓘ 里能看到「零值 >75% 会失效」
- [ ] 试跑后 `zero_ratio=97.6%` 出现黄色警告 + 失效原因
- [ ] 检测记录详情能展开六段决策链，`fallback` / 降级高亮
- [ ] `poisson_count`：1 次不报、10 次必报
- [ ] `zero_inflated_iqr`：非零点 <30 时显示「幅度不可判」
- [ ] `event_count` 的评估数字**下降**（因果修正）
- [ ] 正常数据的分数逐点不变（Chunk 1 回归）
- [ ] 全量测试绿：后端 ≥ 835（预计 839）、前端 ≥ 412（预计 414）

### 提交节奏

| 批次 | 建议 tag |
|---|---|
| Chunk 1 | `v0.3.0-scale-fallback` |
| Chunk 2 | `v0.3.1-capability` |
| Chunk 3 | `v0.3.2-decision-trace` |
| Chunk 4 | `v0.4.0-sparse-detectors` |

---

## 风险与开放项

| 风险 | 应对 |
|---|---|
| Chunk 1 改动面广（所有统计检测器） | 「正常数据分数逐点不变」做回归门禁；先合 A 再动 UI |
| `_last_scale_source` 是实例状态，多序列复用同一检测器实例时可能串味 | 每次 `score()` 都会重设；如果 `resolve_detector` 复用实例，改为每次 `create_detector` |
| `scale_source` 只记众数，不是逐点 | 逐点来源放 `decision.capability.scale_probe`，够用即可 |
| `scale_source` 的取值集合扩到 `poisson` | `poisson_count` 的「尺度」是泊松率，不是统计尺度 —— 契约注释里写清楚，前端只做展示 |
| `seasonal` 的来源是近似（相位组 + 全局兜底） | 只影响展示，不影响分数；需要精确时再拆到逐相位 |
| `decision_json` 让 `run_series` 变大 | 每条几百字节；108 条约几十 KB，可接受 |
| `poisson_count` 对过度离散敏感 | 先只看 demo 数据；真实数据再加负二项开关 |
| 新检测器没有 `bands()` | 平台会得到 `None`，前端不画带 —— 这是**预期**，不是漏实现；在模块头注释里写明 |
| 前端时间线信息密度过高 | 默认一行摘要，原始数字折叠 |
| `zero_inflated_iqr` 的阈值语义 | 写在 guide 里：「非零部分几个 IQR」，不要和 `iqr` 混用 |
| `event_count` 评估下降 | 这是修正。合并前对比 before/after 的 F1，把差异写进 PR 描述 |
