"""平台元数据存储：SQLite 里的数据源 / 指标 / 任务 / 运行记录。

只保存配置与摘要；检测结果数组落在 run_dir 下的 npz，避免把大对象塞进数据库。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

from anomaly_lab.platform.alerts import (
    band_multiplier,
    band_multiplier_or_none,
    default_rules,
    highest_multiplier,
    parse_rules,
    rules_to_dicts,
)
from anomaly_lab.platform.detectors import AUTO_DETECTOR, DETECTOR_FACTORIES
from anomaly_lab.platform.feedback import FEEDBACK_KINDS, normalize_ts
from anomaly_lab.platform.models import Feedback, Job, Metric, Run, Source
from anomaly_lab.platform.timeutil import freq_delta, to_iso, utcnow
from anomaly_lab.platform.validation import (
    validate_http_config,
    validate_identifier,
    validate_interval_seconds,
    validate_kind,
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
"""


def _pick(fields: dict, key: str, current):
    """取「要改的值」：传了用传的，没传用当前的。

    ⚠️ **不能写成 `fields.get(key) or current`** —— 0 会被当成「没传」，
       于是「把窗口点改成 0」这种非法输入会被静默忽略。
    """
    value = fields.get(key)
    return current if value is None else value


REDACTED = "••••"
_SECRET_KEYS = ("token", "key", "password", "secret", "authorization")


def _is_secret(name: str) -> bool:
    """参数名是否含凭据关键词。

    ⚠️ 必须**子串**匹配 —— `api_key` / `access_token` / `apikey` /
       `X-API-Key` 这些复合名用精确相等会漏掉，明文就经 API 泄漏了。
    """
    low = name.lower()
    return any(key in low for key in _SECRET_KEYS)


def _redact_url(url: str) -> str:
    """把 URL 里的凭据参数替换成哨兵值。

    ⚠️ **文本级替换，不重新编码整个 query** ——
       重新编码会把 `{sql}` 变成 `%7Bsql%7D`，模板就废了；
       而且前端回写脱敏值时，用户改一次 host 就会把真实密钥覆盖成哨兵值。
    """
    head, sep, query = url.partition("?")
    if not sep:
        return url
    parts: list[str] = []
    changed = False
    for item in query.split("&"):
        name, eq, _ = item.partition("=")
        if eq and _is_secret(name):
            parts.append(f"{name}={REDACTED}")
            changed = True
        else:
            parts.append(item)
    return f"{head}?{'&'.join(parts)}" if changed else url


def _merge_url(old_url: str, new_url: str) -> str:
    """把新 url 里的哨兵值换回旧 url 里的真值（参数级，不重新编码）。

    ⚠️ 必须**参数级**替换 —— 整串比较只认得「完全一样」，
       用户改个 host 就会把真实密钥一起丢掉。
    """
    _, _, old_q = old_url.partition("?")
    new_head, _, new_q = new_url.partition("?")
    if not old_q or not new_q:
        return new_url
    old_values: dict[str, str] = {}
    for item in old_q.split("&"):
        name, eq, value = item.partition("=")
        if eq:
            old_values.setdefault(name, value)
    merged = []
    for item in new_q.split("&"):
        name, eq, value = item.partition("=")
        if eq and value == REDACTED and name in old_values:
            merged.append(f"{name}={old_values[name]}")
        else:
            merged.append(item)
    return f"{new_head}?{'&'.join(merged)}"


def _redact_config(config: dict) -> dict:
    """把 config 里的凭据替换成哨兵值。

    ⚠️ 脱敏在 store 层做 —— 前端拿不到原值，
       「保留原值」这类合并规则只能后端实现。
    """
    out = dict(config)
    headers = out.get("headers")
    if isinstance(headers, dict):
        out["headers"] = {
            key: (
                f"{str(value).split(' ', 1)[0]} {REDACTED}"
                if " " in str(value)
                else REDACTED
            )
            if _is_secret(str(key))
            else value
            for key, value in headers.items()
        }
    body = out.get("body")
    if isinstance(body, dict):
        out["body"] = {
            key: (REDACTED if _is_secret(str(key)) else value)
            for key, value in body.items()
        }
    url = out.get("url")
    if isinstance(url, str):
        out["url"] = _redact_url(url)
    return out


