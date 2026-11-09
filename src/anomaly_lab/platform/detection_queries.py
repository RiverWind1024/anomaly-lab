"""检测记录的只读查询。

从 `store.py` 拆出来：这几个查询共用一段很长的 SELECT，且只读不写，
单独放一处便于核对字段清单。

⚠️ 字段清单只有这一份 —— 全量清单与分页共用，新增字段时不会漏掉另一条读路径。
"""

from __future__ import annotations

import sqlite3

#: 检测记录清单的公共 SELECT。
DETECTION_RECORDS_SELECT = (
    "SELECT rs.run_id, rs.series_id, rs.group_name, rs.n, rs.n_valid,"
    " rs.n_missing, rs.n_alerts, rs.n_p0, rs.sufficient, rs.detector,"
    " rs.metric_class, rs.fallback, rs.file, rs.content_hash,"
    " rs.start_ts, rs.end_ts, rs.decision_json,"
    " r.job_id, r.started_at, j.name AS job_name,"
    " m.id AS metric_id, m.name AS metric_name,"
    " s.id AS source_id, s.name AS source_name"
    " FROM run_series rs"
    " JOIN runs r ON r.id = rs.run_id"
    " JOIN jobs j ON j.id = r.job_id"
    " JOIN metrics m ON m.id = j.metric_id"
    " JOIN sources s ON s.id = m.source_id"
    " WHERE rs.file <> ''"
)


def detection_records(
    conn: sqlite3.Connection, job_id: int | None = None
) -> list[dict]:
    """**检测记录清单** —— 每次运行的每条序列，带上指标 / 数据源维度。

    ⚠️ **只返回真正跑出结果的记录**（`file` 非空）——
       数据不足的序列没有检测产物，进总体只会稀释指标。
    """
    sql = DETECTION_RECORDS_SELECT
    params: list[object] = []
    if job_id is not None:
        sql += " AND r.job_id = ?"
        params.append(int(job_id))
    sql += " ORDER BY rs.run_id, rs.series_id"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def detection_record_page(
    conn: sqlite3.Connection,
    *,
    job_id: int | None = None,
    only_alerts: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """检测记录分页 —— 新的在前，附带总条数。"""
    where = ""
    params: list[object] = []
    if job_id is not None:
        where += " AND r.job_id = ?"
        params.append(int(job_id))
    if only_alerts:
        where += " AND rs.n_alerts > 0"

    total = int(
        conn.execute(
            "SELECT COUNT(*) FROM (" + DETECTION_RECORDS_SELECT + where + ")",
            params,
        ).fetchone()[0]
    )
    rows = conn.execute(
        DETECTION_RECORDS_SELECT
        + where
        + " ORDER BY rs.run_id DESC, rs.series_id LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    ).fetchall()
    return [dict(row) for row in rows], total


def distinct_alert_events(
    conn: sqlite3.Connection,
) -> dict[tuple[int, str, str], int]:
    """(metric_id, series_id, 检出结果) → **去重后**的告警事件数。

    ⚠️ **去重键是 (level, start_ts, end_ts)** ——
       滚动窗口下同一个异常区间会被连续多次运行反复报出，
       那在用户看来是**一个**告警。检测记录数与告警事件数是两个量。
    ⚠️ **带检出结果** —— 报出告警的记录与什么都没报的记录必须分开算。
    """
    rows = conn.execute(
        "SELECT m.id AS metric_id, ae.series_id,"
        " CASE WHEN rs.n_alerts > 0 THEN 'alert' ELSE 'normal' END AS outcome,"
        " COUNT(DISTINCT ae.level || '|' || ae.start_ts || '|' || ae.end_ts) AS n"
        " FROM alert_events ae"
        " JOIN runs r ON r.id = ae.run_id"
        " JOIN jobs j ON j.id = r.job_id"
        " JOIN metrics m ON m.id = j.metric_id"
        " JOIN run_series rs ON rs.run_id = ae.run_id"
        "  AND rs.series_id = ae.series_id"
        " GROUP BY m.id, ae.series_id, outcome"
    ).fetchall()
    return {
        (int(row["metric_id"]), str(row["series_id"]), str(row["outcome"])): int(row["n"])
        for row in rows
    }


def synced_run_ids(conn: sqlite3.Connection) -> set[int]:
    """已经把检测结果同步进库的运行。"""
    rows = conn.execute("SELECT DISTINCT run_id FROM run_series").fetchall()
    return {int(row[0]) for row in rows}
