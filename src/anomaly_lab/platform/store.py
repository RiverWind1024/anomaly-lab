"""平台元数据存储：SQLite 里的数据源 / 指标 / 任务 / 运行记录。

只保存配置与摘要；检测结果数组落在 run_dir 下的 npz，避免把大对象塞进数据库。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
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
from anomaly_lab.platform.detectors import (
    AUTO_DETECTOR,
    DETECTOR_FACTORIES,
    create_detector,
    detector_default_threshold,
    detector_score_family,
)
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
"""


def _pick(fields: dict, key: str, current):
    """取「要改的值」：传了用传的，没传用当前的。

    ⚠️ **不能写成 `fields.get(key) or current`** —— 0 会被当成「没传」，
       于是「把窗口点改成 0」这种非法输入会被静默忽略。
    """
    value = fields.get(key)
    return current if value is None else value


def _absolute_rules_only(raw: object) -> list:
    """从规则表里挑出**绝对值条件**（倍数条件会被重算，绝对值条件保留）。

    ⚠️ 换算法、改阈值都会重算倍数 —— 那是必须的（量纲变了）。
       但用户配的「值 > 50 记 P0」是**绝对值**的，与量纲无关 ——
       不该跟着被冲掉。
    """
    if not raw:
        return []
    try:
        rules = parse_rules(raw)
    except (ValueError, TypeError):
        # ⚠️ 旧数据里的规则表读不出来（格式变了）—— 不该让整个保存失败，
        #    绝对值条件拿不到就算了，倍数照常重算。
        return []
    return [rule for rule in rules if rule.is_absolute]


REDACTED = "••••"
_SECRET_KEYS = ("token", "key", "password", "secret", "authorization")


def _is_secret(name: str) -> bool:
    """参数名是否含凭据关键词。

    ⚠️ 必须**子串**匹配 —— `api_key` / `access_token` / `apikey` /
       `X-API-Key` 这些复合名用精确相等会漏掉，明文就经 API 泄漏了。
    """
    low = name.lower()
    return any(key in low for key in _SECRET_KEYS)


def _split_netloc(head: str) -> tuple[str, str, str] | None:
    """URL 的 head → `(scheme 前缀, netloc, 剩余路径)`。

    ⚠️ 没有 `//` 时返回 None —— 那不是标准 URL 形态，不处理 userinfo。
    """
    scheme, sep, rest = head.partition("//")
    if not sep:
        return None
    netloc, slash, tail = rest.partition("/")
    return f"{scheme}//", netloc, f"/{tail}" if slash else ""


def _split_userinfo(netloc: str) -> tuple[str, str] | None:
    """netloc → `(userinfo, host)`；没有 userinfo 时返回 None。

    ⚠️ 密码里可能含 `@` —— 按**最后一个** `@` 切，host 才切得对。
    """
    if "@" not in netloc:
        return None
    userinfo, _, host = netloc.rpartition("@")
    return userinfo, host


def _redact_userinfo(head: str) -> str:
    """把 netloc 里的 `user:pass@` 换成哨兵值。

    ⚠️ 只看 netloc —— 路径里的 `@` 不是凭据。
    """
    parts = _split_netloc(head)
    if parts is None:
        return head
    prefix, netloc, tail = parts
    split = _split_userinfo(netloc)
    if split is None:
        return head
    return f"{prefix}{REDACTED}@{split[1]}{tail}"


def _restore_userinfo(old_head: str, new_head: str) -> str:
    """把脱敏后的 `••••@host` 换回旧 URL 里的真 userinfo。

    ⚠️ 前端拿不到真值 —— 它原样回传 `••••@host`，
       直接存下去远端就收不到凭据了。
    """
    old_parts = _split_netloc(old_head)
    new_parts = _split_netloc(new_head)
    if old_parts is None or new_parts is None:
        return new_head
    old_split = _split_userinfo(old_parts[1])
    new_split = _split_userinfo(new_parts[1])
    if old_split is None or new_split is None:
        return new_head
    new_userinfo, new_host = new_split
    if new_userinfo != REDACTED:
        return new_head
    return f"{new_parts[0]}{old_split[0]}@{new_host}{new_parts[2]}"


