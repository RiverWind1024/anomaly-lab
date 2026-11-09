"""数据保留与清理策略。

保留期只有**一个维度：时间**。这里守的是两条**功能性**约束 ——
破坏任何一条都不是「清理过头」，是**功能坏了**：

1. 最新一次运行永远保留（告警中心只读最新 run）；
2. 正在执行的运行不删（删了它的目录，runner 写文件会失败）。

以及一条**人工数据**约束：人工反馈不删，只把引用断开。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from anomaly_lab.platform.retention import (
    DEFAULT_RETENTION_DAYS,
    RetentionPolicy,
    prune,
    select_prunable_runs,
    storage_usage,
)
from anomaly_lab.platform.runner import run_dir
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow

# ---------- 夹具 ----------


def _make_store(tmp_path: Path) -> tuple[PlatformStore, int]:
    """一个含数据源 / 指标 / 任务的 store。"""
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
        window_seconds=60 * 300,
        interval_seconds=300,
    )
    return store, job.id


def _add_run(
    store: PlatformStore,
    job_id: int,
    *,
    age_days: float = 0.0,
    with_dir: bool = False,
    data_root: Path | None = None,
    size_bytes: int = 0,
) -> int:
    """造一次运行记录（可指定「多少天之前」），可选带上它的结果目录。"""
    run = store.create_run(job_id)
    store.finish_run(run.id, "success", n_series=1, n_alerts=0)
    started = utcnow() - timedelta(days=age_days)
    with store._conn() as conn:
        conn.execute(
            "UPDATE runs SET started_at = ? WHERE id = ?", (to_iso(started), run.id)
        )
    if with_dir and data_root is not None:
        target = run_dir(data_root, run.id)
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.json").write_text("{}", encoding="utf-8")
        (target / "a.npz").write_bytes(b"x" * size_bytes)
    return run.id


# ---------- 纯函数：保留期 ----------


def test_expired_runs_are_prunable(tmp_path):
    """超过保留期的待删。"""
    store, job_id = _make_store(tmp_path)
    old = _add_run(store, job_id, age_days=200)
    fresh = _add_run(store, job_id, age_days=10)
    runs = store.all_runs()  # id 倒序

    prunable = select_prunable_runs(
        runs, RetentionPolicy(retention_days=180), now=utcnow()
    )
    assert prunable == [old]
    assert fresh not in prunable


def test_runs_within_retention_are_kept(tmp_path):
    """保留期内的**一条都不删** —— 没有「条数上限」那一说。"""
    store, job_id = _make_store(tmp_path)
    for _ in range(50):
        _add_run(store, job_id, age_days=1)
    runs = store.all_runs()

    prunable = select_prunable_runs(
        runs, RetentionPolicy(retention_days=180), now=utcnow()
    )
    assert prunable == []


def test_prunable_keeps_latest_run_even_when_expired(tmp_path):
    """⚠️ 最新一次**永远**保留 —— 告警中心只读最新 run，删了它整个页面就空了。

    这在「任务停了半年、你打开平台看告警」时是刚需：
    那个任务不会再产生新运行，清理每轮都会把最后一条删掉，
    告警中心就**永久**空了。
    """
    store, job_id = _make_store(tmp_path)
    latest = _add_run(store, job_id, age_days=999)
    runs = store.all_runs()

    prunable = select_prunable_runs(
        runs, RetentionPolicy(retention_days=1), now=utcnow()
    )
    assert latest not in prunable


def test_prunable_skips_inflight_run(tmp_path):
    """⚠️ 正在执行的运行不删 —— 删了它的目录，runner 写文件会失败。

    ⚠️ **场景要挑对**：正在执行的那次**不是最新的一次**。
       否则「最新一次永远保留」已经把它挡住了，这个测试就白写了
       （去掉 protected 分支它照样绿）。
       多进程部署时会出现这种局面：进程 1 在写 run 100，
       进程 2 不知道、又起了 run 101。
    """
    store, job_id = _make_store(tmp_path)
    oldest = _add_run(store, job_id, age_days=200)
    _add_run(store, job_id, age_days=100)
    _add_run(store, job_id, age_days=0)
    runs = store.all_runs()  # id 倒序

    policy = RetentionPolicy(retention_days=180)
    # 不保护时：最老的那次会超保留期
    assert select_prunable_runs(runs, policy, now=utcnow()) == [oldest]

    # 保护它 → 不删
    prunable = select_prunable_runs(runs, policy, now=utcnow(), protected={oldest})
    assert oldest not in prunable


def test_prunable_window_boundary_is_inclusive(tmp_path):
    """⚠️ 正好等于截止时间的算**保留**（闭区间）。"""
    store, job_id = _make_store(tmp_path)
    now = utcnow()
    run = store.create_run(job_id)
    store.finish_run(run.id, "success")
    exact = now - timedelta(days=30)
    with store._conn() as conn:
        conn.execute(
            "UPDATE runs SET started_at = ? WHERE id = ?", (to_iso(exact), run.id)
        )
    runs = store.all_runs()
    prunable = select_prunable_runs(
        runs, RetentionPolicy(retention_days=30), now=now
    )
    assert prunable == []


# ---------- 集成：prune ----------


def test_prune_deletes_rows_and_dirs(tmp_path):
    """超保留期的运行：DB 行与结果目录一起清掉。"""
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    old = _add_run(store, job_id, age_days=200, with_dir=True, data_root=data_root)
    _add_run(store, job_id, age_days=1, with_dir=True, data_root=data_root)

    result = prune(
        store, data_root, RetentionPolicy(retention_days=180), now=utcnow()
    )
    assert result.deleted_runs == 1
    assert result.deleted_dirs == 1
    assert result.freed_bytes > 0
    assert not run_dir(data_root, old).exists()
    assert len(store.all_runs()) == 1


def test_prune_keeps_feedback_but_detaches_reference(tmp_path):
    """⚠️ 人工反馈**不删** —— 只把指向已删运行的 `run_id` 断开。

    表里没有外键约束（`run_id INTEGER`，无 `REFERENCES`），
    所以必须手动置 NULL，否则就是悬空引用。
    """
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    old = _add_run(store, job_id, age_days=200)
    _add_run(store, job_id, age_days=1)
    store.add_feedback(
        job_id=job_id,
        run_id=old,
        series_id="cpu-1",
        start_ts="2026-01-01T00:00:00Z",
        end_ts="2026-01-01T00:05:00Z",
        kind="false_alarm",
    )

    prune(store, data_root, RetentionPolicy(retention_days=180), now=utcnow())
    feedback = store.list_feedback(job_id)
    assert len(feedback) == 1, "人工反馈不该被自动删掉"
    assert feedback[0].run_id is None, "引用断了，但反馈本身要留着"


def test_prune_removes_orphan_dirs(tmp_path):
    """孤儿目录（DB 里没有记录）要清掉 —— 纯垃圾。"""
    store, _job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    orphan = run_dir(data_root, 999)
    orphan.mkdir(parents=True)
    (orphan / "x.npz").write_bytes(b"y" * 64)

    result = prune(store, data_root, RetentionPolicy(), now=utcnow())
    assert result.orphan_dirs == 1
    assert not orphan.exists()


def test_prune_skips_non_numeric_dir_names(tmp_path):
    """⚠️ 非数字目录名跳过 —— 可能是人放进去的东西，不该乱删。"""
    store, _job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    manual = run_dir(data_root, 0).parent / "my-notes"
    manual.mkdir(parents=True)
    (manual / "readme.txt").write_text("别删我", encoding="utf-8")

    prune(store, data_root, RetentionPolicy(), now=utcnow())
    assert manual.exists()


def test_prune_dry_run_changes_nothing(tmp_path):
    """`--dry-run` 只报告，不动任何东西。"""
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    old = _add_run(store, job_id, age_days=200, with_dir=True, data_root=data_root)
    _add_run(store, job_id, age_days=1)

    result = prune(
        store, data_root, RetentionPolicy(retention_days=180), now=utcnow(), dry_run=True
    )
    assert result.deleted_runs == 1
    assert result.freed_bytes > 0
    assert run_dir(data_root, old).exists(), "dry-run 不该删目录"
    assert len(store.all_runs()) == 2, "dry-run 不该删 DB 行"


def test_prune_keeps_everything_within_retention(tmp_path):
    """⚠️ 没有「条数上限」—— 保留期内的**一条都不删**。

    这是简化保留策略的核心承诺：配 180 天就是留 180 天。
    """
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    for _ in range(300):
        _add_run(store, job_id, age_days=1, with_dir=True, data_root=data_root)

    prune(store, data_root, RetentionPolicy(retention_days=180), now=utcnow())
    assert len(store.all_runs()) == 300


def test_disk_cap_catches_high_frequency_jobs(tmp_path, monkeypatch):
    """⚠️ 磁盘上限兜底 —— 任务频率太高时，「保留 180 天」会撑爆磁盘。

    保留期永远优先，但兜不住时宁可少留 —— **平台不能因为磁盘写满而崩掉**。
    触发时要在结果里说出来，不藏着。
    """
    monkeypatch.setattr("anomaly_lab.platform.retention.MAX_BYTES_PER_JOB", 1024)
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    for _ in range(5):
        _add_run(
            store, job_id, age_days=1, with_dir=True, data_root=data_root, size_bytes=512
        )

    result = prune(store, data_root, RetentionPolicy(retention_days=180), now=utcnow())
    assert result.disk_capped_jobs == [job_id], "触发了上限就要说出来"
    assert result.deleted_runs > 0, "超上限的最老的那些要被删"
    # 最新一次永远保留
    assert len(store.all_runs()) >= 1


def test_disk_cap_does_not_trigger_within_budget(tmp_path, monkeypatch):
    """占用没超上限时**不额外删** —— 保留期是唯一的策略。"""
    monkeypatch.setattr("anomaly_lab.platform.retention.MAX_BYTES_PER_JOB", 1024**3)
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    for _ in range(5):
        _add_run(store, job_id, age_days=1, with_dir=True, data_root=data_root)

    result = prune(store, data_root, RetentionPolicy(retention_days=180), now=utcnow())
    assert result.disk_capped_jobs == []
    assert result.deleted_runs == 0


def test_prune_records_state(tmp_path):
    """清理状态写进库里 —— 「上次清理时间」要跨进程可见。"""
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    _add_run(store, job_id, age_days=200)
    _add_run(store, job_id, age_days=1)

    prune(store, data_root, RetentionPolicy(retention_days=180), now=utcnow())
    state = store.get_retention_state()
    assert state["pruned_at"] is not None
    assert state["deleted_runs"] == 1


def test_prune_protects_inflight_run(tmp_path, monkeypatch):
    """端到端：正在执行的 run 不会被清掉。

    ⚠️ 同样要把「正在执行的那次」设成**不是最新的一次** ——
       否则测的是「最新保留」，不是「正在执行不删」。
    """
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    running = _add_run(
        store, job_id, age_days=200, with_dir=True, data_root=data_root
    )
    _add_run(store, job_id, age_days=100)
    _add_run(store, job_id, age_days=0)
    monkeypatch.setattr(
        "anomaly_lab.platform.retention.inflight_run_ids", lambda: {running}
    )

    prune(store, data_root, RetentionPolicy(retention_days=180), now=utcnow())
    assert run_dir(data_root, running).exists()
    assert running in {run.id for run in store.all_runs()}


# ---------- 策略参数 ----------


def test_policy_from_env(monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "30")
    policy = RetentionPolicy.from_env()
    assert policy.retention_days == 30


def test_policy_from_env_falls_back_on_garbage(monkeypatch):
    """非法值回落到默认值 —— 不能因为一个环境变量写错就整个平台起不来。"""
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "不是数字")
    policy = RetentionPolicy.from_env()
    assert policy.retention_days == DEFAULT_RETENTION_DAYS


def test_policy_from_env_falls_back_on_negative(monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_DAYS", "-5")
    assert RetentionPolicy.from_env().retention_days == DEFAULT_RETENTION_DAYS


def test_policy_default():
    assert RetentionPolicy().retention_days == DEFAULT_RETENTION_DAYS


# ---------- 占用统计 ----------


def test_storage_usage_reports_disk_and_policy(tmp_path):
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    _add_run(store, job_id, with_dir=True, data_root=data_root)

    usage = storage_usage(store, data_root, RetentionPolicy())
    assert usage["policy"]["retention_days"] == DEFAULT_RETENTION_DAYS
    assert usage["runs"]["kept"] == 1
    assert usage["runs"]["n_dirs"] == 1
    assert usage["runs"]["bytes"] > 0
    assert usage["database"]["bytes"] > 0
    assert usage["last_pruned_at"] is None


def test_prune_handles_empty_store(tmp_path):
    """没有任何运行时不能崩。"""
    store, _job_id = _make_store(tmp_path)
    result = prune(store, tmp_path / "data", RetentionPolicy(), now=utcnow())
    assert result.deleted_runs == 0
    assert result.kept_runs == 0


def test_now_can_be_injected(tmp_path):
    """`now` 可注入 —— 判定必须可复现，不能依赖真实时钟。"""
    store, job_id = _make_store(tmp_path)
    old = _add_run(store, job_id, age_days=200)
    _add_run(store, job_id, age_days=0)
    future = utcnow() + timedelta(days=365)
    prune(store, tmp_path / "data", RetentionPolicy(retention_days=180), now=future)
    assert old not in {run.id for run in store.all_runs()}


@pytest.mark.parametrize("days", [1, 30, 365])
def test_policy_accepts_any_day_count(days):
    assert RetentionPolicy(retention_days=days).retention_days == days
