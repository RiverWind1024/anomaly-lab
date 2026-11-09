import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from anomaly_lab.platform.store import (
    REDACTED,
    PlatformStore,
    _is_secret,
    _redact_config,
    _redact_url,
)
from anomaly_lab.platform.timeutil import to_iso, utcnow


def _source(store, name="local"):
    return store.add_source(name, "platform/source.db")


def _metric(store, source_id):
    return store.add_metric(
        source_id=source_id,
        name="cpu",
        query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="host",
        time_format="iso_utc",
    )


def test_add_list_and_get_source(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    assert source.id == 1
    assert store.get_source(source.id).name == "local"
    assert store.list_sources()[0].path == "platform/source.db"


def test_duplicate_source_name_is_rejected(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source("local", "a.db")
    with pytest.raises(ValueError, match="已存在"):
        store.add_source("local", "b.db")


def test_add_metric_rejects_query_without_timefilter(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    with pytest.raises(ValueError, match="timefilter"):
        store.add_metric(
            source_id=source.id,
            name="cpu",
            query="SELECT ts, value FROM metrics",
            time_column="ts",
            value_column="value",
            group_column=None,
            time_format="iso_utc",
        )


def test_add_job_defaults_schedule_to_now(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    before = utcnow()
    job = store.add_job(
        metric_id=metric.id,
        name="cpu-job",
        detector="seasonal",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_seconds=500 * 300,
        interval_seconds=300,
    )
    assert job.enabled is True
    assert job.next_run_at is not None
    assert datetime.fromisoformat(job.next_run_at) >= before - timedelta(seconds=1)


def test_job_rejects_critical_not_above_alert(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    with pytest.raises(ValueError, match="critical_threshold"):
        store.add_job(
            metric_id=metric.id,
            name="bad",
            detector="seasonal",
            alert_threshold=4.0,
            critical_threshold=4.0,
            window_seconds=500 * 300,
            interval_seconds=300,
        )


def test_job_rejects_unknown_detector(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    with pytest.raises(ValueError, match="检测器"):
        store.add_job(
            metric_id=metric.id,
            name="bad-detector",
            detector="nope",
            alert_threshold=2.5,
            critical_threshold=4.0,
            window_seconds=500 * 300,
            interval_seconds=300,
        )


def test_job_detect_points_defaults_to_whole_window(tmp_path):
    """不配置检测点数 = 0 = 检测整个窗口（老任务行为不变）。"""
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    job = store.add_job(
        metric_id=metric.id,
        name="cpu-job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_seconds=60 * 300,
        interval_seconds=60,
    )
    assert job.detect_points == 0
    updated = store.update_job_config(job.id, detect_points=3)
    assert updated.detect_points == 3
    # 改回 0 也要生效
    assert store.update_job_config(job.id, detect_points=0).detect_points == 0


def test_job_detect_points_rejects_negative(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    base = {
        "metric_id": metric.id,
        "name": "cpu-job",
        "detector": "iqr",
        "alert_threshold": 2.5,
        "critical_threshold": 4.0,
        "window_seconds": 3 * 300,
        "interval_seconds": 60,
    }
    # 窗口是时间，实际点数由 SQL 决定 —— 检测点数不再有「不能超过窗口」的上限
    job = store.add_job(**base, detect_points=3)
    with pytest.raises(ValueError, match="detect_points"):
        store.update_job_config(job.id, detect_points=-1)


def test_old_jobs_table_gets_detect_points_column(tmp_path):
    """老库的 jobs 表没有 detect_points —— 迁移后默认 0。"""
    db_path = tmp_path / "platform.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " metric_id INTEGER NOT NULL, name TEXT NOT NULL UNIQUE,"
        " detector TEXT NOT NULL, alert_threshold REAL NOT NULL,"
        " critical_threshold REAL NOT NULL, window_points INTEGER NOT NULL,"
        " interval_seconds INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,"
        " last_run_at TEXT, next_run_at TEXT, created_at TEXT NOT NULL,"
        " alert_rules TEXT NOT NULL DEFAULT '[]',"
        " alert_direction TEXT NOT NULL DEFAULT 'both')"
    )
    conn.execute(
        "INSERT INTO jobs (metric_id, name, detector, alert_threshold,"
        " critical_threshold, window_points, interval_seconds, enabled, created_at,"
        " alert_rules)"
        " VALUES (1, 'old', 'iqr', 2.5, 4.0, 60, 60, 1, '2026-01-01T00:00:00+00:00',"
        " '[{\"level\": \"P1\", \"multiplier\": 2.5},"
        " {\"level\": \"P0\", \"multiplier\": 4.0}]')"
    )
    conn.commit()
    conn.close()

    store = PlatformStore(db_path)
    assert store.get_job(1).detect_points == 0


def test_old_archive_records_table_gets_description_column(tmp_path):
    """归档记录的「说明」是后加的列 —— 老库要能自动补上。"""
    db_path = tmp_path / "platform.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE archive_sets (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE archive_records (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " archive_set_id INTEGER NOT NULL, run_id INTEGER NOT NULL,"
        " series_id TEXT NOT NULL, job_name TEXT NOT NULL DEFAULT '',"
        " metric_name TEXT NOT NULL DEFAULT '', detector TEXT NOT NULL DEFAULT '',"
        " n INTEGER NOT NULL DEFAULT 0, n_valid INTEGER NOT NULL DEFAULT 0,"
        " n_alerts INTEGER NOT NULL DEFAULT 0, n_p0 INTEGER NOT NULL DEFAULT 0,"
        " start_ts TEXT NOT NULL DEFAULT '', end_ts TEXT NOT NULL DEFAULT '',"
        " file TEXT NOT NULL DEFAULT '', decision_json TEXT NOT NULL DEFAULT '',"
        " content_hash TEXT NOT NULL DEFAULT '', archived_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    PlatformStore(db_path)
    check = sqlite3.connect(db_path)
    columns = {row[1] for row in check.execute("PRAGMA table_info(archive_records)")}
    check.close()
    assert "description" in columns


def test_due_jobs_reconcile_and_schedule_update(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="seasonal",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_seconds=500 * 300,
        interval_seconds=300,
    )
    past = to_iso(datetime(2000, 1, 1, tzinfo=UTC))
    store.set_job_next_run(job.id, past)
    assert [item.id for item in store.due_jobs(to_iso(utcnow()))] == [job.id]
    store.reconcile_missed(to_iso(utcnow()))
    due = store.due_jobs(to_iso(utcnow()))
    assert [item.id for item in due] == [job.id]
    assert due[0].next_run_at != past
    store.update_job_schedule(
        job.id, to_iso(utcnow()), to_iso(utcnow() + timedelta(seconds=300))
    )
    assert store.due_jobs(to_iso(utcnow())) == []


def test_disabled_job_is_not_due(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="seasonal",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_seconds=500 * 300,
        interval_seconds=300,
    )
    store.set_job_enabled(job.id, False)
    assert store.due_jobs(to_iso(utcnow())) == []


def test_source_config_roundtrip(tmp_path):
    """config 存 JSON，读出来是 dict。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/query?q={sql}", "format": "csv"},
    )
    source = store.get_source_raw(1)
    assert source.config["url"] == "https://x/query?q={sql}"
    assert source.config["format"] == "csv"


def test_source_config_defaults_to_empty(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    assert source.config == {}


def test_sqlite_source_requires_path(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="数据源路径"):
        store.add_source("local", "", kind="sqlite")


def test_http_source_requires_url(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="url"):
        store.add_source("remote", "", kind="http", config={"format": "csv"})


def test_unknown_kind_rejected(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="不支持的数据源类型"):
        store.add_source("x", "a.db", kind="kafka")


def test_config_is_redacted_in_reads(tmp_path):
    """密钥不能出现在读出来的 source 里。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/query?q={sql}",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    assert "secret-token" not in str(store.get_source(1).config)
    assert "secret-token" not in str(store.list_sources()[0].config)


def test_redacted_url_is_unchanged_when_no_secret(tmp_path):
    """没有密钥参数时，url 不能被重新编码 —— `{sql}` 会被变成 %7Bsql%7D。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/query?q={sql}"},
    )
    assert store.get_source(1).config["url"] == "https://x/query?q={sql}"


def test_update_keeps_original_secret_when_redacted_value_submitted(tmp_path):
    """前端提交脱敏值时，不能把真值覆盖掉。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/query?q={sql}",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    store.update_source(1, config={
        "url": "https://x/query?q={sql}",
        "headers": {"Authorization": "Bearer ••••"},
    })
    assert (
        store.get_source_raw(1).config["headers"]["Authorization"]
        == "Bearer secret-token"
    )


def test_update_without_config_keeps_stored_secret(tmp_path):
    """⚠️ 只改名字不能把密钥冲掉 —— update 必须读**未脱敏**的当前值。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/query?q={sql}",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    store.update_source(1, name="renamed")
    assert (
        store.get_source_raw(1).config["headers"]["Authorization"]
        == "Bearer secret-token"
    )


def test_run_lifecycle(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    source = _source(store)
    metric = _metric(store, source.id)
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="seasonal",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_seconds=500 * 300,
        interval_seconds=300,
    )
    run = store.create_run(job.id)
    assert run.status == "running"
    store.finish_run(run.id, "success", n_series=2, n_alerts=3)
    latest = store.latest_run(job.id)
    assert latest.status == "success"
    assert latest.n_alerts == 3
    assert store.list_runs(job.id)[0].id == run.id


# ---------- config：脱敏与凭据保全 ----------


def test_redact_url_keeps_sql_template_when_masking_token():
    """⚠️ 有密钥参数时也**不能**重新编码整个 query —— `{sql}` 会变成 `%7Bsql%7D`。

    模板一坏，SQL 透传就废了；密钥一坏，真值就永久丢了。
    """
    out = _redact_url("https://ch.internal:8123/?query={sql}&token=abc")
    assert "{sql}" in out
    assert "abc" not in out
    assert out == "https://ch.internal:8123/?query={sql}&token=••••"


@pytest.mark.parametrize(
    "name",
    ["token", "api_key", "access_token", "apikey", "secret_key", "X-API-Key", "password"],
)
def test_redact_url_masks_compound_secret_names(name):
    """⚠️ 必须**子串**匹配 —— `api_key` / `X-API-Key` 用精确相等会漏掉。"""
    assert _is_secret(name)
    assert "LEAKME" not in _redact_url(f"https://x/?{name}=LEAKME")


def test_redact_config_masks_secret_body_keys():
    """body 里的凭据也要脱敏 —— `access_token` 这种复合名不能漏。"""
    out = _redact_config({"body": {"access_token": "LEAKME", "query": "{sql}"}})
    assert "LEAKME" not in str(out)
    assert out["body"]["query"] == "{sql}"


def test_update_with_redacted_config_restores_real_secret(tmp_path):
    """脱敏后的 config 原样提交 → 完全还原成真值。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://ch.internal:8123/?query={sql}&token=SECRET",
            "headers": {"Authorization": "Bearer secret-token"},
        },
    )
    store.update_source(1, config=store.get_source(1).config)
    raw = store.get_source_raw(1).config
    assert raw["url"] == "https://ch.internal:8123/?query={sql}&token=SECRET"
    assert raw["headers"]["Authorization"] == "Bearer secret-token"


def test_update_changing_host_keeps_template_and_secret(tmp_path):
    """⚠️ 用户改一次 host —— 模板与密钥都不能被毁掉。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://ch.internal:8123/?query={sql}&token=SECRET"},
    )
    redacted = store.get_source(1).config
    store.update_source(
        1,
        config={**redacted, "url": redacted["url"].replace("ch.internal", "ch2.internal")},
    )
    raw = store.get_source_raw(1).config
    assert raw["url"] == "https://ch2.internal:8123/?query={sql}&token=SECRET"


def test_update_changing_token_adopts_new_value(tmp_path):
    """改了 token → 新值采纳，旧真值被替换掉。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http", config={"url": "https://ch.internal/?token=OLD"},
    )
    redacted = store.get_source(1).config
    store.update_source(
        1, config={**redacted, "url": redacted["url"].replace(REDACTED, "NEW")}
    )
    assert store.get_source_raw(1).config["url"] == "https://ch.internal/?token=NEW"


def test_update_can_clear_config_of_http_source(tmp_path):
    """显式清空 config（`{}`）—— http 源允许（先建后配）。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source("remote", "", kind="http", config={"url": "https://x/query"})
    store.update_source(1, config={})
    assert store.get_source_raw(1).config == {}


def test_update_can_clear_config_of_sqlite_source(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source("local", "platform/source.db")
    store.update_source(1, config={})
    assert store.get_source_raw(1).config == {}


def test_sqlite_source_config_is_normalized_to_empty(tmp_path):
    """spec §3.2：sqlite 的 config 恒为 {}。"""
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source(
        "local", "platform/source.db", config={"url": "https://x/query"},
    )
    assert source.config == {}
    assert store.get_source_raw(source.id).config == {}


def test_get_source_raw_returns_unredacted_config(tmp_path):
    """`get_source_raw` 是内部入口 —— 必须拿到真值。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http", config={"url": "https://x/query?token=SECRET"},
    )
    assert store.get_source_raw(1).config["url"] == "https://x/query?token=SECRET"
    assert "SECRET" not in str(store.get_source(1).config)


