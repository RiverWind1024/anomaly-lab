from datetime import UTC, datetime, timedelta

from anomaly_lab.platform.scheduler import Scheduler
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow


def _job(store, name="job"):
    source = store.add_source(f"src-{name}", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name=f"m-{name}",
        query="SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column=None,
        time_format="iso_utc",
        freq="5min",
    )
    return store.add_job(
        metric_id=metric.id,
        name=name,
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=10,
        interval_seconds=300,
    )


def _recorder(calls):
    def runner(*args, **kwargs):
        calls.append(kwargs)
        return 1

    return runner


def test_tick_runs_due_job_once_and_advances_schedule(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    calls = []
    scheduler = Scheduler(store, tmp_path, runner=_recorder(calls))
    now = utcnow()
    assert scheduler.tick(now=now) == [1]
    assert len(calls) == 1
    assert scheduler.tick(now=now) == []
    assert store.get_job(job.id).next_run_at > to_iso(now)


def test_reconcile_missed_only_runs_once(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    store.set_job_next_run(job.id, to_iso(datetime(2000, 1, 1, tzinfo=UTC)))
    calls = []
    scheduler = Scheduler(store, tmp_path, runner=_recorder(calls))
    scheduler.reconcile(now=utcnow())
    assert scheduler.tick(now=utcnow()) == [1]
    assert scheduler.tick(now=utcnow()) == []
    assert len(calls) == 1


def test_disabled_job_is_skipped(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    store.set_job_enabled(job.id, False)
    calls = []
    scheduler = Scheduler(store, tmp_path, runner=_recorder(calls))
    assert scheduler.tick(now=utcnow()) == []
    assert calls == []


def test_failed_run_still_advances_schedule(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)

    def failing_runner(*args, **kwargs):
        raise RuntimeError("boom")

    scheduler = Scheduler(store, tmp_path, runner=failing_runner)
    now = utcnow()
    assert scheduler.tick(now=now) == []
    assert store.get_job(job.id).next_run_at > to_iso(now)


def test_start_and_stop_are_idempotent(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    calls = []
    scheduler = Scheduler(store, tmp_path, poll_seconds=0.05, runner=_recorder(calls))
    scheduler.start()
    scheduler.start()
    scheduler.stop()
    scheduler.stop()
    assert scheduler.is_running is False


# ---------- 自动清理 ----------


def _expired_run(store, job_id, *, age_days: float):
    """造一次「已经超出保留期」的运行记录。"""
    run = store.create_run(job_id)
    store.finish_run(run.id, "success", n_series=1, n_alerts=0)
    with store._conn() as conn:
        conn.execute(
            "UPDATE runs SET started_at = ? WHERE id = ?",
            (to_iso(utcnow() - timedelta(days=age_days)), run.id),
        )
    return run.id


def test_tick_prunes_expired_runs(tmp_path, monkeypatch):
    """⚠️ 调度器**自动**清理 —— 「不断产生的数据会自动清理」是这个需求的核心。

    不自动清的话，得手动跑 `prune` 才有效果 —— 那不叫「自动」。

    ⚠️ 超窗的那条**不能是最新的一次** —— 最新的一次永远保留
       （告警中心只读它）。所以先造老的、再造一条新的。
    """
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "180")
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    expired = _expired_run(store, job.id, age_days=200)
    _expired_run(store, job.id, age_days=0)

    scheduler = Scheduler(store, tmp_path, runner=_recorder([]))
    scheduler.tick(now=utcnow())

    assert expired not in {run.id for run in store.all_runs()}


def test_prune_is_throttled(tmp_path, monkeypatch):
    """⚠️ 清理要**节流** —— tick 默认每 2 秒一次，每次都全表扫描太浪费。"""
    from anomaly_lab.platform import retention

    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "180")
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    _expired_run(store, job.id, age_days=200)
    _expired_run(store, job.id, age_days=0)

    calls: list[int] = []
    real_prune = retention.prune

    def counting_prune(*args, **kwargs):
        calls.append(1)
        return real_prune(*args, **kwargs)

    monkeypatch.setattr("anomaly_lab.platform.retention.prune", counting_prune)

    scheduler = Scheduler(store, tmp_path, runner=_recorder([]), prune_every_seconds=3600)
    now = utcnow()
    scheduler.tick(now=now)
    scheduler.tick(now=now + timedelta(seconds=10))
    assert len(calls) == 1, "还没到清理间隔，不该再清"

    scheduler.tick(now=now + timedelta(seconds=3700))
    assert len(calls) == 2, "过了间隔就该再清一次"


def test_prune_can_be_disabled(tmp_path, monkeypatch):
    """`prune_every_seconds <= 0` → 关掉自动清理。"""
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "180")
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    _expired_run(store, job.id, age_days=200)
    _expired_run(store, job.id, age_days=0)

    scheduler = Scheduler(store, tmp_path, runner=_recorder([]), prune_every_seconds=0)
    scheduler.tick(now=utcnow())
    assert len(store.all_runs()) == 2, "关了自动清理就不该动"


def test_prune_failure_does_not_kill_the_scheduler(tmp_path, monkeypatch):
    """⚠️ 清理失败**不能**把调度线程带走 —— 否则整个平台再也不会执行任务了。"""
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "180")
    store = PlatformStore(tmp_path / "platform.db")
    _job(store)

    def boom(*args, **kwargs):
        raise RuntimeError("清理炸了")

    monkeypatch.setattr("anomaly_lab.platform.retention.prune", boom)
    scheduler = Scheduler(store, tmp_path, runner=_recorder([]))
    scheduler.tick(now=utcnow())  # 不该抛
    assert scheduler.tick(now=utcnow()) == []
