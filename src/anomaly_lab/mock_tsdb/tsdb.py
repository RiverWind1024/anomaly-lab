"""假远端的存储层：SQLite（WAL）+ 写入 + 只读查询。

⚠️ **自己开 WAL** —— 平台以 `mode=ro` 打开这个库。
   WAL 让「写者不阻塞读者」，只读连接能读到已提交的最新数据。
   （平台 store 的 WAL 设置在 `data/platform.db`，与这里无关。）
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from urllib.parse import quote

from anomaly_lab.mock_tsdb.generator import (
    KIND_GAP,
    KIND_NULL,
    SAMPLE_SECONDS,
    SERIES,
    Generator,
    spec_fingerprint,
)
from anomaly_lab.platform.validation import validate_readonly_sql

TABLE = "metrics"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    ts     TEXT NOT NULL,
    series TEXT NOT NULL,
    value  REAL,
    -- ⚠️ 唯一约束是 `INSERT OR IGNORE` 真正生效的前提 ——
    --    没有它，IGNORE 什么都不忽略，重启后历史数据会翻倍。
    UNIQUE (ts, series)
);
CREATE INDEX IF NOT EXISTS idx_{TABLE}_ts ON {TABLE}(ts);

-- 时间锚点：点序号 → 时间戳的映射基准。
-- ⚠️ **必须持久化** —— 否则每次重启 index 0 都对应「现在」，
--    同一个 index 有了不同时间戳，历史数据与新数据会重影。
CREATE TABLE IF NOT EXISTS mock_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ANCHOR_KEY = "anchor_ts"

#: 序列定义的指纹 —— 见 `generator.spec_fingerprint()`。
SERIES_FINGERPRINT_KEY = "series_fingerprint"


def to_iso(value: datetime) -> str:
    """时刻 → `2026-11-02T10:00:00+00:00`。

    ⚠️ **必须与平台的 `to_iso()` 完全一致** —— 平台用 `+00:00` 结尾的
       字面量做时间条件，而 SQLite 对 TEXT 列是**字典序**比较。
       格式不统一 → 边界行的比较结果会错（D55）。
    """
    return value.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _connect(path: Path) -> sqlite3.Connection:
    """读写连接 —— 假远端自己用（要能写）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def _connect_readonly(path: Path) -> sqlite3.Connection:
    """只读连接 —— 查询走这条。

    ⚠️ `mode=ro` 让 SQLite **在引擎层**拒绝写入 ——
       比「查询前先查一遍关键字」可靠得多。
    """
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    return sqlite3.connect(uri, uri=True)


