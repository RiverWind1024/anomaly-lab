"""平台层的记录模型：数据源、指标、检测任务、一次运行。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    """一个数据源；第一版只有 SQLite，kind 为后续插件预留。"""

    id: int
    name: str
    kind: str
    path: str
    created_at: str


@dataclass(frozen=True)
class Metric:
    """一条指标定义：SQL + 时间列/值列/分组列 + 采样频率。

    时间语义必须显式声明，不能猜：
    - `time_format` 说明时间列的存储形式；
    - `source_timezone` 说明无时区时间戳按哪个时区解释（对应 CloudWatch 的 MetricTimezone）；
    - `missing_policy` 说明缺失值怎么处理。
    """

    id: int
    source_id: int
    name: str
    query: str
    time_column: str
    value_column: str
    group_column: str | None
    time_format: str
    freq: str
    created_at: str
    source_timezone: str = "UTC"
    missing_policy: str = "drop"


@dataclass(frozen=True)
class Job:
    """一个检测任务：选指标、选算法、配阈值与频率。"""

    id: int
    metric_id: int
    name: str
    detector: str
    alert_threshold: float
    critical_threshold: float
    window_points: int
    interval_seconds: int
    enabled: bool
    last_run_at: str | None
    next_run_at: str | None
    created_at: str


@dataclass(frozen=True)
class Run:
    """一次任务执行的结果摘要；详细数组在 run_dir 下。"""

    id: int
    job_id: int
    status: str
    started_at: str
    finished_at: str | None
    n_series: int
    n_alerts: int
    error: str | None