def test_find_source_by_name_returns_redacted_config(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http", config={"url": "https://x/query?token=SECRET"},
    )
    found = store.find_source_by_name("remote")
    assert found is not None
    assert "SECRET" not in str(found.config)


def test_config_roundtrip_keeps_chinese_and_special_chars(tmp_path):
    """⚠️ `ensure_ascii=False` —— 中文与特殊字符要原样存回来。"""
    store = PlatformStore(tmp_path / "platform.db")
    config = {"url": "https://x/query?name=值", "note": "中文 & 特殊字符 = {sql}"}
    store.add_source("remote", "", kind="http", config=config)
    assert store.get_source_raw(1).config == config


def test_old_database_gets_config_column(tmp_path):
    """老库没有 config 列 —— 初始化时要补上，且能读能写。"""
    db_path = tmp_path / "platform.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'sqlite',"
        " path TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sources (name, kind, path, created_at)"
        " VALUES ('old', 'sqlite', 'a.db', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    store = PlatformStore(db_path)
    assert store.get_source_raw(1).config == {}
    store.add_source("new", "b.db")
    assert store.get_source_raw(2).config == {}


def test_switching_kind_to_http_allows_empty_config(tmp_path):
    """⚠️ HTTP 源允许**空 config**（先建后配）—— create 与 update 必须一致。

    之前 POST 允许、PATCH 不允许 —— 同一个源在两条路径上语义不一样。
    """
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source("local", "platform/source.db")
    store.update_source(1, kind="http")
    source = store.get_source_raw(1)
    assert source.kind == "http"
    assert source.config == {}


