"""把 OpenTelemetry 指标写进 SQLite —— 自己实现的 `MetricExporter`。

为什么需要它：

- OTel Python SDK 只提供 OTLP 与 Console 两种 exporter，**没有 file / SQLite**；
- 「本地文件 + 能按时间范围查询」在 OTel 里只能自己写 exporter，或者上 Prometheus。

两个关键取舍：

1. **DELTA temporality**：cumulative 下每次导出都是累计值，存进去后查询要自己做
   差分；用 DELTA 让 SDK 算好，exporter 直接存增量。
2. **两类表**：
   - `metric_samples` 只存**时间线需要的聚合量**（每分钟十几行），30 天也就几十 MB；
   - `metric_totals` 存**全维度累计**（按路由 / 算法 / 任务），只保留最新一行，
     用于页面上的统计表，不随时间膨胀。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from opentelemetry.sdk.metrics._internal.instrument import (
    Counter,
    Histogram,
    ObservableCounter,
    ObservableUpDownCounter,
    UpDownCounter,
)
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    MetricExporter,
    MetricExportResult,
    MetricsData,
)

from anomaly_lab.observability.buckets import DURATION_BUCKETS_MS

logger = logging.getLogger(__name__)

#: 时间线只需要「每分钟总量」的指标 —— 其余维度不进 `metric_samples`，
#: 否则 30 天会被路由 × 状态的组合撑爆。
SAMPLE_LABEL_KEYS: dict[str, tuple[str, ...]] = {
    "job.runs": ("status",),
    "alerts.fired": ("level",),
}

#: 统计表需要的维度标签。不在表里的标签直接丢弃（比如未来的 trace_id）。
TOTAL_LABEL_KEYS: frozenset[str] = frozenset(
    {"method", "route", "status", "detector", "job", "level", "stage"}
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_samples (
  minute TEXT NOT NULL,
  metric TEXT NOT NULL,
  labels TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  value REAL,
  count INTEGER,
  sum REAL,
  buckets TEXT,
  PRIMARY KEY (minute, metric, labels)
);
CREATE INDEX IF NOT EXISTS idx_metric_samples_minute ON metric_samples(minute);

CREATE TABLE IF NOT EXISTS metric_totals (
  metric TEXT NOT NULL,
  labels TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  value REAL NOT NULL DEFAULT 0,
  count INTEGER,
  sum REAL,
  buckets TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (metric, labels)
);
"""


