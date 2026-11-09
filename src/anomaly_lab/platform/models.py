"""平台层的记录模型：数据源、指标、检测任务、一次运行。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    """一个数据源。

    ⚠️ `config` 存 kind 专属参数（JSON）—— SQLite 用 `path` 列，
       HTTP 源用 config 里的 url / method / headers / format 等。
    """

    id: int
    name: str
    kind: str
    path: str
    created_at: str
    config: dict = field(default_factory=dict)


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
    """一个检测任务：选指标、选算法、配告警规则与频率。

    `alert_rules` 是「倍数 → 等级」的规则表，按倍数升序；判定以异常分数为准。
    `alert_threshold` / `critical_threshold` 是规则表的快捷视图（最低档/最高档倍数）。

    `alert_direction` 决定报哪一侧的异常（both / above / below）。
    方向按「值与检测器基线的比较」判断，不是按分数。
    """

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
    alert_rules: list[dict] = field(default_factory=list)
    #: 告警方向：both / above / below
    alert_direction: str = "both"
    #: 只对窗口最后 N 个点判定告警；0 = 检测整个窗口（旧行为）。
    #: 前 `window_points - detect_points` 个点仍参与基线统计，但不产生告警。
    detect_points: int = 0


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


@dataclass(frozen=True)
class Feedback:
    """一条人工反馈：某段时间内检测行为对不对。

    粒度对齐 CloudWatch 的告警反馈——按**时间范围**给，而不是逐点标注：
    `missed` = 该告警但没报；`false_alarm` = 不该报却报了；`correct` = 报得对；
    `other` = 其他原因（数据问题、已知变更等），不参与调参。
    """

    id: int
    job_id: int
    run_id: int | None
    series_id: str
    start_ts: str
    end_ts: str
    kind: str
    note: str
    created_at: str