def test_switching_kind_to_sqlite_requires_path(tmp_path):
    """跨类型切换 —— 必须**同时**提供目标类型的必填项。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http", config={"url": "https://x/query"},
    )
    with pytest.raises(ValueError, match="数据源路径"):
        store.update_source(1, kind="sqlite")


def test_switching_kind_to_http_with_url_is_accepted(tmp_path):
    """跨类型切换 + 同时提供 url → 成功。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source("local", "platform/source.db")
    store.update_source(1, kind="http", config={"url": "https://x/query"})
    source = store.get_source_raw(1)
    assert source.kind == "http"
    assert source.config["url"] == "https://x/query"


def test_headers_with_nonstandard_names_are_redacted(tmp_path):
    """⚠️ header 的值**一律脱敏** —— 不能靠参数名判断。

    `Cookie` / `X-Session-Id` / `Proxy-Authorization` 这些根本猜不出
    名字里有凭据，靠名字判断就会明文泄漏。
    """
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/q?q={sql}",
            "headers": {"Cookie": "sid=abc", "Authorization": "Bearer secret"},
        },
    )
    source = store.get_source(1)
    assert "sid=abc" not in str(source.config)
    assert "secret" not in str(source.config)


def test_update_with_redacted_headers_restores_real_values(tmp_path):
    """脱敏后的 headers 原样提交 → 真值完整还原。

    ⚠️ header 的脱敏形式是 `前缀 ••••`（值里有空格才留前缀）——
       `sid=abc` → `••••`，`Bearer secret` → `Bearer ••••`。
    """
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/q?q={sql}",
            "headers": {"Cookie": "sid=abc", "Authorization": "Bearer secret"},
        },
    )
    store.update_source(
        1,
        config={
            "url": "https://x/q?q={sql}",
            "headers": {"Cookie": "••••", "Authorization": "Bearer ••••"},
        },
    )
    raw = store.get_source_raw(1)
    assert raw.config["headers"]["Cookie"] == "sid=abc"
    assert raw.config["headers"]["Authorization"] == "Bearer secret"


