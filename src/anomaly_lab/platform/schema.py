"""平台库的建表语句与轻量迁移。

单独成文件：`store.py` 里 SQL 占了上百行，混在业务方法中间很难读。
"""

from __future__ import annotations

import sqlite3

from anomaly_lab.platform.timeutil import freq_delta

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'sqlite',
  path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  query TEXT NOT NULL,
  time_column TEXT NOT NULL,
  value_column TEXT NOT NULL,
  group_column TEXT,
  time_format TEXT NOT NULL DEFAULT 'iso',
  -- ⚠️ 已弃用：数据粒度由 SQL 决定，平台从时间戳推断。
  --    保留列只为兼容老库，代码不再读写（新库写入默认值）。
  freq TEXT NOT NULL DEFAULT '5min',
  created_at TEXT NOT NULL,
  UNIQUE(source_id, name)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  metric_id INTEGER NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
  name TEXT NOT NULL UNIQUE,
  detector TEXT NOT NULL,
  alert_threshold REAL NOT NULL,
  critical_threshold REAL NOT NULL,
  -- ⚠️ 已弃用：窗口改为时间（window_seconds）。保留列只为兼容老库，
  --    新任务写 0。
  window_points INTEGER NOT NULL DEFAULT 0,
  -- 每次取最近多少秒的数据；SQL 返回多少点就检测多少点。
  window_seconds INTEGER NOT NULL DEFAULT 0,
  interval_seconds INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  next_run_at TEXT,
  created_at TEXT NOT NULL,
  alert_direction TEXT NOT NULL DEFAULT 'both',
  detect_points INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  n_series INTEGER NOT NULL DEFAULT 0,
  n_alerts INTEGER NOT NULL DEFAULT 0,
  error TEXT
);
-- 按任务查运行记录（列表 / 最近一次）—— 没有它会退化成全表扫 + 排序。
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id, id DESC);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  run_id INTEGER,
  series_id TEXT NOT NULL,
  start_ts TEXT NOT NULL,
  end_ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
-- 清理状态：单行表（id 恒为 1），记「上次清理是什么时候、删了多少」。
-- ⚠️ 放库里而不是文件里 —— 「上次清理时间」要跨进程可见
--    （Web 请求看到的要和调度器写的是同一份状态）。
CREATE TABLE IF NOT EXISTS retention_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  pruned_at TEXT,
  deleted_runs INTEGER NOT NULL DEFAULT 0,
  freed_bytes INTEGER NOT NULL DEFAULT 0
);
-- 每次运行的每条序列 —— 检测记录的「清单」层。
-- ⚠️ 以前这些只躺在 index.json 里，查询「有哪些检测记录」得扫整个
--    产物目录（实测 8700 多个目录 = 0.47s，且随运行数线性涨）。
--    落库之后那是一条 SQL。
CREATE TABLE IF NOT EXISTS run_series (
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  series_id TEXT NOT NULL,
  group_name TEXT,
  n INTEGER NOT NULL DEFAULT 0,
  n_valid INTEGER NOT NULL DEFAULT 0,
  n_missing INTEGER NOT NULL DEFAULT 0,
  n_alerts INTEGER NOT NULL DEFAULT 0,
  n_p0 INTEGER NOT NULL DEFAULT 0,
  sufficient INTEGER NOT NULL DEFAULT 1,
  detector TEXT NOT NULL DEFAULT '',
  metric_class TEXT NOT NULL DEFAULT '',
  fallback INTEGER NOT NULL DEFAULT 0,
  file TEXT NOT NULL DEFAULT '',
  -- 内容指纹：同一份数据被反复检测时用来识别「这是同一次检测」。
  content_hash TEXT NOT NULL DEFAULT '',
  -- 这次检测覆盖的时间范围（naive ISO）。
  -- ⚠️ 落库是为了**不读 npz 就能判断「哪条标注落在哪次检测里」** ——
  --    标注按序列存，一条标注要复用给所有覆盖它的检测记录。
  start_ts TEXT NOT NULL DEFAULT '',
  end_ts TEXT NOT NULL DEFAULT '',
  -- 这次检测的完整决策链（六段，JSON）。老库 / 老数据为空串。
  decision_json TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (run_id, series_id)
);
CREATE INDEX IF NOT EXISTS idx_run_series_content ON run_series(content_hash);
-- 告警区间 —— 检测记录的「明细」层。
-- ⚠️ **每次运行报出的区间都记一行，不预先去重** ——
--    「同一个异常被报过几次」本身就是事实（滚动窗口下会重复报），
--    要不要合并由查询层决定。
CREATE TABLE IF NOT EXISTS alert_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  series_id TEXT NOT NULL,
  group_name TEXT,
  level TEXT NOT NULL,
  level_index INTEGER NOT NULL,
  start_ts TEXT NOT NULL,
  end_ts TEXT NOT NULL,
  n_points INTEGER NOT NULL DEFAULT 0,
  max_score REAL NOT NULL DEFAULT 0,
  detector TEXT NOT NULL DEFAULT '',
  score_type TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_alert_events_run ON alert_events(run_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_span ON alert_events(series_id, start_ts);
-- 归档数据集：手动收藏的检测记录容器。
CREATE TABLE IF NOT EXISTS archive_sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
-- 归档记录：检测记录的**独立副本**（含 npz 产物），
-- ⚠️ 不复用 run_series —— 原记录可能被删除或被保留策略清理。
CREATE TABLE IF NOT EXISTS archive_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  archive_set_id INTEGER NOT NULL REFERENCES archive_sets(id) ON DELETE CASCADE,
  run_id INTEGER NOT NULL,
  series_id TEXT NOT NULL,
  group_name TEXT,
  job_name TEXT NOT NULL DEFAULT '',
  metric_name TEXT NOT NULL DEFAULT '',
  detector TEXT NOT NULL DEFAULT '',
  n INTEGER NOT NULL DEFAULT 0,
  n_valid INTEGER NOT NULL DEFAULT 0,
  n_alerts INTEGER NOT NULL DEFAULT 0,
  n_p0 INTEGER NOT NULL DEFAULT 0,
  start_ts TEXT NOT NULL DEFAULT '',
  end_ts TEXT NOT NULL DEFAULT '',
  -- 用户填写 / 归档时补充的原因
  description TEXT NOT NULL DEFAULT '',
  -- 归档目录里的 npz 相对路径（相对 data_root）
  file TEXT NOT NULL DEFAULT '',
  decision_json TEXT NOT NULL DEFAULT '',
  content_hash TEXT NOT NULL DEFAULT '',
  archived_at TEXT NOT NULL,
  UNIQUE(archive_set_id, run_id, series_id)
);
CREATE INDEX IF NOT EXISTS idx_archive_records_set
  ON archive_records(archive_set_id, id DESC);
