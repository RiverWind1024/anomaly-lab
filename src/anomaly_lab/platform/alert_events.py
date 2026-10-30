"""把一次运行的检测结果汇总成「告警事件」。

定位：告警事件的**读侧模型**。告警明细不在数据库里 —— 它躺在每次运行的
npz 里（逐点的 `severity` 数组），本模块负责把它读出来、聚合成区间。

⚠️ **以任务的最新一次运行为准**：平台任务是滚动窗口，同一段异常会被
连续多次运行重复报出。扫全部历史 run 会让同一个异常区间出现很多遍，
所以只取最新一次 —— 语义是「当前各任务处于什么告警状态」。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from anomaly_lab.platform.alerts import SEVERITY_NORMAL


@dataclass(frozen=True)
class AlertEvent:
    """一条告警事件：一段连续告警点合并成的区间。"""

    job_id: int
    job_name: str
    metric_id: int
    metric_name: str
    series_id: str
    group: str | None
    #: 档位名（来自任务的规则表，可能是 P0/P1，也可能是自定义的「注意」）
    level: str
    #: 档位序号，越大越严重（1 = 最低档）
    level_index: int
    start_ts: str
    end_ts: str
    #: 区间内的告警点数
    n_points: int
    #: 区间内的峰值分数
    max_score: float
    detector: str
    score_type: str
    run_id: int


def merge_alert_intervals(severity: np.ndarray) -> list[tuple[int, int, int]]:
    """把逐点 severity 合并成连续区间。

    返回 `[(起始下标, 结束下标, 区间内最高档位序号), ...]`（闭区间）。

    - `severity > 0` 的点算告警；`0` 是正常。
    - 连续的告警点合成一个区间；中间隔着正常点就断开。
    - 区间里的档位取**最大值**（最严重的那一档代表这个区间）。
    """
    severity = np.asarray(severity)
    if severity.size == 0:
        return []
    intervals: list[tuple[int, int, int]] = []
    start: int | None = None
    for index in range(len(severity)):
        if severity[index] > SEVERITY_NORMAL:
            if start is None:
                start = index
        elif start is not None:
            intervals.append((start, index - 1, int(severity[start:index].max())))
            start = None
    if start is not None:
        intervals.append((start, len(severity) - 1, int(severity[start:].max())))
    return intervals