# ---------- 脱敏的漏网之鱼：userinfo 与嵌套 body ----------


def test_redact_url_masks_userinfo():
    """⚠️ netloc 里的 `user:pass@host` 也要脱 —— 只脱 query 会明文泄漏。"""
    out = _redact_url("https://alice:s3cr3tP@ss@ch.internal:8123/?query={sql}&token=abc123")
    assert "s3cr3tP" not in out
    assert "alice" not in out
    # ⚠️ 密码里含 `@` —— host 必须切对（按**最后一个** @ 切）
    assert "ch.internal:8123" in out
    assert out == "https://••••@ch.internal:8123/?query={sql}&token=••••"


def test_redact_url_keeps_at_in_path():
    """⚠️ 路径里的 `@` 不是凭据 —— 不能被当成 userinfo 脱掉。"""
    out = _redact_url("https://ch.internal/query@v2?q={sql}")
    assert out == "https://ch.internal/query@v2?q={sql}"


def test_redact_config_masks_nested_body_secrets():
    """⚠️ 凭据常藏在嵌套结构里 —— 只脱顶层等于没脱。"""
    out = _redact_config(
        {"body": {"db": "demo", "auth": {"password": "nested-secret", "user": "bob"}}}
    )
    assert "nested-secret" not in str(out)
    assert out["body"]["auth"]["password"] == "••••"
    # ⚠️ 非凭据的键保持原样（`{sql}` 模板不能被毁掉）
    assert out["body"]["db"] == "demo"
    assert out["body"]["auth"]["user"] == "bob"