def _merge_config(old: dict, new: dict) -> dict:
    """合并配置：**整体替换** + 哨兵值还原。

    ⚠️ 前端必须提交**完整**的 config —— 没传的顶层键会被删掉。
       新值里凡是等于旧值脱敏形式的，沿用旧真值
       （前端拿不到原值，只能把脱敏值原样传回来）。
    """
    redacted_old = _redact_config(old)
    merged = dict(new)
    for key in ("headers", "body"):
        new_map = new.get(key)
        old_map = old.get(key)
        if not isinstance(new_map, dict) or not isinstance(old_map, dict):
            continue
        old_redacted = redacted_old.get(key, {})
        combined: dict[str, object] = {}
        for name, value in new_map.items():
            if name in old_map and value == old_redacted.get(name):
                combined[name] = old_map[name]  # 脱敏值 → 还原真值
            else:
                combined[name] = value
        merged[key] = combined
    url = new.get("url")
    old_url = old.get("url")
    if isinstance(url, str) and isinstance(old_url, str) and url != old_url:
        merged["url"] = _merge_url(old_url, url)
    return merged


def _dump_config(config: dict) -> str:
    """config → JSON 文本。不可序列化时抛 ValueError（不是 TypeError）。

    ⚠️ store 层的调用方按 ValueError 捕获 —— TypeError 会漏网，
       变成 500 而不是 400。
    """
    try:
        return json.dumps(config, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"数据源配置无法序列化: {exc}") from exc


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
        source_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(sources)")
        }
        if "config" not in source_columns:
            conn.execute(
                "ALTER TABLE sources ADD COLUMN config TEXT NOT NULL DEFAULT '{}'"
            )

    # ---------- 数据源 ----------

    def add_source(
        self,
        name: str,
        path: str,
        kind: str = "sqlite",
        config: dict | None = None,
    ) -> Source:
        """新增数据源。

        ⚠️ `kind` 决定必填项 —— sqlite 要 path，http 要 url（在 config 里）。
           跨类型切换（update_source 改 kind）需要**同时**提供目标类型的必填项。
        """
        name = validate_name(name, "数据源名称")
        kind = validate_kind(kind)
        config = config or {}
        if kind == "sqlite":
            path = validate_name(path, "数据源路径")
            config = {}  # sqlite 不用 config —— 归一为空，语义才干净
        else:  # http —— 路径对它没有意义，参数都在 config 里
            path = path.strip()
            validate_http_config(config)
        created_at = to_iso(utcnow())
        try:
            with self._conn() as conn:
                cursor = conn.execute(
                    "INSERT INTO sources (name, kind, path, created_at, config) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, kind, path, created_at, _dump_config(config)),
                )
                source_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"数据源名称已存在: {name}") from exc
        return self.get_source(source_id)

    @staticmethod
    def _to_source(row: sqlite3.Row) -> Source:
        """行 → Source。config 列是 JSON 文本，这里解成 dict。"""
        data = dict(row)
        raw = data.pop("config", None) or "{}"
        data["config"] = json.loads(raw) if raw else {}
        return Source(**data)

    def get_source(self, source_id: int) -> Source:
        """取数据源（**已脱敏**）—— 给 API 用。"""
        source = self.get_source_raw(source_id)
        return replace(source, config=_redact_config(source.config))

    def get_source_raw(self, source_id: int) -> Source:
        """取数据源（**未脱敏**）—— 给内部逻辑用（取数、合并配置）。"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise ValueError(f"数据源不存在: {source_id}")
        return self._to_source(row)

    def update_source(
        self,
        source_id: int,
        *,
        name: str | None = None,
        path: str | None = None,
        kind: str | None = None,
        config: dict | None = None,
    ) -> Source:
        """改数据源。只传要改的字段，其余保持原样。

        ⚠️ 已经跑过的运行记录不受影响 —— run 的结果早已落盘。
           改动只在**下一次**运行任务时生效。
        ⚠️ `config=None` 表示「不改」；传 `{}` 表示「清空」。
           传了 config 就是**整体替换** —— 前端必须提交完整配置，
           没传的顶层键会被删掉。
        ⚠️ 跨类型切换（改 kind）需要**同时**提供目标类型的必填项。
        """
        current = self.get_source_raw(source_id)  # ⚠️ 未脱敏 —— 否则密钥会被冲掉
        new_name = validate_name(name if name is not None else current.name, "数据源名称")
        new_kind = validate_kind(kind if kind is not None else current.kind)
        new_path = path if path is not None else current.path
        switched = new_kind != current.kind
        if new_kind == "sqlite":
            new_path = validate_name(new_path, "数据源路径")
            new_config: dict = {}  # sqlite 不用 config
        else:  # http —— 路径对它没有意义，参数都在 config 里
            new_path = new_path.strip()
            new_config = (
                current.config if config is None else _merge_config(current.config, config)
            )
            if switched and not new_config.get("url"):
                # ⚠️ 跨类型切换必须**同时**提供目标类型的必填项 ——
                #    否则切过去就是一个立刻不可用的源
                raise ValueError("HTTP 数据源必须配置 url")
            validate_http_config(new_config)
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE sources SET name = ?, path = ?, kind = ?, config = ? WHERE id = ?",
                    (
                        new_name,
                        new_path,
                        new_kind,
                        _dump_config(new_config),
                        source_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"数据源名称已存在: {new_name}") from exc
        return self.get_source(source_id)

    def list_sources(self) -> list[Source]:
        """列数据源（**已脱敏**）—— `catalog` 端点走这里。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        sources = [self._to_source(row) for row in rows]
        return [replace(s, config=_redact_config(s.config)) for s in sources]

    def find_source_by_name(self, name: str) -> Source | None:
        """按名字找（**已脱敏**）。"""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        source = self._to_source(row)
        return replace(source, config=_redact_config(source.config))

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

    def update_metric(self, metric_id: int, **fields) -> Metric:
        """改指标。只传要改的字段，其余保持原样。

        校验复用 add_metric 的那套（列名 / 时间格式 / 时区 / 频率）——
        非法配置要在**保存时**被拦下，而不是等任务运行时才失败。

        ⚠️ 已经跑过的运行记录不受影响（结果早已落盘），
           改动只在**下一次**运行任务时生效。
        """
        current = self.get_metric(metric_id)
        name = validate_name(fields.get("name") or current.name, "指标名称")
        query = validate_query(fields.get("query") or current.query)
        time_column = fields.get("time_column") or current.time_column
        value_column = fields.get("value_column") or current.value_column
        group_column = fields.get("group_column", current.group_column)
        time_format = fields.get("time_format") or current.time_format
        freq = fields.get("freq") or current.freq
        source_timezone = fields.get("source_timezone") or current.source_timezone
        missing_policy = fields.get("missing_policy") or current.missing_policy
        validate_identifier(time_column, "time_column")
        validate_identifier(value_column, "value_column")
        if group_column:
            validate_identifier(group_column, "group_column")
        validate_time_format(time_format)
        validate_missing_policy(missing_policy)
        validate_timezone(source_timezone)
        freq_delta(freq)
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE metrics SET name = ?, query = ?, time_column = ?, value_column = ?,"
                    " group_column = ?, time_format = ?, freq = ?, source_timezone = ?,"
                    " missing_policy = ? WHERE id = ?",
                    (
                        name,
                        query,
                        time_column,
                        value_column,
                        group_column or None,
                        time_format,
                        freq,
                        source_timezone,
                        missing_policy,
                        metric_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该数据源下指标名称已存在") from exc
        return self.get_metric(metric_id)

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
        if detector != AUTO_DETECTOR and detector not in DETECTOR_FACTORIES:
            raise ValueError(f"不支持的检测器: {detector}")
        window_points = validate_window_points(int(window_points))
        interval_seconds = validate_interval_seconds(int(interval_seconds))
        self.get_metric(metric_id)
        if alert_rules:
            # 规则表为准：阈值由规则推导（最低档/最高档的倍数）
            # 没有倍数条件（规则全是绝对值条件）→ 用调用方传入的兜底值
            rules = parse_rules(alert_rules)
            derived = band_multiplier_or_none(rules)
            alert_threshold = derived if derived is not None else float(alert_threshold)
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

    def update_job_config(self, job_id: int, **fields) -> Job:
        """改任务配置。只传要改的字段，其余保持原样。

        ⚠️ **阈值与规则表必须一致**：
           改了阈值就**重算规则表**（以阈值为准），
           否则规则表里还是旧的倍数条件，两边对不上。
           反过来，改其它字段时**不动**规则表 ——
           否则用户通过「应用建议」调好的规则会被冲掉。

        ⚠️ 已经跑过的运行记录不受影响（结果早已落盘），
           改动只在**下一次**运行任务时生效。
        """
        current = self.get_job(job_id)
        name = validate_name(_pick(fields, "name", current.name), "任务名称")
        detector = _pick(fields, "detector", current.detector)
        if detector != AUTO_DETECTOR and detector not in DETECTOR_FACTORIES:
            raise ValueError(f"不支持的检测器: {detector}")
        metric_id = int(_pick(fields, "metric_id", current.metric_id))
        self.get_metric(metric_id)
        window_points = validate_window_points(
            int(_pick(fields, "window_points", current.window_points))
        )
        interval_seconds = validate_interval_seconds(
            int(_pick(fields, "interval_seconds", current.interval_seconds))
        )
        enabled = fields.get("enabled", current.enabled)
        alert = float(_pick(fields, "alert_threshold", current.alert_threshold))
        if fields.get("critical_threshold") is not None:
            critical = float(fields["critical_threshold"])
        elif alert != current.alert_threshold and alert >= current.critical_threshold:
            # 只改了告警阈值、没改严重阈值 —— 严重阈值跟着抬。
            # 否则会出现「严重阈值 ≤ 告警阈值」这种非法组合，
            # 用户改一个数却被要求改两个。
            critical = alert * 1.5
        else:
            critical = current.critical_threshold
        validate_thresholds(alert, critical)

        # 阈值变了才重算规则表
        rules_json = None
        if alert != current.alert_threshold or critical != current.critical_threshold:
            rules_json = json.dumps(
                rules_to_dicts(default_rules(alert, critical)), ensure_ascii=False
            )

        try:
            with self._conn() as conn:
                if rules_json is None:
                    conn.execute(
                        "UPDATE jobs SET name = ?, metric_id = ?, detector = ?,"
                        " alert_threshold = ?, critical_threshold = ?, window_points = ?,"
                        " interval_seconds = ?, enabled = ? WHERE id = ?",
                        (
                            name,
                            metric_id,
                            detector,
                            alert,
                            critical,
                            window_points,
                            interval_seconds,
                            1 if enabled else 0,
                            job_id,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET name = ?, metric_id = ?, detector = ?,"
                        " alert_threshold = ?, critical_threshold = ?, window_points = ?,"
                        " interval_seconds = ?, enabled = ?, alert_rules = ? WHERE id = ?",
                        (
                            name,
                            metric_id,
                            detector,
                            alert,
                            critical,
                            window_points,
                            interval_seconds,
                            1 if enabled else 0,
                            rules_json,
                            job_id,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"任务名称已存在: {name}") from exc
        return self.get_job(job_id)

    def set_job_enabled(self, job_id: int, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET enabled = ? WHERE id = ?", (1 if enabled else 0, job_id)
            )

    def set_job_detector(self, job_id: int, detector: str) -> Job:
        """改任务的检测算法（用户在多算法对比后选定其一）。"""
        if detector != AUTO_DETECTOR and detector not in DETECTOR_FACTORIES:
            raise ValueError(f"不支持的检测器: {detector}")
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET detector = ? WHERE id = ?", (detector, job_id)
            )
        return self.get_job(job_id)

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

    def run_stats(self) -> dict[str, int]:
        """全部任务的运行统计（按状态计数）。

        ⚠️ 一次查询拿完 —— 概览页要的是**全局**统计，
           逐个任务查 list_runs 是 N+1 次查询。
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM runs GROUP BY status"
            ).fetchall()
        return {str(status): int(count) for status, count in rows}

    def latest_runs(self) -> dict[int, Run]:
        """每个任务最近一次运行（job_id → Run）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT r.* FROM runs r JOIN ("
                " SELECT job_id, MAX(id) AS max_id FROM runs GROUP BY job_id"
                ") m ON r.id = m.max_id"
            ).fetchall()
        return {int(row["job_id"]): Run(**dict(row)) for row in rows}

    def feedback_stats(self) -> dict[str, int]:
        """人工反馈统计（按 kind 计数）。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT kind, COUNT(*) FROM feedback GROUP BY kind"
            ).fetchall()
        return {str(kind): int(count) for kind, count in rows}

    # ---------- 人工反馈 ----------

    def add_feedback(
        self,
        *,
        job_id: int,
        series_id: str,
        start_ts: str,
        end_ts: str,
        kind: str,
        note: str = "",
        run_id: int | None = None,
    ) -> Feedback:
        if kind not in FEEDBACK_KINDS:
            raise ValueError(
                f"不支持的反馈类型: {kind!r}（可选 {sorted(FEEDBACK_KINDS)}）"
            )
        if not series_id.strip():
            raise ValueError("反馈必须指明序列")
        start_ts = normalize_ts(start_ts)
        end_ts = normalize_ts(end_ts)
        if start_ts >= end_ts:
            raise ValueError("反馈的结束时间必须晚于开始时间")
        self.get_job(job_id)
        created_at = to_iso(utcnow())
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO feedback (job_id, run_id, series_id, start_ts, end_ts,"
                " kind, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    run_id,
                    series_id,
                    start_ts,
                    end_ts,
                    kind,
                    note,
                    created_at,
                ),
            )
            feedback_id = int(cursor.lastrowid)
        return self.get_feedback(feedback_id)

    def get_feedback(self, feedback_id: int) -> Feedback:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"反馈不存在: {feedback_id}")
        return Feedback(**dict(row))

    def list_feedback(self, job_id: int) -> list[Feedback]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE job_id = ? ORDER BY id", (job_id,)
            ).fetchall()
        return [Feedback(**dict(row)) for row in rows]

    def update_job_rules(self, job_id: int, rules: list[dict]) -> Job:
        """替换任务的规则表（应用反馈建议时用）。"""
        parsed = parse_rules(rules)
        alert = band_multiplier(parsed)
        critical = highest_multiplier(parsed) or alert
        rules_json = json.dumps(rules_to_dicts(parsed), ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET alert_rules = ?, alert_threshold = ?,"
                " critical_threshold = ? WHERE id = ?",
                (rules_json, alert, critical, job_id),
            )
        return self.get_job(job_id)

    # ---------- 删除 ----------

    def delete_job(self, job_id: int) -> dict:
        """删一个任务（连带 runs / feedback），返回删除统计。

        ⚠️ 返回值里的 `run_ids` 是**内部用**的 —— 路由层要据此删 run 目录
        文件（数据库外键管不到文件系统）。路由层构造响应前要把它 pop 掉。
        """
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError(f"任务不存在: {job_id}")
            stats = self._cascade_stats(conn, [job_id])
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        stats["jobs"] = 1
        return stats

    def delete_metric(self, metric_id: int) -> dict:
        """删一个指标（连带它下面的任务、运行、反馈）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM metrics WHERE id=?", (metric_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"指标不存在: {metric_id}")
            job_ids = [
                item["id"]
                for item in conn.execute(
                    "SELECT id FROM jobs WHERE metric_id=?", (metric_id,)
                )
            ]
            stats = self._cascade_stats(conn, job_ids)
            conn.execute("DELETE FROM metrics WHERE id=?", (metric_id,))
        stats["metrics"] = 1
        return stats

    def delete_source(self, source_id: int) -> dict:
        """删一个数据源（连带它下面的指标、任务、运行、反馈）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM sources WHERE id=?", (source_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"数据源不存在: {source_id}")
            metric_ids = [
                item["id"]
                for item in conn.execute(
                    "SELECT id FROM metrics WHERE source_id=?", (source_id,)
                )
            ]
            job_ids: list[int] = []
            if metric_ids:
                placeholders = ",".join("?" * len(metric_ids))
                job_ids = [
                    item["id"]
                    for item in conn.execute(
                        f"SELECT id FROM jobs WHERE metric_id IN ({placeholders})",
                        metric_ids,
                    )
                ]
            stats = self._cascade_stats(conn, job_ids)
            conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        stats["metrics"] = len(metric_ids)
        stats["sources"] = 1
        return stats

    @staticmethod
    def _cascade_stats(conn: sqlite3.Connection, job_ids: list[int]) -> dict:
        """统计要连带删掉多少任务 / 运行 / 反馈，并收集 run_id。

        ⚠️ 必须在删除**之前**统计 —— `runs` 表有 `ON DELETE CASCADE`，
        删完就查不到了。
        """
        if not job_ids:
            return {"jobs": 0, "runs": 0, "feedback": 0, "run_ids": []}
        placeholders = ",".join("?" * len(job_ids))
        run_ids = [
            item["id"]
            for item in conn.execute(
                f"SELECT id FROM runs WHERE job_id IN ({placeholders})", job_ids
            )
        ]
        feedback = conn.execute(
            f"SELECT COUNT(*) AS c FROM feedback WHERE job_id IN ({placeholders})",
            job_ids,
        ).fetchone()["c"]
        return {
            "jobs": len(job_ids),
            "runs": len(run_ids),
            "feedback": feedback,
            "run_ids": run_ids,
        }