def _redact_url(url: str) -> str:
    """把 URL 里的凭据替换成哨兵值。

    ⚠️ **文本级替换，不重新编码整个 query** ——
       重新编码会把 `{sql}` 变成 `%7Bsql%7D`，模板就废了；
       而且前端回写脱敏值时，用户改一次 host 就会把真实密钥覆盖成哨兵值。
    ⚠️ netloc 里的 userinfo（`user:pass@host`）也要脱 ——
       密码里可能含 `@`，按最后一个 `@` 切才切得对 host。
    """
    head, sep, query = url.partition("?")
    head = _redact_userinfo(head)
    if not sep:
        return head
    parts: list[str] = []
    for item in query.split("&"):
        name, eq, _ = item.partition("=")
        if eq and _is_secret(name):
            parts.append(f"{name}={REDACTED}")
        else:
            parts.append(item)
    return f"{head}?{'&'.join(parts)}"


def _merge_url(old_url: str, new_url: str) -> str:
    """把新 url 里的哨兵值换回旧 url 里的真值（参数级 + userinfo，不重新编码）。

    ⚠️ 必须**参数级**替换 —— 整串比较只认得「完全一样」，
       用户改个 host 就会把真实密钥一起丢掉。
    """
    old_head, _, old_q = old_url.partition("?")
    new_head, _, new_q = new_url.partition("?")
    new_head = _restore_userinfo(old_head, new_head)
    old_values: dict[str, str] = {}
    for item in old_q.split("&"):
        name, eq, value = item.partition("=")
        if eq:
            old_values.setdefault(name, value)
    merged = []
    for item in new_q.split("&"):
        name, eq, value = item.partition("=")
        if not eq:
            merged.append(item)
            continue
        if value == REDACTED:
            if name not in old_values:
                # ⚠️ 认不出对应旧 key —— 说明用户把凭据**改名**了。
                #    哨兵值存下去远端就收到字面量 `••••`，源直接坏掉。
                raise ValueError(
                    f"url 参数 {name!r} 的值是脱敏值，但旧配置里没有同名参数"
                    "（改名了？脱敏值不能作为新凭据，请重新输入）"
                )
            merged.append(f"{name}={old_values[name]}")
        else:
            merged.append(item)
    return f"{new_head}?{'&'.join(merged)}" if new_q else new_head