def test_redact_config_masks_nested_body_lists():
    out = _redact_config({"body": {"items": [{"token": "LEAKME"}]}})
    assert "LEAKME" not in str(out)


def test_update_with_redacted_nested_body_restores_real_secret(tmp_path):
    """嵌套的脱敏值原样回传 → 真值完整还原。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/q?q={sql}",
            "body": {"db": "demo", "auth": {"password": "nested-secret", "user": "bob"}},
        },
    )
    redacted = store.get_source(1).config
    assert redacted["body"]["auth"]["password"] == "••••"
    store.update_source(1, config=redacted)
    raw = store.get_source_raw(1).config
    assert raw["body"]["auth"]["password"] == "nested-secret"
    assert raw["body"]["auth"]["user"] == "bob"


def test_update_with_redacted_userinfo_restores_real_credentials(tmp_path):
    """userinfo 的脱敏值原样回传 → 真值完整还原（不能把 `••••@` 存进库）。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://alice:s3cr3t@ch.internal:8123/q?q={sql}"},
    )
    redacted = store.get_source(1).config
    assert redacted["url"] == "https://••••@ch.internal:8123/q?q={sql}"
    store.update_source(1, config=redacted)
    assert store.get_source_raw(1).config["url"] == (
        "https://alice:s3cr3t@ch.internal:8123/q?q={sql}"
    )


