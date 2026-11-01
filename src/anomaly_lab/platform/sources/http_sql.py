"""HTTP 透传连接器：把 SQL 原样发给远端 SQL 网关，取回表格。

对应的是 **SQL-over-HTTP** 的远端（InfluxDB 3 的 `/api/v3/query_sql`、
ClickHouse 的 `/?query=`、TDengine 的 `/rest/sql`…）——
它们自己执行 SQL，只返回结果集，平台不落地也不代算。

⚠️ 安全边界是**远端账号的权限**，不是平台的只读校验 ——
   `validate_readonly_sql` 的关键字黑名单可被绕过。UI 与文档必须讲明。
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

import pandas as pd

from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources.base import TimeContext, sql_literal
from anomaly_lab.platform.validation import validate_identifier


class RemoteError(RuntimeError):
    """远端返回了错误状态，或连接失败。"""


def _substitute(template: str, sql: str, *, encode: bool) -> str:
    """把 `{sql}` 占位符换成真实 SQL。

    ⚠️ URL 里的要 URL 编码，body 里的**不能** ——
       百分号编码会污染 SQL 本身。
    """
    value = urllib.parse.quote(sql) if encode else sql
    return template.replace("{sql}", value)


def _dig(payload: Any, path: str) -> Any:
    """按点号路径取值（`data.items`）。"""
    current = payload
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            raise ValueError(f"rows_path 在响应里找不到: {path}")
        if current is None:
            raise ValueError(f"rows_path 在响应里找不到: {path}")
    return current


def _parse_json(text: str, rows_path: str | None) -> pd.DataFrame:
    payload = json.loads(text)
    if rows_path:
        payload = _dig(payload, rows_path)
    if isinstance(payload, dict):
        payload = [payload]
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    # ⚠️ 远端返回了非预期结构 —— 报 ValueError（不是 TypeError）：
    #    这是远端数据的问题，路由层按 ValueError 返回 400。
    raise ValueError(f"JSON 响应不是对象数组: {type(payload).__name__}")


def _parse_csv(text: str) -> pd.DataFrame:
    # ⚠️ 远端 CSV 约定带表头行（InfluxDB 的 csv format 带头）
    return pd.read_csv(io.StringIO(text))


def _parse_jsonl(text: str) -> pd.DataFrame:
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return pd.DataFrame(rows)


class HttpSqlConnector:
    """HTTP 透传连接器。"""

    kind = "http"

    def __init__(self, source: Source) -> None:
        self.source = source
        self.config = source.config or {}

    # ---------- 配置 ----------

    @property
    def _timeout(self) -> float:
        return float(self.config.get("timeout_seconds", 30) or 30)

    @property
    def _format(self) -> str:
        return str(self.config.get("format", "json") or "json")

    # ---------- 连接器协议 ----------

    def describe(self) -> str:
        return f"HTTP {self.config.get('method', 'GET')} {self.config.get('url', '')}"

    def test_connection(self) -> tuple[bool, str]:
        try:
            self.execute_sql("SELECT 1")
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return True, "连接正常"

    def build_time_condition(self, ctx: TimeContext) -> tuple[str, tuple]:
        """HTTP 方言的时间条件（字面量，无绑定参数）。

        ⚠️ 与 SQLite 的 `julianday()` 完全不同 —— 这是**故意的**：
           浏览预览与指标运行时都走这里，两边结果必然一致。
        """
        low = sql_literal(ctx.start, ctx.fmt, ctx.timezone)
        high = sql_literal(ctx.end, ctx.fmt, ctx.timezone)
        condition = f'"{ctx.column}" >= {low} AND "{ctx.column}" < {high}'
        return condition, ()

    def execute_sql(
        self, sql: str, *, limit: int | None = None, params: tuple = ()
    ) -> pd.DataFrame:
        """把 SQL 发给远端，返回表格。

        ⚠️ `params` 被忽略 —— HTTP 侧没有绑定参数的概念，
           条件里的值都是字面量。
        """
        text = sql
        if limit is not None:
            text = f"SELECT * FROM ({sql}) LIMIT {int(limit)}"
        payload = self._request(text)
        fmt = self._format
        if fmt == "csv":
            return _parse_csv(payload)
        if fmt == "jsonl":
            return _parse_jsonl(payload)
        return _parse_json(payload, self.config.get("rows_path"))

    def fetch(self, metric: Metric, start: datetime, end: datetime) -> pd.DataFrame:
        """取 [start, end) 的数据（做 `$timefilter` 替换）。"""
        validate_identifier(metric.time_column, "time_column")
        condition, _ = self.build_time_condition(
            TimeContext(
                column=metric.time_column,
                fmt=metric.time_format,
                timezone=metric.source_timezone,
                start=start,
                end=end,
            )
        )
        return self.execute_sql(metric.query.replace("$timefilter", condition))

    # ---------- HTTP ----------

    def _request(self, sql: str) -> str:
        url = _substitute(str(self.config.get("url", "")), sql, encode=True)
        method = str(self.config.get("method", "GET")).upper()
        headers = {str(k): str(v) for k, v in (self.config.get("headers") or {}).items()}
        body_template = self.config.get("body")

        data: bytes | None = None
        if method == "POST":
            if isinstance(body_template, dict):
                body = {
                    key: (
                        _substitute(str(value), sql, encode=False)
                        if isinstance(value, str)
                        else value
                    )
                    for key, value in body_template.items()
                }
                # ⚠️ 请求的格式必须与解析的格式一致 —— 远端按 body["format"]
                #    返回，平台按 config["format"] 解析，两边不一致就是解析失败。
                #    body 里没写就注入配置里的；写了但不一样 → 当场报错。
                asked = str(body.get("format", "") or "")
                if not asked:
                    body["format"] = self._format
                elif asked != self._format:
                    raise ValueError(
                        f"body 里的 format={asked!r} 与配置的 format={self._format!r} 不一致"
                        "（远端会按前者返回、平台按后者解析）"
                    )
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            else:
                data = sql.encode("utf-8")
                headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RemoteError(f"远端返回 {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise TimeoutError(f"请求远端超时（{self._timeout}s）") from exc
            raise RemoteError(f"无法连接远端: {reason}") from exc
