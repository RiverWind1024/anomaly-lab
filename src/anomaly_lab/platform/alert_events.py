"""把一次运行的检测结果汇总成「告警事件」。

定位：告警事件的**读侧模型**。

⚠️ **告警明细在数据库里**（`alert_events` 表）—— runner 写库时就记下了
   每次运行报出的区间，这里只负责读出来、拼上任务 / 指标信息。

⚠️ **以任务的最新一次运行为准**：平台任务是滚动窗口，同一段异常会被
连续多次运行重复报出。扫全部历史 run 会让同一个异常区间出现很多遍，
所以只取最新一次 —— 语义是「当前各任务处于什么告警状态」。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from anomaly_lab.platform.alerts import merge_alert_intervals

__all__ = [
    "AlertEvent",
    "collect_alert_events",
    "events_from_series",
    "merge_alert_intervals",
]


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


def _iso(ts: np.datetime64) -> str:
    """时间戳 → ISO 秒精度字符串（与 preview 端点的格式一致）。"""
    return str(np.datetime64(ts).astype("datetime64[s]"))


def events_from_series(
    *,
    severity: np.ndarray,
    timestamps: np.ndarray,
    scores: np.ndarray,
    levels: list[str],
    job_id: int,
    job_name: str,
    metric_id: int,
    metric_name: str,
    series_id: str,
    group: str | None,
    detector: str,
    score_type: str,
    run_id: int,
) -> list[AlertEvent]:
    """把一条序列的逐点 severity 转成告警事件列表。"""
    events: list[AlertEvent] = []
    for start, end, level_index in merge_alert_intervals(severity):
        level = levels[level_index] if 0 < level_index < len(levels) else "未知"
        window = scores[start : end + 1]
        events.append(
            AlertEvent(
                job_id=job_id,
                job_name=job_name,
                metric_id=metric_id,
                metric_name=metric_name,
                series_id=series_id,
                group=group,
                level=level,
                level_index=level_index,
                start_ts=_iso(timestamps[start]),
                end_ts=_iso(timestamps[end]),
                n_points=end - start + 1,
                max_score=float(window.max()) if window.size else 0.0,
                detector=detector,
                score_type=score_type,
                run_id=run_id,
            )
        )
    return events


def collect_alert_events(
    store, data_root: Path
) -> tuple[list[AlertEvent], list[dict]]:
    """汇总所有任务的告警事件 —— **从数据库读**。

    返回 `(events, skipped)`：
    - `events` 按开始时间**倒序**（新的在前）
    - `skipped` 列出没被纳入统计的任务与原因 —— **不能静默消失**

    ⚠️ 以每个任务的**最新一次运行**为准 —— 滚动窗口下同一段异常会被
    连续多次运行重复报出。

    ⚠️ 「这次运行没有告警」和「这次运行没同步进库」是两回事 ——
       前者正常，后者是数据缺失，必须说出来，否则任务会静默消失。
    """
    events: list[AlertEvent] = []
    skipped: list[dict] = []
    for job in store.list_jobs():
        try:
            metric = store.get_metric(job.metric_id)
        except ValueError:
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "指标已不存在"}
            )
            continue
        run = store.latest_run(job.id)
        if run is None:
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "还没有运行记录"}
            )
            continue
        if run.status == "failed":
            skipped.append(
                {
                    "job_id": job.id,
                    "name": job.name,
                    "reason": f"最近一次运行失败：{run.error or '未知原因'}",
                }
            )
            continue
        if run.status == "running":
            skipped.append(
                {"job_id": job.id, "name": job.name, "reason": "最近一次运行尚未结束"}
            )
            continue
        rows = store.alert_events_for_run(run.id)
        if not rows:
            if not store.has_run_series(run.id):
                skipped.append(
                    {
                        "job_id": job.id,
                        "name": job.name,
                        "reason": "最近一次运行的检测结果未同步进数据库",
                    }
                )
            continue
        for row in rows:
            events.append(
                AlertEvent(
                    job_id=job.id,
                    job_name=job.name,
                    metric_id=metric.id,
                    metric_name=metric.name,
                    series_id=row["series_id"],
                    group=row["group_name"],
                    level=row["level"],
                    level_index=int(row["level_index"]),
                    start_ts=row["start_ts"],
                    end_ts=row["end_ts"],
                    n_points=int(row["n_points"]),
                    max_score=float(row["max_score"]),
                    detector=row["detector"],
                    score_type=row["score_type"],
                    run_id=run.id,
                )
            )
    events.sort(key=lambda item: (item.start_ts, item.job_id), reverse=True)
    return events, skipped
