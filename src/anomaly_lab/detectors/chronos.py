"""Chronos 预训练模型适配器；权重不可用时优雅降级，不在 import 时下载。

⚠️ **加载必须离线**（`local_files_only=True`）：

huggingface.co 在本项目环境里不可达，`from_pretrained` 会**重试退避 ~540 秒**
才报错 —— 实测首次加载 542 秒，而真正加载完权重只要 0.05 秒。
进程级缓存只能救同一进程内的后续调用；**每次重启服务都要重付这 9 分钟**。

所以：
- 只认本地缓存（`local_files_only=True`）—— 有缓存秒加载，没缓存立刻失败；
- 权重要先下载好：用镜像端点单独跑一次下载脚本（见 README「Chronos 权重」）。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np

from anomaly_lab.contracts import DetectionResult, SeriesBundle
from anomaly_lab.detectors.bands import Bands
from anomaly_lab.detectors.base import TimedDetector

#: 默认模型。可以用 `ANOMALY_LAB_CHRONOS_MODEL` 换（例：`amazon/chronos-t5-tiny`）。
#:
#: 选 chronos-2 的原因（同一批合成序列实测，6 条形态各一条）：
#:   - 速度：326 ms/序列 vs chronos-t5-tiny 的 4021 ms —— **快 12 倍**
#:     （t5 是自回归逐 token 生成，chronos-2 是一次性预测）
#:   - 质量：平均 F1 0.210 vs 0.184
#: 代价是权重更大（456 MB vs 44 MB），首次下载要几分钟。
DEFAULT_MODEL_NAME = "amazon/chronos-2"

#: 兼容旧引用
MODEL_NAME = DEFAULT_MODEL_NAME

#: 已加载的 pipeline 缓存（按模型名）。
#:
#: 必须缓存：即使离线加载只要 0.05 秒，但**推理**本身不便宜 ——
#: 同一个进程里复用 pipeline 可以省掉重复的权重装载。
_PIPELINE_CACHE: dict[str, object] = {}


class ChronosUnavailable(RuntimeError):
    """chronos 包或本地权重不可用。"""


def default_model_name() -> str:
    """当前要用的模型名（可由环境变量覆盖）。"""
    return os.environ.get("ANOMALY_LAB_CHRONOS_MODEL", DEFAULT_MODEL_NAME).strip()


def _hf_cache_roots() -> list[Path]:
    roots = []
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


def _cache_pattern(model_name: str) -> str:
    """模型名 → 本地缓存目录的 glob 模式。

    `amazon/chronos-t5-tiny` → `models--amazon--chronos-t5-tiny`
    """
    return "models--" + model_name.replace("/", "--")


def chronos_available(model_name: str | None = None) -> bool:
    """chronos 包在不在、本地权重缓存有没有？"""
    if importlib.util.find_spec("chronos") is None:
        return False
    pattern = _cache_pattern(model_name or default_model_name())
    return any(
        any(root.glob(pattern)) for root in _hf_cache_roots() if root.exists()
    )


def _is_chronos2(model_name: str) -> bool:
    """是不是 Chronos-2 系列（需要单独的加载路径）。"""
    lowered = model_name.lower()
    return "chronos-2" in lowered or "chronos2" in lowered


def _pipeline_class(model_name: str):
    """按模型名选 pipeline 类 —— Chronos-2 是另一个类，接口兼容但类不同。"""
    from chronos import Chronos2Pipeline, ChronosPipeline

    if _is_chronos2(model_name):
        return Chronos2Pipeline
    return ChronosPipeline


def _is_chronos2(model_name: str) -> bool:
    """是不是 Chronos-2 系列（需要单独的加载路径）。"""
    lowered = model_name.lower()
    return "chronos-2" in lowered or "chronos2" in lowered


def _pipeline_class(model_name: str):
    """按模型名选 pipeline 类 —— Chronos-2 是另一个类，接口兼容但类不同。"""
    from chronos import Chronos2Pipeline, ChronosPipeline

    if _is_chronos2(model_name):
        return Chronos2Pipeline
    return ChronosPipeline


def _load_chronos2(model_name: str):
    """加载 Chronos-2：**绕开** `Chronos2Pipeline.from_pretrained`。

    ⚠️ 为什么不能直接用 `Chronos2Pipeline.from_pretrained`：
    它第一件事是调 `transformers.utils.peft_utils.find_adapter_config_file`
    查「是不是 LoRA 适配器」，而那个调用**既没有** `local_files_only`，
    **也无视** `HF_HUB_OFFLINE`（后者在 transformers import 时就被求值缓存了，
    运行时再设已经太晚）。网络不通时它会重试 5 次、每次超时，合计约 30 秒。

    这里复刻它后面的逻辑，但所有 hub 调用都显式 `local_files_only=True`。
    """
    from chronos import Chronos2Model, Chronos2Pipeline
    from chronos import chronos2 as chronos2_module
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(model_name, local_files_only=True)
    architecture = getattr(config, "architectures", ["Chronos2Model"])[0]
    model_class = getattr(chronos2_module, architecture, Chronos2Model)
    model = model_class.from_pretrained(
        model_name, config=config, local_files_only=True
    )
    return Chronos2Pipeline(model=model)


def _load_pipeline(model_name: str):
    """加载 pipeline（按模型名缓存到模块级）。

    ⚠️ `local_files_only=True` 是硬要求 —— 见模块 docstring：
    不加它，网络不通时会先退避 9 分钟才失败。
    """
    cached = _PIPELINE_CACHE.get(model_name)
    if cached is not None:
        return cached

    try:
        if _is_chronos2(model_name):
            pipeline = _load_chronos2(model_name)
        else:
            pipeline = _pipeline_class(model_name).from_pretrained(
                model_name, device_map="cpu", local_files_only=True
            )
    except Exception as exc:
        raise ChronosUnavailable(
            f"加载 {model_name} 失败（只认本地权重缓存）：{exc}"
        ) from exc
    _PIPELINE_CACHE[model_name] = pipeline
    return pipeline


class ChronosDetector(TimedDetector):
    """用预训练模型的分位数预测区间宽度/越界程度作为异常分数。"""

    name = "chronos"
    score_type = "prob"
    default_threshold = 0.5

    def __init__(
        self,
        model_name: str | None = None,
        window: int = 256,
        horizon: int = 64,
    ) -> None:
        self.model_name = model_name or default_model_name()
        self.window = int(window)
        self.horizon = int(horizon)
        self.pipeline = None

    def fit(self, series: SeriesBundle) -> ChronosDetector:
        if not chronos_available(self.model_name):
            raise ChronosUnavailable(
                f"{self.model_name} 未安装或本地无权重缓存；跳过该检测器"
            )
        try:
            self.pipeline = _load_pipeline(self.model_name)
        except Exception as exc:
            raise ChronosUnavailable(f"加载 Chronos 失败: {exc}") from exc
        return self

    def _predict(
        self, series: SeriesBundle
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """跑一遍预测，返回 (原始越界分数, 中位数预测, q10 下界, q90 上界)。

        分数与基线**同源**：分数就是「实际值越出 q10~q90 区间的程度 ÷ 区间宽度」，
        基线带就是那个区间本身。两边必须来自同一次预测，否则画的带和报的分数对不上。

        没有被预测覆盖的点（前 min_context 个、以及末尾不足一个 horizon 的尾巴）
        用 NaN 表示 —— 前端会把 NaN 变成 null 从而断线，不会画出一条假基线。
        """
        if self.pipeline is None:
            self.fit(series)
        assert self.pipeline is not None
        import torch

        values = np.asarray(series.values, dtype=float)
        n = len(values)
        scores = np.zeros(n)
        median = np.full(n, np.nan)
        low_band = np.full(n, np.nan)
        high_band = np.full(n, np.nan)
        context_len = min(self.window, max(8, n - self.horizon))
        # 从**最小上下文**开始滚动：原来从 context_len 才开始评分，
        # 前 256 点（占 51%）完全没打分，召回被结构性封顶在 49.8%。
        min_context = 8
        for start in range(min_context, n, self.horizon):
            ctx_len = min(context_len, start)
            context = values[start - ctx_len : start]
            target = values[start : start + self.horizon]
            if len(target) == 0 or len(context) == 0:
                continue
            # ⚠️ 两个版本的输入形状不同：
            #    v1（ChronosPipeline）收 (batch, history_length)
            #    v2（Chronos2Pipeline）收 (n_series, n_variates, history_length)
            tensor = torch.tensor(context, dtype=torch.float32)
            if _is_chronos2(self.model_name):
                tensor = tensor.unsqueeze(0).unsqueeze(0)
            else:
                tensor = tensor.unsqueeze(0)
            try:
                samples = self.pipeline.predict(tensor, prediction_length=len(target))
                arr = np.asarray(samples)
                low = np.quantile(arr.reshape(-1, len(target)), 0.1, axis=0)
                high = np.quantile(arr.reshape(-1, len(target)), 0.9, axis=0)
                mid = np.quantile(arr.reshape(-1, len(target)), 0.5, axis=0)
            except Exception as exc:
                raise ChronosUnavailable(f"Chronos 预测失败: {exc}") from exc
            width = np.maximum(high - low, 1e-6)
            outside = np.maximum(low - target, 0.0) + np.maximum(target - high, 0.0)
            end = start + len(target)
            scores[start:end] = outside / width
            median[start:end] = mid
            low_band[start:end] = low
            high_band[start:end] = high
        return scores, median, low_band, high_band

    def score(self, series: SeriesBundle) -> np.ndarray:
        raw, _, _, _ = self._predict(series)
        low, high = float(raw.min()), float(raw.max())
        if high - low < 1e-12:
            return np.zeros_like(raw)
        return (raw - low) / (high - low)

    def bands(self, series: SeriesBundle, threshold: float) -> Bands:
        """基线 = 模型预测中位数；带 = 预测的 q10~q90 分位区间。

        ⚠️ 这与统计型检测器的带**语义不同**：这里的带是模型自己的
        预测区间（表达「模型认为正常值在哪儿、有多不确定」），
        不是告警阈值边界 —— Chronos 的分数是序列内 min-max 归一的相对量。
        """
        _, median, low_band, high_band = self._predict(series)
        return Bands(
            baseline=median,
            lower=low_band,
            upper=high_band,
            detector=self.name,
            threshold=float(threshold),
            kind="prediction_interval",
        )

    def detect(
        self, series: SeriesBundle, threshold: float | None = None
    ) -> DetectionResult:
        return self._timed_detect(series, threshold)
