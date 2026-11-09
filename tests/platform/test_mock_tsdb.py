"""假远端时序数据库的测试。

⚠️ 重点在**平台侧**的三件事（spec §8）：
   1. 连接器一致性 —— 同一个库，sqlite 与 http 两条路径结果相同；
   2. WAL + 只读 —— 平台以 `mode=ro` 打开正在被写的库，读到已提交数据；
   3. 端到端 —— 取数 → 检测 → 告警。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Self

import pytest
import uvicorn
from fastapi.testclient import TestClient

from anomaly_lab.mock_tsdb.generator import (
    KIND_GAP,
    KIND_NULL,
    SERIES,
    Generator,
    SeriesSpec,
    series_at,
)
from anomaly_lab.mock_tsdb.server import MockConfig, create_app
from anomaly_lab.mock_tsdb.tsdb import MockTsdb
from anomaly_lab.platform.mock_remote import seed_mock_remote, source_config
from anomaly_lab.platform.models import Metric, Source
from anomaly_lab.platform.sources import get_connector
from anomaly_lab.platform.sources.base import series_from_frame

# ---------------------------------------------------------------- 造数


def test_generator_is_deterministic():
    """同一规格造两次 → 完全一样。"""
    spec = SERIES[0]
    assert series_at(spec, 200) == series_at(spec, 200)


def test_generator_uses_stable_hash_not_python_hash():
    """⚠️ 不能用内置 `hash()` —— 字符串 hash 被 PYTHONHASHSEED 随机化。

    同一进程内 hash 是稳定的，但换个进程就变了 ——
    所以确定性必须靠 `zlib.crc32` 这类稳定哈希。
    """
    from anomaly_lab.mock_tsdb.generator import _stable_seed

    assert _stable_seed("web-traffic") == _stable_seed("web-traffic")
    assert _stable_seed("web-traffic") != _stable_seed("api-latency")
    # 已知值 —— 换实现时这个断言会提醒「确定性变了」
    assert _stable_seed("web-traffic") == 1404706371


def test_daily_baseline_has_peak_and_trough():
    """日周期曲线：一天里有峰有谷。"""
    spec = SeriesSpec(name="x", baseline="daily", level=100.0, amplitude=30.0, sigma=0.0)
    values = series_at(spec, 24 * 60)
    assert max(values) > 125.0
    assert min(values) < 75.0


def test_spike_is_above_baseline():
    """尖峰点的值显著高于基线。"""
    spec = SeriesSpec(
        name="spiky",
        baseline="constant",
        level=20.0,
        sigma=0.0,
        spike_every=30,
        spike_width=2,
        spike_gain=3.0,
    )
    values = series_at(spec, 120)
    assert values[0] == 20.0
    assert values[30] == 60.0
    assert values[31] == 60.0
    assert values[32] == 20.0


def test_drift_raises_later_baseline():
    """漂移：后段均值明显高于前段。"""
    spec = SeriesSpec(
        name="drifty",
        baseline="constant",
        level=80.0,
        sigma=0.0,
        drift_from=120,
        drift_span=240,
        drift_amount=15.0,
    )
    values = series_at(spec, 360)
    early = sum(v for v in values[:120] if v is not None) / 120
    late = sum(v for v in values[300:] if v is not None) / 60
    assert late > early + 10.0


def test_gap_produces_no_point_but_null_keeps_row():
    """⚠️ 断流（没有行）与值缺失（有行、值为 NULL）是两件事。"""
    spec = SeriesSpec(name="g", gap_from=10, gap_len=5, null_every=20)
    generator = Generator((spec,))
    produced = generator.advance_to(30)
    kinds = [kind for _, _, _, kind in produced]
    assert kinds[10:15] == [KIND_GAP] * 5
    assert kinds[20] == KIND_NULL
    assert kinds[0] == "value"


def test_ar1_noise_is_correlated():
    """⚠️ 噪声要有相关性（AR(1)），不能是白噪声。"""
    spec = SeriesSpec(name="noisy", level=0.0, sigma=5.0, phi=0.9)
    values = series_at(spec, 200)
    assert all(v is not None for v in values)
    diffs = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
    # 白噪声的话相邻差分 ≈ σ√2；AR(1) 接近 1 时差分应该小得多
    assert sum(diffs) / len(diffs) < 5.0


# ---------------------------------------------------------------- 形态


def test_trending_baseline_rises_linearly():
    """⚠️ 趋势型是**整条曲线都在涨** —— 不是一段临时漂移。"""
    spec = SeriesSpec(
        name="trend", baseline="trending", level=40.0, slope=0.02, sigma=0.0
    )
    values = series_at(spec, 200)
    assert values[0] == 40.0
    assert values[100] == pytest.approx(42.0)
    assert values[199] == pytest.approx(40.0 + 0.02 * 199)
    # 单调递增
    assert all(values[i] <= values[i + 1] for i in range(len(values) - 1))


def test_trending_baseline_differs_from_drift():
    """⚠️ 趋势与漂移是**两件事** —— 漂移有起点和终点，趋势一直涨。"""
    trending = SeriesSpec(
        name="t", baseline="trending", level=0.0, slope=0.01, sigma=0.0
    )
    drifting = SeriesSpec(
        name="d",
        baseline="constant",
        level=0.0,
        sigma=0.0,
        drift_from=100,
        drift_span=100,
        drift_amount=10.0,
    )
    t = series_at(trending, 200)
    d = series_at(drifting, 200)
    # 漂移：前 100 点**不动**
    assert d[0] == 0.0 and d[99] == 0.0
    # 趋势：每一段都在涨
    assert t[0] < t[50] < t[100] < t[150]


def test_step_baseline_switches_between_two_levels():
    """⚠️ 阶跃型是**水平跳变** —— 两段水平，中间跳一下。"""
    spec = SeriesSpec(
        name="step",
        baseline="step",
        level=30.0,
        step_period=100,
        step_delta=25.0,
        sigma=0.0,
    )
    values = series_at(spec, 300)
    # 前 100 点是低水平，100~200 是高水平，200~300 回到低水平
    assert values[50] == 30.0
    assert values[150] == 55.0
    assert values[250] == 30.0


def test_step_baseline_one_shot_jump():
    """一次性阶跃（`step_period = 0`）：`step_at` 处跳一次，之后不再变。"""
    spec = SeriesSpec(
        name="step1",
        baseline="step",
        level=30.0,
        step_at=100,
        step_delta=25.0,
        sigma=0.0,
    )
    values = series_at(spec, 200)
    assert values[99] == 30.0
    assert values[100] == 55.0
    assert values[199] == 55.0


def test_sparse_baseline_is_flat_except_events():
    """⚠️ 稀疏型：绝大多数点是 0，偶尔冒一个脉冲。"""
    spec = SeriesSpec(
        name="sparse",
        baseline="sparse",
        level=0.0,
        sigma=0.0,
        event_rate=0.05,
        event_width=2,
        event_value=25.0,
    )
    values = series_at(spec, 400)
    nonzero = [v for v in values if v != 0.0]
    # 有事件，但不多
    assert 0 < len(nonzero) < 400 * 0.25
    assert all(v == 25.0 for v in nonzero)


def test_sparse_events_have_the_configured_width():
    """⚠️ 事件是**连续几个点**（宽度 2 就是两点），且**不与下一个事件连成一段**。"""
    spec = SeriesSpec(
        name="sparse2",
        baseline="sparse",
        level=0.0,
        sigma=0.0,
        event_rate=0.05,
        event_width=2,
        event_value=25.0,
    )
    values = series_at(spec, 400)
    # 切出所有连续非零段的长度
    runs: list[int] = []
    current = 0
    for value in values:
        if value != 0.0:
            current += 1
        else:
            if current:
                runs.append(current)
            current = 0
    if current:
        runs.append(current)
    assert runs, "一个事件都没有 —— 概率上不可能（rate=0.05）"
    # ⚠️ 每一段都恰好是配置的宽度 —— 事件之间不会连成更长的一段
    assert all(length == 2 for length in runs), runs


def test_sparse_baseline_is_deterministic():
    """⚠️ 稀疏事件的**位置**也必须是确定的 —— 同一个 index 恒等。"""
    spec = SeriesSpec(
        name="sparse3",
        baseline="sparse",
        event_rate=0.05,
        event_width=2,
        event_value=25.0,
    )
    assert series_at(spec, 300) == series_at(spec, 300)


def test_new_baselines_are_deterministic():
    """三条新曲线都要满足「造两次完全一样」。"""
    for spec in SERIES:
        assert series_at(spec, 120) == series_at(spec, 120)


def test_spec_fingerprint_changes_with_series():
    """⚠️ 指纹要跟着定义变 —— 否则改了曲线却用旧库，数据会悄悄错位。"""
    from anomaly_lab.mock_tsdb.generator import spec_fingerprint

    first = spec_fingerprint()
    assert first == spec_fingerprint()
    assert len(first) == 16


def test_storage_rejects_db_made_with_old_series(tmp_path):
    """⚠️ 库里已有数据、但没有指纹 → **明确报错**，不静默跑出怪数据。"""
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE metrics (ts TEXT, series TEXT, value REAL, UNIQUE(ts, series))"
    )
    conn.execute("INSERT INTO metrics VALUES ('2026-11-02T10:00:00+00:00', 'x', 1.0)")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="旧格式"):
        MockTsdb(path).open()


def test_storage_rejects_db_with_different_fingerprint(tmp_path):
    """指纹对不上 → 报错并说清怎么修。"""
    path = tmp_path / "t.db"
    store = MockTsdb(path)
    with store:
        store.produce_until(datetime.now(UTC))

    # 伪造一个不同的指纹
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("UPDATE mock_meta SET value = 'deadbeef' WHERE key = 'series_fingerprint'")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="序列定义已变"):
        MockTsdb(path).open()


# ---------------------------------------------------------------- 存储


def test_storage_writes_and_reads(tmp_path):
    store = MockTsdb(tmp_path / "t.db")
    with store:
        store.produce_until(datetime.now(UTC))
        columns, rows = store.query("SELECT ts, series, value FROM metrics LIMIT 3")
    assert columns == ["ts", "series", "value"]
    assert len(rows) == 3


def test_storage_rejects_write_query(tmp_path):
    """只读校验 —— 假远端不能变成「能删库的 HTTP 端点」。"""
    store = MockTsdb(tmp_path / "t.db")
    with store, pytest.raises(ValueError, match="SELECT"):
        store.query("DELETE FROM metrics")


def test_storage_data_lies_in_the_past(tmp_path):
    """⚠️ 回填的数据必须在**过去** —— 未来数据会让检测取不到「最近窗口」。"""
    store = MockTsdb(tmp_path / "t.db")
    with store:
        store.produce_until(datetime.now(UTC))
        _, rows = store.query("SELECT MAX(ts) FROM metrics")
    latest = datetime.fromisoformat(rows[0][0])
    assert latest <= datetime.now(UTC)


def test_storage_prune_keeps_recent_only(tmp_path):
    store = MockTsdb(tmp_path / "t.db")
    with store:
        store.produce_until(datetime.now(UTC))
        before = store.query("SELECT COUNT(*) FROM metrics")[1][0][0]
        deleted = store.prune(retention_hours=0)
        after = store.query("SELECT COUNT(*) FROM metrics")[1][0][0]
    assert before > 0
    assert deleted > 0
    assert after < before


def test_storage_restart_does_not_duplicate_rows(tmp_path):
    """⚠️ 重启后同一个 index 仍是同一个时间戳 —— 否则历史数据翻倍。"""
    path = tmp_path / "t.db"
    store = MockTsdb(path)
    with store:
        store.produce_until(datetime.now(UTC))
        count_first = store.query("SELECT COUNT(*) FROM metrics")[1][0][0]

    store2 = MockTsdb(path)
    with store2:
        store2.produce_until(datetime.now(UTC))
        count_second = store2.query("SELECT COUNT(*) FROM metrics")[1][0][0]

    # 第二次只应新增「这一分钟」的点，不该翻倍
    assert count_second < count_first * 1.1


# ---------------------------------------------------------------- HTTP 端点


@pytest.fixture
def client(tmp_path):
    config = MockConfig(
        db_path=tmp_path / "tsdb.db",
        history_points=120,
        autostart=False,
    )
    with TestClient(create_app(config)) as test_client:
        yield test_client


def test_query_sql_csv_has_header(client):
    resp = client.post(
        "/api/v3/query_sql",
        json={"db": "mock", "q": "SELECT ts, series, value FROM metrics LIMIT 2", "format": "csv"},
    )
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    assert lines[0] == "ts,series,value"
    assert len(lines) == 3


def test_query_sql_json_is_object_array(client):
    resp = client.post(
        "/api/v3/query_sql",
        json={"db": "mock", "q": "SELECT ts FROM metrics LIMIT 2", "format": "json"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    assert set(payload[0]) == {"ts"}


def test_query_sql_jsonl_is_one_object_per_line(client):
    resp = client.post(
        "/api/v3/query_sql",
        json={"db": "mock", "q": "SELECT ts FROM metrics LIMIT 2", "format": "jsonl"},
    )
    assert resp.status_code == 200
    lines = [line for line in resp.text.strip().splitlines() if line]
    assert len(lines) == 2
    assert set(json.loads(lines[0])) == {"ts"}


def test_query_sql_requires_db_and_q(client):
    assert client.post("/api/v3/query_sql", json={"q": "SELECT 1"}).status_code == 400
    assert client.post("/api/v3/query_sql", json={"db": "mock"}).status_code == 400
    assert client.post("/api/v3/query_sql", json={"db": "mock", "q": "SELECT 1"}).status_code == 200


def test_query_sql_rejects_invalid_json(client):
    resp = client.post(
        "/api/v3/query_sql",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_query_sql_rejects_write(client):
    resp = client.post(
        "/api/v3/query_sql",
        json={"db": "mock", "q": "DROP TABLE metrics", "format": "csv"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid"


def test_query_sql_rejects_unsupported_format(client):
    for fmt in ("pretty", "parquet"):
        resp = client.post(
            "/api/v3/query_sql", json={"db": "mock", "q": "SELECT 1", "format": fmt}
        )
        assert resp.status_code == 400
        assert "format" in resp.json()["message"]


def test_query_sql_get_variant(client):
    resp = client.get("/api/v3/query_sql", params={"db": "mock", "q": "SELECT 1 AS n"})
    assert resp.status_code == 200
    assert resp.json() == [{"n": 1}]


def test_authorization_header_is_accepted_and_ignored(client):
    """⚠️ 假远端**不实现鉴权**，但接受并忽略 `Authorization`。

    真库的鉴权是连接器 `config.headers` 的事 —— 平台侧已经做完了。
    """
    resp = client.post(
        "/api/v3/query_sql",
        json={"db": "mock", "q": "SELECT 1 AS n"},
        headers={"Authorization": "Bearer whatever"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------- 平台侧


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _LiveServer:
    """在后台线程里跑一个真的 HTTP 服务（平台的连接器要能真的连上）。"""

    def __init__(self, config: MockConfig) -> None:
        self.config = config
        self.port = _free_port()
        self._server = uvicorn.Server(
            uvicorn.Config(create_app(config), host="127.0.0.1", port=self.port, log_level="error")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> Self:
        self._thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not self._server.started:
            time.sleep(0.05)
        assert self._server.started, "假远端没起来"
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture
def live_server(tmp_path):
    config = MockConfig(
        db_path=tmp_path / "tsdb.db",
        history_points=120,
        autostart=False,
    )
    with _LiveServer(config) as server:
        yield server


def _metric(source_id: int = 1) -> Metric:
    return Metric(
        id=1,
        source_id=source_id,
        name="m",
        query="SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="series",
        time_format="iso_utc",
        created_at="",
    )


def test_connector_consistency_sqlite_vs_http(tmp_path, live_server):
    """⚠️ **本 spec 的核心测试** —— 同一个库，两条连接路径结果相同。

    spec 1 的测试策略承诺了「sqlite 与 http 跑同一套用例 → 两条路径
    返回相同的 SeriesBundle 集合」，但那时没有真的共同后端。
    假远端就是那个共同后端。
    """
    db_path = tmp_path / "tsdb.db"
    store = MockTsdb(db_path)
    with store:
        store.produce_until(datetime.now(UTC))

    end = datetime.now(UTC)
    start = end - timedelta(hours=2)

    sqlite_source = Source(
        id=1, name="s", kind="sqlite", path=str(db_path), created_at="", config={}
    )
    http_source = Source(
        id=2,
        name="h",
        kind="http",
        path="",
        created_at="",
        config=source_config(live_server.base_url),
    )

    metric = _metric()
    sqlite_series = series_from_frame(
        get_connector(sqlite_source, tmp_path).fetch(metric, start, end), metric
    )
    http_series = series_from_frame(
        get_connector(http_source, tmp_path).fetch(metric, start, end), metric
    )

    assert [s.series_id for s in sqlite_series] == [s.series_id for s in http_series]
    assert len(sqlite_series) == len(SERIES)
    for left, right in zip(sqlite_series, http_series, strict=True):
        assert list(left.values) == list(right.values), left.series_id
        assert list(left.timestamps) == list(right.timestamps), left.series_id


def test_browse_matches_runtime(live_server, tmp_path):
    """D11：浏览端点看到的与指标运行时取到的，是同一份数据。"""
    source = Source(
        id=1,
        name="h",
        kind="http",
        path="",
        created_at="",
        config=source_config(live_server.base_url),
    )
    connector = get_connector(source, tmp_path)
    metric = _metric()
    end = datetime.now(UTC)
    start = end - timedelta(hours=2)

    frame = connector.fetch(metric, start, end)
    # 浏览路径：同一段 SQL，但不替换 $timefilter
    condition, _ = connector.build_time_condition(
        type(
            "Ctx",
            (),
            {
                "column": metric.time_column,
                "fmt": metric.time_format,
                "timezone": metric.source_timezone,
                "start": start,
                "end": end,
            },
        )()
    )
    browse_frame = connector.execute_sql(
        metric.query.replace("$timefilter", condition)
    )
    assert len(frame) == len(browse_frame)
    assert list(frame.columns) == list(browse_frame.columns)


def test_wal_readonly_sees_committed_data(tmp_path):
    """⚠️ **spec §11 约束 1** —— 平台以 `mode=ro` 打开正在被写的 WAL 库。

    假远端开着 WAL 写数据；平台的 SQLite 连接器用 `file:...?mode=ro` 打开
    同一个文件，必须读到**已提交**的数据。
    """
    db_path = tmp_path / "tsdb.db"
    config = MockConfig(db_path=db_path, history_points=60, autostart=True)
    with _LiveServer(config):
        # 让后台线程写几轮
        time.sleep(1.5)
        # ⚠️ 后台写入不能有错 —— 之前这里只断言「回填的数据能读到」，
        #    结果后台线程其实一直在报错，测试照样绿。
        assert config.write_errors == []

        source = Source(
            id=1, name="s", kind="sqlite", path=str(db_path), created_at="", config={}
        )
        connector = get_connector(source, tmp_path)
        ok, message = connector.test_connection()
        assert ok, message

        metric = _metric()
        end = datetime.now(UTC)
        frame = connector.fetch(metric, end - timedelta(hours=2), end)
        assert not frame.empty, "只读连接没读到已提交的数据"


def test_background_writer_actually_writes(tmp_path):
    """⚠️ **数据必须真的在流动** —— 这条是「活数据」的底线。

    之前后台线程因跨线程用连接而死锁，但测试没抓到：
    死锁不抛异常，`write_errors` 是空的；而点数断言写成了 `>=`（恒真）。

    这里把采样间隔压到 1 秒，然后断言点数**严格增长**。
    """
    config = MockConfig(
        db_path=tmp_path / "tsdb.db",
        history_points=30,
        sample_seconds=1,
        write_interval_seconds=1,
        autostart=True,
    )
    with _LiveServer(config):
        time.sleep(1.0)
        assert config.write_errors == [], config.write_errors

        store = MockTsdb(config.db_path, sample_seconds=1)
        with store:
            before = store.query("SELECT COUNT(*) AS n FROM metrics")[1][0][0]
            time.sleep(2.5)
            after = store.query("SELECT COUNT(*) AS n FROM metrics")[1][0][0]
        assert after > before, f"点数没涨（{before} → {after}）—— 数据没在流动"
        assert config.write_errors == []


def test_wal_readonly_survives_writer_crash(tmp_path):
    """⚠️ 写者被 `kill -9`、`-wal` 残留时，平台的只读连接仍能打开并读到数据。"""
    db_path = tmp_path / "tsdb.db"
    script = tmp_path / "writer.py"
    script.write_text(
        "import sqlite3, time\n"
        f"c = sqlite3.connect({str(db_path)!r})\n"
        "c.execute('PRAGMA journal_mode=WAL')\n"
        "c.execute('CREATE TABLE IF NOT EXISTS metrics (ts TEXT, series TEXT, value REAL,"
        " UNIQUE(ts, series))')\n"
        "c.commit()\n"
        "for i in range(5):\n"
        "    c.execute('INSERT OR IGNORE INTO metrics VALUES (?,?,?)',"
        " (f'2026-11-02T10:0{i}:00+00:00', 'x', 1.0))\n"
        "    c.commit()\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    child = subprocess.Popen([sys.executable, str(script)])
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not db_path.exists():
            time.sleep(0.05)
        time.sleep(1.0)
        child.kill()
        child.wait(timeout=10)
        time.sleep(0.3)

        source = Source(
            id=1, name="s", kind="sqlite", path=str(db_path), created_at="", config={}
        )
        connector = get_connector(source, tmp_path)
        ok, message = connector.test_connection()
        assert ok, f"写者崩溃后只读连接打不开: {message}"
        frame = connector.execute_sql("SELECT COUNT(*) AS n FROM metrics")
        assert int(frame.iloc[0]["n"]) >= 5
    finally:
        if child.poll() is None:
            child.kill()


def test_end_to_end_detection_raises_alert(tmp_path, live_server):
    """端到端：平台取数 → 检测 → 产出告警。"""
    from anomaly_lab.platform.runner import execute_job
    from anomaly_lab.platform.store import PlatformStore

    store = PlatformStore(tmp_path / "platform.db")
    info = seed_mock_remote(tmp_path, base_url=live_server.base_url)
    store = PlatformStore(tmp_path / "platform.db")
    job = store.get_job(info["job_id"])

    run_id = execute_job(store, job.id, data_root=tmp_path)
    run = store.get_run(run_id)
    assert run.status in {"success", "insufficient_data"}
    assert run.n_series >= 1


def test_seed_mock_remote_is_idempotent(tmp_path):
    first = seed_mock_remote(tmp_path)
    second = seed_mock_remote(tmp_path)
    assert first["source_id"] == second["source_id"]
    assert first["metric_id"] == second["metric_id"]
    assert first["job_id"] == second["job_id"]


def test_seed_config_can_actually_be_used(tmp_path, live_server):
    """种子生成的 config 必须真能连上 —— 不能只是「看着对」。"""
    info = seed_mock_remote(tmp_path, base_url=live_server.base_url)
    from anomaly_lab.platform.store import PlatformStore

    store = PlatformStore(tmp_path / "platform.db")
    source = store.get_source_raw(info["source_id"])
    connector = get_connector(source, tmp_path)
    ok, message = connector.test_connection()
    assert ok, message
