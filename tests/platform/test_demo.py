import sqlite3

from anomaly_lab.cli import main
from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore


def test_platform_demo_command_creates_source_metric_job(tmp_path, capsys):
    rc = main(["platform-demo", "--data", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "platform" / "source.db").exists()
    store = PlatformStore(tmp_path / "platform.db")
    assert len(store.list_sources()) == 1
    assert len(store.list_metrics()) == 1
    assert len(store.list_jobs()) == 1
    assert "platform" in capsys.readouterr().out


def test_platform_demo_is_idempotent(tmp_path):
    assert main(["platform-demo", "--data", str(tmp_path)]) == 0
    assert main(["platform-demo", "--data", str(tmp_path)]) == 0
    store = PlatformStore(tmp_path / "platform.db")
    assert len(store.list_sources()) == 1
    assert len(store.list_jobs()) == 1


def test_platform_demo_job_runs_successfully(tmp_path):
    assert main(["platform-demo", "--data", str(tmp_path)]) == 0
    store = PlatformStore(tmp_path / "platform.db")
    job = store.list_jobs()[0]
    run_id = execute_job(store, job.id, data_root=tmp_path)
    run = store.get_run(run_id)
    assert run.status == "success"
    assert run.n_series == 2
    assert run.n_alerts > 0


def test_platform_demo_source_db_has_recent_points(tmp_path):
    assert main(["platform-demo", "--data", str(tmp_path)]) == 0
    conn = sqlite3.connect(tmp_path / "platform" / "source.db")
    rows = conn.execute("SELECT ts FROM metrics ORDER BY ts").fetchall()
    conn.close()
    assert len(rows) > 100
    assert rows[-1][0].startswith("202")
