from datetime import UTC, datetime, timedelta

import pytest

from anomaly_lab.platform.store import PlatformStore
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
        freq="5min",
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
            freq="5min",
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
        window_points=500,
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
            window_points=500,
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
            window_points=500,
            interval_seconds=300,
        )


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
        window_points=500,
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
        window_points=500,
        interval_seconds=300,
    )
    store.set_job_enabled(job.id, False)
    assert store.due_jobs(to_iso(utcnow())) == []


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
        window_points=500,
        interval_seconds=300,
    )
    run = store.create_run(job.id)
    assert run.status == "running"
    store.finish_run(run.id, "success", n_series=2, n_alerts=3)
    latest = store.latest_run(job.id)
    assert latest.status == "success"
    assert latest.n_alerts == 3
    assert store.list_runs(job.id)[0].id == run.id
