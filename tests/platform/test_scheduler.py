from datetime import UTC, datetime

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
        time_format="iso",
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