def _redact_value(value):
    """递归脱敏：嵌套 dict / list 里的凭据键也要脱。

    ⚠️ 凭据常藏在嵌套结构里（`{"auth":{"password":...}}`）——
       只脱顶层等于没脱。
    """
    if isinstance(value, dict):
        return {
            key: (REDACTED if _is_secret(str(key)) else _redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _redact_header_value(value):
    """header 的值**一律脱敏** —— 不能靠参数名判断。

    ⚠️ `Cookie` / `X-Session-Id` / `Proxy-Authorization` 这些根本猜不出
       名字里有凭据，靠名字判断就会明文泄漏。
    """
    if isinstance(value, dict):
        return {key: _redact_header_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_header_value(item) for item in value]
    text = str(value)
    return f"{text.split(' ', 1)[0]} {REDACTED}" if " " in text else REDACTED


def _looks_redacted(value) -> bool:
    """值是不是「脱敏哨兵」形态（`••••` 或 `前缀 ••••`）。"""
    if isinstance(value, str):
        return value == REDACTED or value.endswith(f" {REDACTED}")
    if isinstance(value, dict):
        return any(_looks_redacted(item) for item in value.values())
    if isinstance(value, list):
        return any(_looks_redacted(item) for item in value)
    return False


def _redact_config(config: dict) -> dict:
    """把 config 里的凭据替换成哨兵值。

    ⚠️ 脱敏在 store 层做 —— 前端拿不到原值，
       「保留原值」这类合并规则只能后端实现。
    ⚠️ **整个 config 递归脱敏**，不是只处理 headers / body / url ——
       凭据可以藏在任意顶层键的嵌套结构里
       （`{"auth": {"password": ...}}`），只脱三个已知键等于没脱。
    """
    out = _redact_value(config)
    # ⚠️ headers 要用**原始**的值 —— 通用递归已经按「键名含凭据」把它脱成
    #    `••••` 了，再走 `_redact_header_value` 就丢了 `Bearer ` 这类前缀。
    headers = config.get("headers")
    if isinstance(headers, dict):
        out["headers"] = {
            key: _redact_header_value(value) for key, value in headers.items()
        }
    elif headers is not None:
        # ⚠️ 非对象（历史脏数据）—— 整段脱敏，别让明文漏出去
        out["headers"] = REDACTED
    url = out.get("url")
    if isinstance(url, str):
        out["url"] = _redact_url(url)
    body = config.get("body")
    if body is not None and not isinstance(body, dict):
        # ⚠️ 非对象（历史脏数据）—— 整段脱敏。
        #    通用递归对字符串是原样返回的，`"password=xxx"` 这种会明文漏出去。
        out["body"] = REDACTED
    return out


def _merge_secret_map(old_map: dict, old_redacted: dict, new_map: dict) -> dict:
    """合并一个「键 → 值」的 map（headers / body），把哨兵值换回真值。

    - 新值 == 旧值的脱敏形式 → 还原真值
    - 新值是哨兵但旧 map 里**没有同名 key** → 报错（用户改名了）
    - 嵌套 dict 递归处理
    """
    combined: dict[str, object] = {}
    for name, value in new_map.items():
        if name not in old_map:
            if _looks_redacted(value):
                raise ValueError(
                    f"字段 {name!r} 的值是脱敏值，但旧配置里没有同名字段"
                    "（改名了？脱敏值不能作为新凭据，请重新输入）"
                )
            combined[name] = value
            continue
        old_value = old_map[name]
        old_redacted_value = (
            old_redacted.get(name) if isinstance(old_redacted, dict) else None
        )
        if (
            isinstance(value, dict)
            and isinstance(old_value, dict)
            and isinstance(old_redacted_value, dict)
        ):
            combined[name] = _merge_secret_map(old_value, old_redacted_value, value)
            continue
        if value == old_redacted_value:
            combined[name] = old_value  # 脱敏值 → 还原真值
            continue
        if _looks_redacted(value):
            raise ValueError(
                f"字段 {name!r} 的值是脱敏值，但与旧配置里的脱敏形式不一致"
                "（脱敏值不能作为新凭据，请重新输入）"
            )
        combined[name] = value
    return combined


def _merge_config(old: dict, new: dict) -> dict:
    """合并配置：**整体替换** + 哨兵值还原。

    ⚠️ 前端必须提交**完整**的 config —— 没传的顶层键会被删掉。
       新值里凡是等于旧值脱敏形式的，沿用旧真值
       （前端拿不到原值，只能把脱敏值原样传回来）。
    """
    redacted_old = _redact_config(old)
    # ⚠️ url **单独处理**（参数级还原）—— 不能走 `_merge_secret_map`：
    #    url 里的哨兵值是「被脱敏的某个参数」，不是「用户把字段改名了」。
    #    走通用合并会被当成「脱敏值不能作为新凭据」而误拒。
    rest_old = {key: value for key, value in old.items() if key != "url"}
    rest_redacted = {key: value for key, value in redacted_old.items() if key != "url"}
    rest_new = {key: value for key, value in new.items() if key != "url"}
    merged = _merge_secret_map(rest_old, rest_redacted, rest_new)
    url = new.get("url")
    old_url = old.get("url")
    if isinstance(url, str) and isinstance(old_url, str):
        merged["url"] = _merge_url(old_url, url)
    elif url is not None:
        merged["url"] = url
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
        # 检测记录的时间范围是后加的列 —— 老库补上（空值由 sync-detections 回填）。
        run_series_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(run_series)")
        }
        if run_series_columns:
            for column in ("start_ts", "end_ts"):
                if column not in run_series_columns:
                    conn.execute(
                        f"ALTER TABLE run_series ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
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
        ⚠️ HTTP 源允许**空 config**（先建后配）—— 与 `update_source` 一致。
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
        ⚠️ HTTP 源允许**空 config**（先建后配）—— 与 `add_source` 一致。
        """
        current = self.get_source_raw(source_id)  # ⚠️ 未脱敏 —— 否则密钥会被冲掉
        new_name = validate_name(name if name is not None else current.name, "数据源名称")
        new_kind = validate_kind(kind if kind is not None else current.kind)
        new_path = path if path is not None else current.path
        if new_kind == "sqlite":
            new_path = validate_name(new_path, "数据源路径")
            new_config: dict = {}  # sqlite 不用 config
        else:  # http —— 路径对它没有意义，参数都在 config 里
            new_path = new_path.strip()
            new_config = (
                current.config if config is None else _merge_config(current.config, config)
            )
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

        ⚠️ **显式给了 `alert_rules` 就以它为准** ——
           阈值是规则表的快捷视图（最低档/最高档倍数），
           这时反过来跟着规则表走，不重算、不覆盖。

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

        # ⚠️ **显式给了规则表 → 以它为准** ——
        #    阈值只是规则表的「快捷视图」（最低档/最高档倍数）。
        #    用户直接编规则表时，阈值必须跟着走，不能反过来。
        explicit_rules = fields.get("alert_rules")
        rules_json: str | None = None
        explicit_alert: float | None = None
        explicit_critical: float | None = None
        if explicit_rules is not None:
            rules = parse_rules(explicit_rules)
            multipliers = [r.multiplier for r in rules if not r.is_absolute]
            if len(set(multipliers)) != len(multipliers):
                raise ValueError("告警规则的缩放因子不能重复")
            if multipliers != sorted(multipliers):
                raise ValueError(
                    "告警规则的缩放因子必须从小到大排列（档位从低到高）"
                )
            distinct = sorted(set(multipliers))
            if len(distinct) < 2:
                raise ValueError(
                    "告警规则至少要有两个不同的缩放因子档位"
                    "（例如 P1 × 2.5、P0 × 3.75）"
                )
            explicit_alert = float(distinct[0])
            explicit_critical = float(distinct[-1])
            rules_json = json.dumps(rules_to_dicts(rules), ensure_ascii=False)

        # ⚠️ **换了算法就要换阈值** —— 分数的量纲变了。
        #
        # 统计族的分数是「几个尺度单位」（阈值 2.5 / 3.5），
        # Chronos 的分数是 [0,1] 的相对越界程度（阈值 0.5）。
        # 跨族沿用旧阈值 = 分数永远到不了 2.5 = **告警永远不触发**，
        # 而界面显示「一切正常」—— 那是假的。
        #
        # ⚠️ 只在**没显式给阈值**时才重置 ——
        #    用户手填的阈值是他自己的决定，不该被覆盖。
        #    显式给了规则表也一样 —— 那是更具体的选择。
        detector_changed = detector != current.detector
        family_changed = detector_changed and (
            detector_score_family(detector) != detector_score_family(current.detector)
        )
        # ⚠️ **同族换算法**：分数量纲一样，但**尺度的定义不同**
        #    （IQR 尺度 vs MAD 尺度 vs 去趋势后的残差 MAD），
        #    所以每个算法的**惯用阈值本来就不一样**：
        #    iqr 2.5 / mad 3.5 / zscore 3.0 / theil_sen 3.5。
        #
        #    那为什么不能一律换成新算法的默认值？
        #    因为用户可能**特意**把 mad 的阈值调成 2.5（要更灵敏）。
        #    「同族沿用旧阈值」这条规则本意就是保护那种调整。
        #
        #    ⚠️ **但它有个盲点**：它分不清
        #    「用户特意调过的阈值」与「从来没动过的默认值」。
        #    后者不该被沿用 ——
        #    用户从没调过 2.5，换到 theil_sen 后继续用 2.5，
        #    精确率会从 98% 掉到 73%，而界面**一点提示都没有**。
        #
        #    所以判据是：**两个阈值都恰好等于旧算法的默认值**时，
        #    认定它是「继承来的」，按新算法重设；
        #    只要用户动过其中任何一个，就保留他的值。
        inherited_thresholds = False
        if detector_changed and not family_changed:
            # ⚠️ 用 `detector_default_threshold` 而不是 `create_detector` ——
            #    当前算法可能是 `auto`（它不在注册表里，运行时才落到具体算法）
            old_default = detector_default_threshold(current.detector)
            inherited_thresholds = (
                abs(current.alert_threshold - old_default) < 1e-9
                and abs(current.critical_threshold - old_default * 1.5) < 1e-9
            )
        if explicit_rules is not None:
            alert = explicit_alert
            critical = explicit_critical
        elif (family_changed or inherited_thresholds) and fields.get(
            "alert_threshold"
        ) is None:
            default_threshold = float(create_detector(detector).default_threshold)
            alert = default_threshold
            critical = default_threshold * 1.5
        else:
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

        # 阈值变了才重算规则表（显式给了规则表时不重算 —— 那会把用户的规则冲掉）
        if rules_json is None and (
            alert != current.alert_threshold or critical != current.critical_threshold
        ):
            # ⚠️ **绝对值条件要保留** ——
            #    用户配的「值 > 50 记 P0」不该因为换了算法（或改了阈值）而消失。
            rules = default_rules(alert, critical) + _absolute_rules_only(
                current.alert_rules
            )
            rules_json = json.dumps(rules_to_dicts(rules), ensure_ascii=False)

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
        """改任务的检测算法（用户在多算法对比后选定其一）。

        ⚠️ **跨量纲族时阈值跟着换** —— 与 `update_job_config` 同一套理由：
           统计族的阈值是「几个尺度单位」，Chronos 的是 [0,1] 的相对量。
           沿用旧阈值 = 告警永远不触发，而界面显示「一切正常」。
        """
        if detector != AUTO_DETECTOR and detector not in DETECTOR_FACTORIES:
            raise ValueError(f"不支持的检测器: {detector}")
        current = self.get_job(job_id)
        if detector_score_family(detector) != detector_score_family(current.detector):
            default_threshold = float(create_detector(detector).default_threshold)
            alert = default_threshold
            critical = default_threshold * 1.5
            rules_json = json.dumps(
                rules_to_dicts(default_rules(alert, critical)), ensure_ascii=False
            )
            with self._conn() as conn:
                conn.execute(
                    "UPDATE jobs SET detector = ?, alert_threshold = ?,"
                    " critical_threshold = ?, alert_rules = ? WHERE id = ?",
                    (detector, alert, critical, rules_json, job_id),
                )
        else:
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

    # ---------- 检测记录 ----------

    def record_run_series(self, run_id: int, entries: Sequence[dict]) -> None:
        """把一次运行的**序列摘要**写进库。

        ⚠️ 用 `INSERT OR REPLACE` —— 同一次运行重复写入是幂等的
           （回填脚本会重跑，不能写成重复行）。
        """
        rows = [
            (
                int(run_id),
                str(entry.get("series_id", "")),
                entry.get("group"),
                int(entry.get("n", 0)),
                int(entry.get("n_valid", 0)),
                int(entry.get("n_missing", 0)),
                int(entry.get("n_alerts", 0)),
                int(entry.get("n_p0", 0)),
                1 if entry.get("sufficient", True) else 0,
                str(entry.get("detector") or ""),
                str(entry.get("metric_class") or ""),
                1 if entry.get("fallback") else 0,
                str(entry.get("file") or ""),
                str(entry.get("content_hash") or ""),
                str(entry.get("start_ts") or ""),
                str(entry.get("end_ts") or ""),
            )
            for entry in entries
        ]
        if not rows:
            return
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO run_series (run_id, series_id, group_name, n,"
                " n_valid, n_missing, n_alerts, n_p0, sufficient, detector, metric_class,"
                " fallback, file, content_hash, start_ts, end_ts)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )

    def record_alert_events(self, run_id: int, job_id: int, rows: Sequence[dict]) -> None:
        """把一次运行报出的**告警区间**写进库。"""
        payload = [
            (
                int(run_id),
                int(job_id),
                str(row.get("series_id", "")),
                row.get("group"),
                str(row.get("level", "")),
                int(row.get("level_index", 0)),
                str(row.get("start_ts", "")),
                str(row.get("end_ts", "")),
                int(row.get("n_points", 0)),
                float(row.get("max_score", 0.0)),
                str(row.get("detector") or ""),
                str(row.get("score_type") or ""),
            )
            for row in rows
        ]
        if not payload:
            return
        with self._conn() as conn:
            # ⚠️ 先删这次运行旧区间再写 —— 重跑同一次运行不能留两份。
            conn.execute("DELETE FROM alert_events WHERE run_id = ?", (int(run_id),))
            conn.executemany(
                "INSERT INTO alert_events (run_id, job_id, series_id, group_name, level,"
                " level_index, start_ts, end_ts, n_points, max_score, detector, score_type)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                payload,
            )

    def alert_events_for_run(self, run_id: int) -> list[dict]:
        """某次运行报出的全部告警区间。"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_events WHERE run_id = ? ORDER BY start_ts, series_id",
                (int(run_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_run_series(self, run_id: int) -> bool:
        """这次运行的检测结果有没有进库。

        ⚠️ 「没有告警」和「没同步进库」必须能区分开 ——
           前者是正常的，后者是数据缺失，报告里要说出来。
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM run_series WHERE run_id = ? LIMIT 1", (int(run_id),)
            ).fetchone()
        return row is not None

    def detection_records(self, job_id: int | None = None) -> list[dict]:
        """**检测记录清单** —— 每次运行的每条序列，带上指标 / 数据源维度。

        ⚠️ **只返回真正跑出结果的记录**（`file` 非空）——
           数据不足的序列没有检测产物，进总体只会稀释指标。
        """
        sql = (
            "SELECT rs.run_id, rs.series_id, rs.group_name, rs.n, rs.n_alerts,"
            " rs.n_p0, rs.sufficient, rs.detector, rs.metric_class, rs.fallback,"
            " rs.file, rs.content_hash, rs.start_ts, rs.end_ts,"
            " r.job_id, m.id AS metric_id, m.name AS metric_name,"
            " s.id AS source_id, s.name AS source_name"
            " FROM run_series rs"
            " JOIN runs r ON r.id = rs.run_id"
            " JOIN jobs j ON j.id = r.job_id"
            " JOIN metrics m ON m.id = j.metric_id"
            " JOIN sources s ON s.id = m.source_id"
            " WHERE rs.file <> ''"
        )
        params: list[object] = []
        if job_id is not None:
            sql += " AND r.job_id = ?"
            params.append(int(job_id))
        sql += " ORDER BY rs.run_id, rs.series_id"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def distinct_alert_events(self) -> dict[tuple[int, str, str], int]:
        """(metric_id, series_id, 检出结果) → **去重后**的告警事件数。

        ⚠️ **去重键是 (level, start_ts, end_ts)** ——
           滚动窗口下同一个异常区间会被连续多次运行反复报出
           （尖峰在滑出窗口前一直被报），那在用户看来是**一个**告警。
           检测记录数与告警事件数是两个不同的量，都得报出来。

        ⚠️ **带检出结果** —— 同一条序列既有报出告警的记录，也有什么都没报的记录，
           两层的告警事件数必须分开算。
        """
        with self._conn() as conn:
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

    def synced_run_ids(self) -> set[int]:
        """已经把检测结果同步进库的运行。"""
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT run_id FROM run_series").fetchall()
        return {int(row[0]) for row in rows}

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

    # ---------- 保留策略 ----------

    def all_runs(self) -> list[Run]:
        """全部运行记录（按 id 倒序 —— 新的在前）。

        保留策略要按任务分组判定，所以这里给全量而不是分页。
        ⚠️ `runs` 表正是「会一直变大」的那张表 —— 但保留窗口会把它压住，
           清理前最多也就几千行，全量读得动。
        """
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        return [Run(**dict(row)) for row in rows]

    def delete_runs(self, run_ids: Sequence[int]) -> dict[str, int]:
        """删若干次运行记录，并把引用它们的反馈的 `run_id` 置空。

        ⚠️ **反馈本身不删** —— 那是人工产生的数据，删它等于丢弃用户的劳动成果。
           只把指向已删运行的引用断开（表里没有外键约束，必须手动置 NULL）。

        返回 `{"runs": 删除数, "feedback_detached": 断开引用的反馈数}`。
        """
        ids = [int(item) for item in run_ids]
        if not ids:
            return {"runs": 0, "feedback_detached": 0}
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            cursor = conn.execute(
                f"UPDATE feedback SET run_id = NULL WHERE run_id IN ({placeholders})",
                ids,
            )
            detached = int(cursor.rowcount or 0)
            conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", ids)
        return {"runs": len(ids), "feedback_detached": detached}

    def get_retention_state(self) -> dict:
        """清理状态（上次清理时间 / 上次删了多少）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT pruned_at, deleted_runs, freed_bytes FROM retention_state"
                " WHERE id = 1"
            ).fetchone()
        if row is None:
            return {"pruned_at": None, "deleted_runs": 0, "freed_bytes": 0}
        return {
            "pruned_at": row["pruned_at"],
            "deleted_runs": int(row["deleted_runs"]),
            "freed_bytes": int(row["freed_bytes"]),
        }

    def set_retention_state(
        self, *, pruned_at: str, deleted_runs: int, freed_bytes: int
    ) -> None:
        """写清理状态（单行 upsert）。"""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO retention_state (id, pruned_at, deleted_runs, freed_bytes)"
                " VALUES (1, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " pruned_at = excluded.pruned_at,"
                " deleted_runs = excluded.deleted_runs,"
                " freed_bytes = excluded.freed_bytes",
                (pruned_at, int(deleted_runs), int(freed_bytes)),
            )