"""


def migrate(conn: sqlite3.Connection) -> None:
    """给老库补上新列，避免升级后配置丢失。"""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(metrics)")}
    if "source_timezone" not in columns:
        conn.execute(
            "ALTER TABLE metrics ADD COLUMN source_timezone TEXT NOT NULL DEFAULT 'UTC'"
        )
    if "missing_policy" not in columns:
        conn.execute(
            "ALTER TABLE metrics ADD COLUMN missing_policy TEXT NOT NULL DEFAULT 'drop'"
        )
    job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "alert_rules" not in job_columns:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN alert_rules TEXT NOT NULL DEFAULT '[]'"
        )
    if "alert_direction" not in job_columns:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN alert_direction TEXT NOT NULL DEFAULT 'both'"
        )
    if "detect_points" not in job_columns:
        # 0 = 检测整个窗口 —— 老任务的既有行为不变。
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN detect_points INTEGER NOT NULL DEFAULT 0"
        )
    if "window_seconds" not in job_columns:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN window_seconds INTEGER NOT NULL DEFAULT 0"
        )
        # ⚠️ 旧任务：把「窗口点数 × 指标频率」换算成时间窗口，
        #    保证升级后告警范围不变（不是让用户重填）。
        rows = conn.execute(
            "SELECT j.id, j.window_points, m.freq FROM jobs j"
            " JOIN metrics m ON m.id = j.metric_id"
        ).fetchall()
        for row in rows:
            points = int(row["window_points"] or 0)
            seconds = 300 * points
            try:
                seconds = int(freq_delta(str(row["freq"])).total_seconds()) * points
            except ValueError:
                # 频率列是脏数据时按 5min 兜底，至少不要让窗口变成 0
                pass
            conn.execute(
                "UPDATE jobs SET window_seconds = ? WHERE id = ?",
                (max(60, seconds), row["id"]),
            )
    source_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sources)")
    }
    if "config" not in source_columns:
        conn.execute(
            "ALTER TABLE sources ADD COLUMN config TEXT NOT NULL DEFAULT '{}'"
        )
    # 检测记录的时间范围 / 决策链是后加的列 —— 老库补上
    # （时间范围空值由 sync-detections 回填，决策链老数据就是没有）。
    run_series_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(run_series)")
    }
    if run_series_columns:
        for column in ("start_ts", "end_ts", "decision_json"):
            if column not in run_series_columns:
                conn.execute(
                    f"ALTER TABLE run_series ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
    # 归档记录的「说明」是后加的列
    archive_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(archive_records)")
    }
    if archive_columns and "description" not in archive_columns:
        conn.execute(
            "ALTER TABLE archive_records ADD COLUMN description TEXT NOT NULL DEFAULT ''"
        )