def _minute_of(time_unix_nano: int) -> str:
    """纳秒时间戳 → `2026-11-06T10:30`（UTC，分钟粒度）。"""
    moment = datetime.fromtimestamp(int(time_unix_nano) / 1e9, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M")


def _labels(attributes: Mapping[str, object] | None, allowed: Iterable[str]) -> str:
    """属性 → 稳定的 JSON 字符串；空标签用空串（不是 `{}`）。"""
    if not attributes:
        return ""
    picked = {
        key: str(attributes[key])
        for key in sorted(attributes)
        if key in allowed and attributes[key] not in (None, "")
    }
    return json.dumps(picked, ensure_ascii=False, sort_keys=True) if picked else ""


def _buckets_of(point: object) -> list[int]:
    """OTel histogram 的桶计数补齐到本地桶长度。

    ⚠️ OTel 的 `bucket_counts` 比 `explicit_bounds` 多一个（+Inf 桶）。
       本地分位只在前 N 个边界上插值，多出来的那桶不参与插值。
    """
    counts = list(getattr(point, "bucket_counts", ()) or ())
    size = len(DURATION_BUCKETS_MS)
    if len(counts) > size:
        counts = counts[:size]
    return counts + [0] * (size - len(counts))


class SqliteMetricExporter(MetricExporter):
    """把 OTel 数据点按分钟累加后写 SQLite。"""

    def __init__(
        self,
        db_path: Path,
        *,
        retention_days: int = 30,
        prune_interval_seconds: float = 3600.0,
    ) -> None:
        super().__init__(
            preferred_temporality={
                Counter: AggregationTemporality.DELTA,
                UpDownCounter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
                ObservableCounter: AggregationTemporality.DELTA,
                ObservableUpDownCounter: AggregationTemporality.DELTA,
            }
        )
        self.db_path = Path(db_path)
        self.retention_days = max(1, int(retention_days))
        self.prune_interval_seconds = float(prune_interval_seconds)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        #: minute -> (metric, labels) -> 累加行
        self._acc: dict[str, dict[tuple[str, str], dict]] = {}
        #: (metric, labels) -> 累计行（只保留最新）
        self._totals: dict[tuple[str, str], dict] = {}
        self._last_prune = 0.0

    # ── MetricExporter 接口 ────────────────────────────────

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: object,
    ) -> MetricExportResult:
        try:
            with self._lock:
                self._ingest(metrics_data)
                self._flush_completed()
                self._write_totals()
                self._maybe_prune()
            return MetricExportResult.SUCCESS
        except Exception:
            # ⚠️ 导出失败不能让 reader 线程退出 —— 返回 FAILURE，下一轮再试。
            logger.exception("写入监控指标失败")
            return MetricExportResult.FAILURE

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        try:
            with self._lock:
                self._flush_completed()
                self._write_totals()
            return True
        except Exception:
            logger.exception("flush 监控指标失败")
            return False

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: object) -> None:
        self.force_flush(timeout_millis)
        with self._lock:
            self._conn.close()

    # ── 摄入 ────────────────────────────────────────────────

    def _ingest(self, metrics_data: MetricsData) -> None:
        from opentelemetry.sdk.metrics._internal.point import Gauge, Histogram, Sum

        for resource_metrics in metrics_data.resource_metrics:
            for scope_metrics in resource_metrics.scope_metrics:
                for metric in scope_metrics.metrics:
                    data = metric.data
                    if isinstance(data, Sum):
                        for point in data.data_points:
                            self._add_number(
                                metric.name,
                                "sum",
                                point.attributes,
                                point.time_unix_nano,
                                float(point.value),
                            )
                    elif isinstance(data, Gauge):
                        for point in data.data_points:
                            self._add_number(
                                metric.name,
                                "gauge",
                                point.attributes,
                                point.time_unix_nano,
                                float(point.value),
                            )
                    elif isinstance(data, Histogram):
                        for point in data.data_points:
                            self._add_histogram(metric.name, point)

    def _add_number(
        self,
        metric: str,
        kind: str,
        attributes: Mapping[str, object] | None,
        time_unix_nano: int,
        value: float,
    ) -> None:
        minute = _minute_of(time_unix_nano)
        labels = _labels(attributes, SAMPLE_LABEL_KEYS.get(metric, ()))
        key = (metric, labels)
        row = self._acc.setdefault(minute, {}).get(key)
        if row is None:
            row = {"kind": kind, "value": 0.0}
            self._acc[minute][key] = row
        if kind == "gauge":
            # gauge 是瞬时值，同一周期内覆盖而不是相加
            row["value"] = value
        else:
            row["value"] += value

        total_key = (metric, _labels(attributes, TOTAL_LABEL_KEYS))
        total = self._totals.get(total_key)
        if total is None:
            total = {"kind": kind, "value": 0.0}
            self._totals[total_key] = total
        if kind == "gauge":
            total["value"] = value
        else:
            total["value"] += value

    def _add_histogram(self, metric: str, point: object) -> None:
        minute = _minute_of(point.time_unix_nano)  # type: ignore[attr-defined]
        labels = _labels(point.attributes, SAMPLE_LABEL_KEYS.get(metric, ()))  # type: ignore[attr-defined]
        key = (metric, labels)
        row = self._acc.setdefault(minute, {}).get(key)
        if row is None:
            row = {
                "kind": "histogram",
                "count": 0,
                "sum": 0.0,
                "buckets": [0] * len(DURATION_BUCKETS_MS),
            }
            self._acc[minute][key] = row
        row["count"] += int(point.count)  # type: ignore[attr-defined]
        row["sum"] += float(point.sum or 0.0)  # type: ignore[attr-defined]
        for index, value in enumerate(_buckets_of(point)):
            row["buckets"][index] += value

        total_key = (metric, _labels(point.attributes, TOTAL_LABEL_KEYS))  # type: ignore[attr-defined]
        total = self._totals.get(total_key)
        if total is None:
            total = {
                "kind": "histogram",
                "count": 0,
                "sum": 0.0,
                "buckets": [0] * len(DURATION_BUCKETS_MS),
            }
            self._totals[total_key] = total
        total["count"] += int(point.count)  # type: ignore[attr-defined]
        total["sum"] += float(point.sum or 0.0)  # type: ignore[attr-defined]
        for index, value in enumerate(_buckets_of(point)):
            total["buckets"][index] += value

    # ── 落库 ────────────────────────────────────────────────

    def _flush_completed(self) -> None:
        """把累加器落库。

        ⚠️ **当前分钟也写**（增量合并），不是等它过完 ——
           否则服务刚启动的第一分钟页面是空的，用户以为监控坏了。
           写完后清空这一分钟的内存增量，下一轮继续累加。
        """
        if not self._acc:
            return
        now_minute = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
        for minute in sorted(self._acc):
            rows = self._acc[minute]
            if rows:
                self._write_samples(minute, rows)
            # 过完的分钟直接丢掉 key；当前分钟保留空壳，继续接增量
            if minute < now_minute:
                del self._acc[minute]
            else:
                self._acc[minute] = {}

    def _flush_all(self) -> None:
        self._flush_completed()

    def _write_samples(self, minute: str, rows: dict[tuple[str, str], dict]) -> None:
        """把这一分钟的增量合并进已有行。

        ⚠️ 不能直接 `INSERT OR REPLACE` —— `force_flush` 可能在同一个分钟里
           被调多次（测试、关停），后一次会把前一次的数据覆盖掉。
           先读旧行再做增量合并，语义才对。
        """
        merged: dict[tuple[str, str], dict] = {}
        for row in self._conn.execute(
            "SELECT metric, labels, kind, value, count, sum, buckets"
            " FROM metric_samples WHERE minute = ?",
            (minute,),
        ).fetchall():
            merged[(row[0], row[1])] = {
                "kind": row[2],
                "value": row[3],
                "count": row[4],
                "sum": row[5],
                "buckets": json.loads(row[6]) if row[6] else None,
            }

        for key, incoming in rows.items():
            target = merged.get(key)
            if target is None:
                merged[key] = dict(incoming)
                continue
            if incoming["kind"] == "gauge":
                target["value"] = incoming["value"]
            elif incoming["kind"] == "histogram":
                target["count"] = int(target.get("count") or 0) + int(incoming["count"])
                target["sum"] = float(target.get("sum") or 0.0) + float(incoming["sum"])
                base = target.get("buckets") or [0] * len(DURATION_BUCKETS_MS)
                target["buckets"] = [
                    left + right
                    for left, right in zip(base, incoming["buckets"], strict=False)
                ]
            else:
                target["value"] = float(target.get("value") or 0.0) + float(
                    incoming["value"]
                )

        payload = [
            (
                minute,
                metric,
                labels,
                row["kind"],
                row.get("value"),
                row.get("count"),
                row.get("sum"),
                json.dumps(row["buckets"]) if row.get("buckets") else None,
            )
            for (metric, labels), row in merged.items()
        ]
        if not payload:
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO metric_samples"
            " (minute, metric, labels, kind, value, count, sum, buckets)"
            " VALUES (?,?,?,?,?,?,?,?)",
            payload,
        )
        self._conn.commit()

    def _write_totals(self) -> None:
        if not self._totals:
            return
        updated = datetime.now(UTC).isoformat(timespec="seconds")
        payload = [
            (
                metric,
                labels,
                row["kind"],
                float(row.get("value") or 0.0),
                row.get("count"),
                row.get("sum"),
                json.dumps(row["buckets"]) if "buckets" in row else None,
                updated,
            )
            for (metric, labels), row in self._totals.items()
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO metric_totals"
            " (metric, labels, kind, value, count, sum, buckets, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            payload,
        )
        self._conn.commit()

    def _maybe_prune(self) -> None:
        stamp = time.time()
        if stamp - self._last_prune < self.prune_interval_seconds:
            return
        self._last_prune = stamp
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        self._conn.execute("DELETE FROM metric_samples WHERE minute < ?", (cutoff,))
        self._conn.commit()


class MetricsStore:
    """监控数据的只读查询（每次开独立连接，和 exporter 的写连接分开）。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.is_file():
            return None
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def timeline_rows(self, since_minute: str) -> list[dict]:
        conn = self._connect()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT minute, metric, labels, kind, value, count, sum, buckets"
                " FROM metric_samples WHERE minute >= ? ORDER BY minute",
                (since_minute,),
            ).fetchall()
        except sqlite3.Error:
            # 表还没建（进程刚启动）—— 当作没有历史
            return []
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def total_rows(self) -> list[dict]:
        conn = self._connect()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT metric, labels, kind, value, count, sum, buckets, updated_at"
                " FROM metric_totals"
            ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()
        return [dict(row) for row in rows]

    def latest_value(self, metric: str) -> float | None:
        for row in self.total_rows():
            if row["metric"] == metric:
                return float(row["value"])
        return None