class MockTsdb:
    """假远端的数据存储。

    ⚠️ **连接是 thread-local 的** —— SQLite 的连接默认绑定创建它的线程
       （`check_same_thread=True`），而后台写入线程要用同一个库。
       跨线程共用一个连接会抛 `ProgrammingError`。
    """

    def __init__(self, path: Path, sample_seconds: int = SAMPLE_SECONDS) -> None:
        self.path = Path(path)
        #: 采样间隔（秒）—— 点序号 → 时间戳的步长。
        self.sample_seconds = int(sample_seconds)
        self._local = threading.local()
        # ⚠️ **必须是可重入锁** —— `_db` 惰性建连接时会重入 `open()`，
        #    而 `open()` 也要拿这把锁。用普通 Lock 就是死锁。
        self._lock = threading.RLock()
        self._generator = Generator(SERIES)
        self._anchor: datetime | None = None
        self._closed = False

    # ---------- 生命周期 ----------

    def open(self, history_points: int = 360) -> None:
        """打开（并建表）。"""
        if self._closed:
            raise RuntimeError("存储已关闭")
        with self._lock:
            if getattr(self._local, "conn", None) is None:
                self._local.conn = _connect(self.path)
            if self._anchor is None:
                self._anchor = self._load_or_create_anchor(history_points)
            self._check_series_fingerprint()

    def _check_series_fingerprint(self) -> None:
        """⚠️ **序列定义与库里已有的数据必须对得上**。

        db 里存的是**按旧定义造出来的历史数据**。
        改了曲线定义（比如加了一条新曲线）之后，旧 db 里：
          - 缺新曲线的历史（那段时间它根本没被造过）；
          - 各曲线的 index 也可能错位。

        这种错位**不会报错** —— 只会让图看起来莫名其妙，
        或者让检测器在「不存在的数据」上跑。

        所以指纹对不上就**明确报错**，让人删掉 db 重造，
        而不是让它静默跑出一堆怪数据。

        ⚠️ 没有指纹行 = 旧格式的库（指纹是后加的）——
           同样报错，除非库里一条数据都没有（那就是全新库）。
        """
        expected = spec_fingerprint()
        row = self._db.execute(
            "SELECT value FROM mock_meta WHERE key = ?", (SERIES_FINGERPRINT_KEY,)
        ).fetchone()
        if row is not None:
            if str(row[0]) != expected:
                raise RuntimeError(
                    f"序列定义已变（指纹 {expected}），但 {self.path} 是按旧定义造的。"
                    f"删掉这个文件（或它的 -wal/-shm）再重启 —— "
                    f"否则新旧数据会错位。"
                )
            return

        has_data = self._db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        if has_data:
            raise RuntimeError(
                f"{self.path} 里已有数据，但没有序列定义指纹 —— "
                f"它是旧格式的库。删掉这个文件（或它的 -wal/-shm）再重启。"
            )
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO mock_meta (key, value) VALUES (?, ?)",
                (SERIES_FINGERPRINT_KEY, expected),
            )

    def close(self) -> None:
        with self._lock:
            conn = getattr(self._local, "conn", None)
            if conn is not None:
                conn.close()
                self._local.conn = None
            self._closed = True

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def _db(self) -> sqlite3.Connection:
        """当前线程的写连接（没有就开一个）。

        ⚠️ **不经过 `open()`** —— 那会重入锁（`open` 也要拿锁）。
           建表由 `open()` 负责；这里只管连接。
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = _connect(self.path)
            self._local.conn = conn
        return conn

    # ---------- 时间锚点 ----------

    def _load_or_create_anchor(self, history_points: int) -> datetime:
        """读时间锚点；没有就创建一个并持久化。

        ⚠️ 锚点对齐到**分钟** —— 采样点落在整分钟上，
           平台的 `iso_utc` 字面量（秒级）才能干净地比较。

        ⚠️ **锚点在「过去」** —— index 0 对应「`history_points` 分钟前」，
           回填的数据才落在过去而不是未来（未来数据会让检测器
           取不到「最近窗口」）。
        """
        row = self._db.execute(
            "SELECT value FROM mock_meta WHERE key = ?", (ANCHOR_KEY,)
        ).fetchone()
        if row is not None:
            return parse_iso(str(row[0]))
        anchor = (
            datetime.now(UTC).replace(second=0, microsecond=0)
            - timedelta(seconds=history_points * self.sample_seconds)
        )
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO mock_meta (key, value) VALUES (?, ?)",
                (ANCHOR_KEY, to_iso(anchor)),
            )
        return anchor

    @property
    def anchor(self) -> datetime:
        """点序号 0 对应的时刻。"""
        if self._anchor is None:
            self.open()
        assert self._anchor is not None
        return self._anchor

    def timestamp_for(self, index: int) -> str:
        """点序号 → 时间戳。"""
        moment = self.anchor + timedelta(seconds=index * self.sample_seconds)
        return to_iso(moment)

    def index_for(self, moment: datetime) -> int:
        """时刻 → 点序号（**向下取整**到已过去的最后一个采样点）。

        ⚠️ 必须向下取整 —— 向上取整会造出「未来」的点，
           那些点不该存在。
        """
        delta = moment - self.anchor
        return max(0, int(delta.total_seconds() // self.sample_seconds))

    # ---------- 写入 ----------

    def produce_until(self, moment: datetime) -> int:
        """造数并写入，直到时间到达 `moment`，返回写入的行数。

        ⚠️ **按时间推进，不按次数** —— 进程被挂起后醒来，
           要一次补齐落下的所有点，否则时间轴与真实时间脱节。

        ⚠️ 幂等 —— 已存在的 `(ts, series)` 不重复写（唯一约束）。

        ⚠️ **全程持锁** —— 造数状态（AR(1) 的前一点）是共享的，
           两个线程同时推进会造出重复的点。
        """
        with self._lock:
            target_index = self.index_for(moment)
            if target_index <= self._generator.index:
                return 0
            produced = self._generator.advance_to(target_index)
            return self.write_points(produced)

    def write_points(
        self, produced: list[tuple[str, int, float | None, str]]
    ) -> int:
        """写入一批点，返回实际写入的行数。

        ⚠️ 断流的点**不写**（那段时间就是没有数据）。
        """
        rows = [
            (self.timestamp_for(index), name, value)
            for name, index, value, kind in produced
            if kind != KIND_GAP and value is not None
        ]
        rows += [
            (self.timestamp_for(index), name, None)
            for name, index, value, kind in produced
            if kind == KIND_NULL
        ]
        return self._insert(rows)

    def _insert(self, rows: list[tuple[str, str, float | None]]) -> int:
        if not rows:
            return 0
        with self._db:
            self._db.executemany(
                f"INSERT OR IGNORE INTO {TABLE} (ts, series, value) VALUES (?, ?, ?)",
                rows,
            )
        return len(rows)

    def latest_timestamp(self) -> str | None:
        row = self._db.execute(f"SELECT MAX(ts) FROM {TABLE}").fetchone()
        return row[0] if row and row[0] else None

    def prune(self, retention_hours: int) -> int:
        """删掉保留窗口之外的数据，返回删除的行数。

        ⚠️ 按**时间列**删，不按行号 —— 断流的点不存在，
           但它们的位置仍在窗口内。
        """
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        with self._lock, self._db:
            cursor = self._db.execute(
                f"DELETE FROM {TABLE} WHERE ts < ?", (to_iso(cutoff),)
            )
            deleted = cursor.rowcount or 0
        return deleted

    # ---------- 查询 ----------

    def query(self, sql: str) -> tuple[list[str], list[tuple]]:
        """执行只读 SQL，返回 `(列名, 行)`。

        ⚠️ 只读校验 + `mode=ro` 连接，双保险 ——
           假远端是个 HTTP 端点，不能变成「能删库的接口」。
        """
        statement = validate_readonly_sql(sql)
        with closing(_connect_readonly(self.path)) as conn:
            cursor = conn.execute(statement)
            columns = [item[0] for item in cursor.description or []]
            rows = cursor.fetchall()
        return columns, rows