def test_update_changing_host_keeps_userinfo(tmp_path):
    """⚠️ 改 host 不能把 userinfo 里的凭据丢掉。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://alice:s3cr3t@ch.internal:8123/q?q={sql}"},
    )
    redacted = store.get_source(1).config
    store.update_source(
        1, config={**redacted, "url": redacted["url"].replace("ch.internal", "ch2.internal")}
    )
    assert store.get_source_raw(1).config["url"] == (
        "https://alice:s3cr3t@ch2.internal:8123/q?q={sql}"
    )


# ---------- 改名后的哨兵值不能当成真值存下来 ----------


def test_update_with_renamed_body_secret_is_rejected(tmp_path):
    """⚠️ 用户把 body 里的 `token` 改名成 `access_token` —— 表单显示的是 `••••`。

    存下去远端就收到字面量 `••••`，源直接坏掉 —— 必须报错让用户重新输入。
    """
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/q?q={sql}", "body": {"token": "SECRET"}},
    )
    redacted = store.get_source(1).config
    assert redacted["body"]["token"] == "••••"
    with pytest.raises(ValueError, match="脱敏值"):
        store.update_source(
            1, config={**redacted, "body": {"access_token": redacted["body"]["token"]}}
        )
    # ⚠️ 拒绝之后不能把哨兵值写进库
    assert store.get_source_raw(1).config["body"]["token"] == "SECRET"


def test_update_with_renamed_url_secret_is_rejected(tmp_path):
    """url 里的凭据改名同理 —— 认不出对应旧 key 就报错。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/q?q={sql}&token=SECRET"},
    )
    redacted = store.get_source(1).config
    with pytest.raises(ValueError, match="脱敏值"):
        store.update_source(
            1,
            config={**redacted, "url": redacted["url"].replace("token=", "access_token=")},
        )
    assert "token=SECRET" in store.get_source_raw(1).config["url"]


def test_update_with_renamed_header_is_rejected(tmp_path):
    """header 改名同理 —— header 的脱敏形式是 `前缀 ••••`。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/q?q={sql}", "headers": {"Authorization": "Bearer SECRET"}},
    )
    redacted = store.get_source(1).config
    assert redacted["headers"]["Authorization"] == "Bearer ••••"
    with pytest.raises(ValueError, match="脱敏值"):
        store.update_source(
            1,
            config={**redacted, "headers": {"X-Authorization": "Bearer ••••"}},
        )


def test_update_with_non_secret_value_containing_sentinel_is_allowed(tmp_path):
    """⚠️ 别误伤 —— 非凭据参数里的 `••••` 不是「改名后的凭据」。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={"url": "https://x/q?q={sql}", "body": {"q": "SELECT 1"}},
    )
    redacted = store.get_source(1).config
    store.update_source(
        1, config={**redacted, "body": {"q": "SELECT '••••' FROM t"}}
    )
    assert store.get_source_raw(1).config["body"]["q"] == "SELECT '••••' FROM t"


# ---------- headers / body 必须是对象 ----------


def test_http_config_rejects_non_dict_headers(tmp_path):
    """⚠️ headers 传字符串 → 脱敏整段跳过（明文泄漏）+ 取数时 `.items()` 炸。"""
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="headers"):
        store.add_source(
            "remote", "", kind="http",
            config={"url": "https://x/q?q={sql}", "headers": "Authorization: Bearer SUPERSECRET"},
        )


def test_http_config_rejects_non_dict_body(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    with pytest.raises(ValueError, match="body"):
        store.add_source(
            "remote", "", kind="http",
            config={"url": "https://x/q?q={sql}", "body": "q=SELECT 1"},
        )


def test_redact_config_masks_non_dict_headers_and_body():
    """⚠️ 历史脏数据（非对象的 headers / body）也不能明文漏出去。"""
    out = _redact_config(
        {
            "headers": "Authorization: Bearer SUPERSECRET",
            "body": "password=SUPERSECRET",
        }
    )
    assert "SUPERSECRET" not in str(out)


def test_nested_credential_in_top_level_config_key_is_redacted(tmp_path):
    """⚠️ 凭据可以藏在**任意**顶层键的嵌套结构里 —— 只脱 headers/body/url 等于没脱。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/q?q={sql}",
            "auth": {"password": "s3cr3t", "user": "bob"},
        },
    )
    source = store.get_source(1)
    assert "s3cr3t" not in str(source.config)
    assert source.config["auth"]["password"] == "••••"
    assert source.config["auth"]["user"] == "bob"


def test_nested_credential_round_trips_through_update(tmp_path):
    """脱敏后原样回传 → 真值还原（嵌套结构也要还原）。"""
    store = PlatformStore(tmp_path / "platform.db")
    store.add_source(
        "remote", "", kind="http",
        config={
            "url": "https://x/q?q={sql}",
            "auth": {"password": "s3cr3t"},
        },
    )
    redacted = store.get_source(1).config
    store.update_source(1, config=redacted)
    assert store.get_source_raw(1).config["auth"]["password"] == "s3cr3t"
