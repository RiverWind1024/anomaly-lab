"""试跑（test-run）：真实执行，但不落库、不落盘。

⚠️ 核心保证：**试跑走的是与真实执行同一段代码**。
   所以「试跑看到的告警」= 「真跑一次会得到的告警」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import utcnow


def _make_store(tmp_path: Path) -> tuple[PlatformStore, int]:
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="cpu",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


def _write_series(tmp_path: Path, values: list[float]) -> None:
    """造一个 SQLite 源库，里面有一条序列（5 分钟一个点）。

    ⚠️ 时间戳**从旧到新**排列 —— 与 `values` 的顺序一一对应。
    """
    import sqlite3
    from datetime import timedelta

    from anomaly_lab.platform.timeutil import to_iso

    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (ts TEXT, value REAL)")
    end = utcnow().replace(second=0, microsecond=0)
    n = len(values)
    rows = [
        (to_iso(end - timedelta(minutes=5 * (n - 1 - index))), float(value))
        for index, value in enumerate(values)
    ]
    conn.executemany("INSERT INTO t VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


#: 一条「有噪声的基线 + 一个尖峰」的序列。
#:
#: ⚠️ **必须有噪声** —— 全是常数的话 IQR 的 q1==q3、尺度为 0，
#:    分数会全变成 0，尖峰根本测不出来（那不是 bug，是数学事实）。
#: ⚠️ 也必须有 **≥ 10 个点** —— 少于 `MIN_VALID_POINTS` 会判「数据不足」。
SPIKY = [10.0, 11.0, 9.5, 10.5, 10.0, 11.5, 9.0, 10.2, 10.8, 9.8, 10.1, 11.0, 9.2, 10.4, 10.0, 9.9, 10.6, 10.3, 9.7, 10.9, 10.0, 11.2, 9.4, 10.1, 10.5, 9.6, 10.7, 10.2, 9.9, 10.4, 10.0, 9.8, 10.6, 10.1, 9.5, 10.3, 10.8, 9.3, 10.0, 11.1, 9.7]
SPIKE_AT = 20


def spiky_values() -> list[float]:
    """带尖峰的序列 —— 尖峰在 `SPIKE_AT` 位置。"""
    values = list(SPIKY)
    values[SPIKE_AT] = 80.0
    return values


# ---------- 落库语义 ----------


def test_test_run_does_not_create_run_row(tmp_path):
    """⚠️ 试跑**不落库** —— `runs` 表一行都不该多。"""
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, spiky_values())

    before = len(store.all_runs())
    result = runner_module.execute_job_test(store, job_id, data_root=tmp_path)

    assert len(store.all_runs()) == before, "试跑不该写 runs 表"
    assert result.n_alerts >= 1, "尖峰应该被判为告警"


def test_test_run_does_not_write_result_files(tmp_path):
    """⚠️ 试跑**不落盘** —— 结果目录里不能多出文件。"""
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, spiky_values())

    runs_root = tmp_path / "cache" / "platform" / "runs"
    before = set(runs_root.iterdir()) if runs_root.exists() else set()

    runner_module.execute_job_test(store, job_id, data_root=tmp_path)

    after = set(runs_root.iterdir()) if runs_root.exists() else set()
    assert after == before, "试跑不该写结果文件"


def test_test_run_does_not_touch_inflight_registry(tmp_path):
    """⚠️ 试跑**不占用** `_INFLIGHT` —— 否则会挡住真正的定时执行。

    这是个真会咬人的坑：试跑把 job 登记成「正在执行」，
    调度器下一次 tick 就会跳过这个任务，试一下反而把任务停了。
    """
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, spiky_values())

    runner_module.execute_job_test(store, job_id, data_root=tmp_path)

    assert job_id not in runner_module._INFLIGHT
    assert not runner_module.is_running(job_id)


# ---------- 与真实执行一致 ----------


def test_test_run_matches_real_run_alerts(tmp_path):
    """⚠️ **核心保证**：试跑的告警数与真实执行完全一致。

    ⚠️ 场景要挑对：数据里必须有**真的异常点**，
       否则两边都是 0，这个断言就是空的。
    """
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, spiky_values())

    test_result = runner_module.execute_job_test(store, job_id, data_root=tmp_path)
    run_id = runner_module.execute_job(store, job_id, data_root=tmp_path)
    run = store.get_run(run_id)
    index = runner_module.read_run_index(tmp_path, run_id)

    assert test_result.n_alerts == run.n_alerts > 0, "试跑与真实执行的告警数必须一致"
    assert test_result.n_p0 == sum(
        int(item.get("n_p0", 0)) for item in index["series"]
    )


def test_test_run_matches_real_run_scores(tmp_path):
    """⚠️ 连**分数**都要一致 —— 不只是告警数。

    告警数一致可能只是巧合（阈值两侧的点数相同）；
    分数逐点一致才是真的同一段代码。
    """
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, spiky_values())

    test_result = runner_module.execute_job_test(store, job_id, data_root=tmp_path)
    test_scores = test_result.outcomes[0].arrays["scores"]

    run_id = runner_module.execute_job(store, job_id, data_root=tmp_path)
    index = runner_module.read_run_index(tmp_path, run_id)
    import numpy as np

    payload = np.load(
        tmp_path / "cache" / "platform" / "runs" / str(run_id) / index["series"][0]["file"],
        allow_pickle=False,
    )
    assert list(test_scores) == list(payload["scores"])


def test_test_run_uses_same_detector_as_real_run(tmp_path):
    """算法选择也要一致 —— auto 的形态推断在两条路上得给同一个答案。"""
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, spiky_values())

    test_result = runner_module.execute_job_test(store, job_id, data_root=tmp_path)
    test_detector = str(test_result.outcomes[0].arrays["detector"])

    run_id = runner_module.execute_job(store, job_id, data_root=tmp_path)
    index = runner_module.read_run_index(tmp_path, run_id)
    assert test_detector == index["series"][0]["detector"]


# ---------- 边界情况 ----------


def test_test_run_reports_insufficient_data(tmp_path):
    """点数不够时要**明说**，绝不能返回「一切正常」。"""
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, [1.0, 1.1])

    result = runner_module.execute_job_test(store, job_id, data_root=tmp_path)
    assert result.n_insufficient >= 1
    assert result.n_alerts == 0


def test_test_run_unknown_job_raises(tmp_path):
    store, _job_id = _make_store(tmp_path)
    with pytest.raises(ValueError):
        runner_module.execute_job_test(store, 9999, data_root=tmp_path)


def test_test_run_on_empty_source(tmp_path):
    """没有数据时不能崩。"""
    store, job_id = _make_store(tmp_path)
    _write_series(tmp_path, [])
    result = runner_module.execute_job_test(store, job_id, data_root=tmp_path)
    assert result.n_alerts == 0
