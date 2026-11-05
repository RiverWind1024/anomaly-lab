"""预检的实验描述（P0 只用到 data 部分）。

⚠️ 这里用 dataclass 而不是 Pydantic —— 核心逻辑要能在没有 FastAPI 的测试里直接跑。
   API 层负责把请求体转成这里的 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from anomaly_lab.data.synthetic import ANOMALY_TYPES, METRIC_CLASSES

#: 数据来源。
#:
#: ⚠️ `synthetic` / `public` 是 P3 加的 —— 它们**自带真值标签**，
#:    是「有真值模式」唯一能立刻用的两类数据。
DATA_KINDS = ("metric", "sql", "synthetic", "public")

#: 真值来源。
#:
#: ⚠️ 合成与公开集的标签**随数据一起来**（`SeriesBundle.labels`），
#:    不需要在这里指定；只有「已有指标 / 临时 SQL」才要额外指明真值从哪来。
TRUTH_SOURCES = ("none", "annotation")


@dataclass(frozen=True)
class SamplingSpec:
    """采样参数。

    `window_points` 必须与未来任务的窗口一致 —— 这是「生产同构」的前提。
    """

    mode: str = "even"
    window_points: int = 500
    stride_points: int | None = None
    max_points: int = 10_000
    max_windows: int = 100
    min_valid_ratio: float = 0.8
    #: 预留给将来的随机采样；当前所有模式都是确定性的。
    seed: int = 42

    def __post_init__(self) -> None:
        if self.mode not in {"recent", "even", "stratified"}:
            raise ValueError(f"不支持的采样模式: {self.mode!r}")
        if self.window_points <= 0:
            raise ValueError("window_points 必须为正整数")
        if self.stride_points is not None and self.stride_points <= 0:
            raise ValueError("stride_points 必须为正整数")
        if self.max_points <= 0:
            raise ValueError("max_points 必须为正整数")
        if self.max_windows <= 0:
            raise ValueError("max_windows 必须为正整数")
        if not 0.0 <= self.min_valid_ratio <= 1.0:
            raise ValueError("min_valid_ratio 必须在 [0, 1] 内")


@dataclass(frozen=True)
class SyntheticSpec:
    """合成数据参数。

    ⚠️ **seed 决定全部数据**（基线形态、噪声、异常注入位置）——
       可复现要求它必须进 spec，否则同一份 spec 重跑会得到不同的数据。
    """

    metric_class: str = "stationary"
    n_points: int = 1000
    n_anomalies: int = 5
    #: 空 = 由生成器随机挑异常类型。
    anomaly_types: tuple[str, ...] = ()
    seed: int = 42

    def __post_init__(self) -> None:
        if self.metric_class not in METRIC_CLASSES:
            raise ValueError(f"未知形态: {self.metric_class!r}（可选：{METRIC_CLASSES}）")
        if self.n_points <= 0:
            raise ValueError("n_points 必须为正整数")
        if self.n_anomalies < 0:
            raise ValueError("n_anomalies 不能为负")
        for item in self.anomaly_types:
            if item not in ANOMALY_TYPES:
                raise ValueError(f"未知异常类型: {item!r}（可选：{ANOMALY_TYPES}）")


@dataclass(frozen=True)
class PublicSpec:
    """公开集参数。

    ⚠️ `nab` 自带点级异常标签；`ucr` 的标签存在缓存的 meta 里
       （`anomaly_intervals`）。两者都**不用于调参**，只用于泛化验证。
    """

    #: `nab` = Numenta Anomaly Benchmark；`ucr` = UCR 单序列。
    dataset: str = "nab"
    #: `ucr` 必填（序列名）；`nab` 留空 = 取缓存里的全部。
    name: str | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if self.dataset not in {"nab", "ucr"}:
            raise ValueError(f"未知公开集: {self.dataset!r}（可选：nab / ucr）")
        if self.dataset == "ucr" and not self.name:
            raise ValueError("ucr 必须给 name（序列名）")
        if self.limit <= 0:
            raise ValueError("limit 必须为正整数")


@dataclass(frozen=True)
class DataSpec:
    """一次预检要取哪段数据。

    `kind="metric"` 用已有指标；`kind="sql"` 用临时 SQL（不落库）；
    `kind="synthetic"` / `kind="public"` 用自带真值的数据（P3）。
    """

    kind: str
    start: datetime
    end: datetime
    metric_id: int | None = None
    source_id: int | None = None
    sql: str | None = None
    time_column: str | None = None
    value_column: str | None = None
    group_column: str | None = None
    time_format: str = "iso_utc"
    source_timezone: str = "UTC"
    #: 指标来源可省略（继承指标）；临时 SQL 必须给。
    freq: str | None = None
    missing_policy: str | None = None
    max_series: int = 20
    sampling: SamplingSpec = field(default_factory=SamplingSpec)
    #: 真值来源（`none` = 无真值，走「检出画像」那一套）。
    truth: str = "none"
    synthetic: SyntheticSpec = field(default_factory=SyntheticSpec)
    public: PublicSpec = field(default_factory=PublicSpec)

    def __post_init__(self) -> None:
        if self.kind not in DATA_KINDS:
            raise ValueError(f"不支持的数据来源: {self.kind!r}（可选：{DATA_KINDS}）")
        if self.truth not in TRUTH_SOURCES:
            raise ValueError(f"不支持的真值来源: {self.truth!r}（可选：{TRUTH_SOURCES}）")
        if self.start.tzinfo is None:
            object.__setattr__(self, "start", self.start.replace(tzinfo=UTC))
        if self.end.tzinfo is None:
            object.__setattr__(self, "end", self.end.replace(tzinfo=UTC))
        if self.end <= self.start:
            raise ValueError("end 必须晚于 start")
        if self.max_series <= 0:
            raise ValueError("max_series 必须为正整数")
        if self.kind == "metric" and self.metric_id is None:
            raise ValueError("kind=metric 时必须提供 metric_id")
        if self.kind == "synthetic" and self.freq is None:
            raise ValueError("kind=synthetic 时必须给 freq —— 合成数据没有指标可继承")
        if self.kind == "sql":
            missing = [
                name
                for name, value in (
                    ("source_id", self.source_id),
                    ("sql", self.sql),
                    ("time_column", self.time_column),
                    ("value_column", self.value_column),
                    ("freq", self.freq),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"kind=sql 时缺少字段: {', '.join(missing)}")
