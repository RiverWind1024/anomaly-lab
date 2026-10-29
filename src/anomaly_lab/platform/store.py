"""平台元数据存储：SQLite 里的数据源 / 指标 / 任务 / 运行记录。

只保存配置与摘要；检测结果数组落在 run_dir 下的 npz，避免把大对象塞进数据库。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from anomaly_lab.platform.alerts import (
    band_multiplier,
    default_rules,
    highest_multiplier,
    parse_rules,
    rules_to_dicts,
)
from anomaly_lab.platform.detectors import DETECTOR_FACTORIES
from anomaly_lab.platform.models import Job, Metric, Run, Source
from anomaly_lab.platform.timeutil import freq_delta, to_iso, utcnow
from anomaly_lab.platform.validation import (
    validate_identifier,
    validate_interval_seconds,
    validate_missing_policy,
    validate_name,
    validate_query,
    validate_thresholds,
    validate_time_format,
    validate_timezone,
    validate_window_points,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'sqlite',
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
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
  window_points INTEGER NOT NULL,
  interval_seconds INTEGER NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  next_run_at TEXT,
  created_at TEXT NOT NULL
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
"""


class PlatformStore:
    """平台元数据的唯一入口；每次操作单独开连接，天然线程安全。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        # WAL：调度线程与 Web 请求会并发读写同一个库
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
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

    # ---------- 数据源 ----------

    def add_source(self, name: str, path: str, kind: str = "sqlite") -> Source:
        name = validate_name(name, "数据源名称")
        path = validate_name(path, "数据源路径")
        created_at = to_iso(utcnow())
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO sources (name, kind, path, created_at) VALUES (?, ?, ?, ?)",
                    (name, kind, path, created_at),
                )
                source_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"数据源名称已存在: {name}") from exc
        return self.get_source(source_id)

    def get_source(self, source_id: int) -> Source:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise ValueError(f"数据源不存在: {source_id}")
        return Source(**dict(row))

    def list_sources(self) -> list[Source]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        return [Source(**dict(row)) for row in rows]

    def find_source_by_name(self, name: str) -> Source | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
        return Source(**dict(row)) if row is not None else None

    # ---------- 指标 ----------

    def add_metric(
        self,
        *,
        source_id: int,
        name: str,
        query: str,
        time_column: str,
        value_column: str,
        group_column: str | None = None,
        time_format: str = "iso_utc",
        freq: str = "5min",
        source_timezone: str = "UTC",
        missing_policy: str = "drop",
    ) -> Metric:
        name = validate_name(name, "指标名称")
        query = validate_query(query)
        validate_identifier(time_column, "time_column")
        validate_identifier(value_column, "value_column")
        if group_column:
            validate_identifier(group_column, "group_column")
        validate_time_format(time_format)
        validate_missing_policy(missing_policy)
        validate_timezone(source_timezone)
        freq_delta(freq)  # 频率非法时立刻报错，而不是等到任务运行时才失败
        self.get_source(source_id)
        created_at = to_iso(utcnow())
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO metrics (source_id, name, query, time_column, value_column,"
                    " group_column, time_format, freq, source_timezone, missing_policy, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        source_id,
                        name,
                        query,
                        time_column,
                        value_column,
                        group_column or None,
                        time_format,
                        freq,
                        source_timezone,
                        missing_policy,
                        created_at,
                    ),
                )
                metric_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"该数据源下指标名称已存在: {name}") from exc
        return self.get_metric(metric_id)

    def get_metric(self, metric_id: int) -> Metric:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM metrics WHERE id = ?", (metric_id,)).fetchone()
        if row is None:
            raise ValueError(f"指标不存在: {metric_id}")
        return Metric(**dict(row))

    def list_metrics(self) -> list[Metric]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM metrics ORDER BY id").fetchall()
        return [Metric(**dict(row)) for row in rows]

    def find_metric_by_name(self, source_id: int, name: str) -> Metric | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM metrics WHERE source_id = ? AND name = ?", (source_id, name)
            ).fetchone()
        return Metric(**dict(row)) if row is not None else None

    # ---------- 检测任务 ----------

    def add_job(
        self,
        *,
        metric_id: int,
        name: str,
        detector: str,
        alert_threshold: float,
        critical_threshold: float,
        window_points: int,
        interval_seconds: int,
        enabled: bool = True,
        alert_rules: list[dict] | None = None,
    ) -> Job:
        name = validate_name(name, "任务名称")
        if detector not in DETECTOR_FACTORIES:
            raise ValueError(f"不支持的检测器: {detector}")
        window_points = validate_window_points(int(window_points))
        interval_seconds = validate_interval_seconds(int(interval_seconds))
        self.get_metric(metric_id)
        if alert_rules:
            # 规则表为准：阈值由规则推导（最低档/最高档的倍数）
            rules = parse_rules(alert_rules)
            alert_threshold = band_multiplier(rules)
            critical_threshold = highest_multiplier(rules) or alert_threshold
        else:
            validate_thresholds(float(alert_threshold), float(critical_threshold))
            rules = default_rules(float(alert_threshold), float(critical_threshold))
        rules_json = json.dumps(rules_to_dicts(rules), ensure_ascii=False)
        created_at = to_iso(utcnow())
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO jobs (metric_id, name, detector, alert_threshold,"
                    " critical_threshold, window_points, interval_seconds, enabled,"
                    " last_run_at, next_run_at, alert_rules, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                    (
                        metric_id,
                        name,
                        detector,
                        float(alert_threshold),
                        float(critical_threshold),
                        window_points,
                        interval_seconds,
                        1 if enabled else 0,
                        created_at,
                        rules_json,
                        created_at,
                    ),
                )
                job_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"任务名称已存在: {name}") from exc
        return self.get_job(job_id)

    def get_job(self, job_id: int) -> Job:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise ValueError(f"任务不存在: {job_id}")
        return self._to_job(row)

    def list_jobs(self) -> list[Job]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        return [self._to_job(row) for row in rows]

    def find_job_by_name(self, name: str) -> Job | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE name = ?", (name,)).fetchone()
        return self._to_job(row) if row is not None else None

    @staticmethod
    def _to_job(row: sqlite3.Row) -> Job:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["alert_rules"] = rules_to_dicts(parse_rules(data.get("alert_rules") or "[]"))
        return Job(**data)

    def set_job_enabled(self, job_id: int, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET enabled = ? WHERE id = ?", (1 if enabled else 0, job_id)
            )

    def set_job_next_run(self, job_id: int, next_run_at: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE jobs SET next_run_at = ? WHERE id = ?", (next_run_at, job_id))

    def update_job_schedule(
        self, job_id: int, last_run_at: str, next_run_at: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (last_run_at, next_run_at, job_id),
            )

    def due_jobs(self, now_iso: str) -> list[Job]:
        """到期的启用任务；next_run_at 为空视为立即到期。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE enabled = 1"
                " AND (next_run_at IS NULL OR next_run_at <= ?) ORDER BY id",
                (now_iso,),
            ).fetchall()
        return [self._to_job(row) for row in rows]

    def reconcile_missed(self, now_iso: str) -> int:
        """重启后把错过的窗口收敛到「现在」，保证只补跑一次。"""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET next_run_at = ? WHERE enabled = 1"
                " AND (next_run_at IS NULL OR next_run_at < ?)",
                (now_iso, now_iso),
            )
            return int(cursor.rowcount)

    # ---------- 运行记录 ----------

    def create_run(self, job_id: int) -> Run:
        started_at = to_iso(utcnow())
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (job_id, status, started_at) VALUES (?, 'running', ?)",
                (job_id, started_at),
            )
            run_id = int(cursor.lastrowid)
        return self.get_run(run_id)

    def finish_run(
        self,
        run_id: int,
        status: str,
        *,
        n_series: int = 0,
        n_alerts: int = 0,
        error: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, n_series = ?, n_alerts = ?,"
                " error = ? WHERE id = ?",
                (status, to_iso(utcnow()), int(n_series), int(n_alerts), error, run_id),
            )

    def get_run(self, run_id: int) -> Run:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"运行记录不存在: {run_id}")
        return Run(**dict(row))

    def list_runs(self, job_id: int, limit: int = 20) -> list[Run]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE job_id = ? ORDER BY id DESC LIMIT ?", (job_id, limit)
            ).fetchall()
        return [Run(**dict(row)) for row in rows]

    def latest_run(self, job_id: int) -> Run | None:
        runs = self.list_runs(job_id, limit=1)
        return runs[0] if runs else None
