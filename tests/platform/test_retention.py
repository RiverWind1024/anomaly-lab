"""数据保留与清理策略。

⚠️ 三条**功能性**约束 —— 破坏任何一条都不是「清理过头」，是**功能坏了**：

1. 最新一次运行永远保留（告警中心只读最新 run）；
2. 正在执行的运行不删（删了它的目录，runner 写文件会失败）；
3. 人工反馈不删（那是人工数据），只把引用断开。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from anomaly_lab.platform.retention import (
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_MAX_RUNS_PER_JOB,
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
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


def _add_run(
    store: PlatformStore,
    job_id: int,
    *,
    age_hours: float = 0.0,
    with_dir: bool = False,
    data_root: Path | None = None,
) -> int:
    """造一次运行记录（可指定「多久之前」），可选带上它的结果目录。"""
    run = store.create_run(job_id)
    store.finish_run(run.id, "success", n_series=1, n_alerts=0)
    started = utcnow() - timedelta(hours=age_hours)
    with store._conn() as conn:
        conn.execute(
            "UPDATE runs SET started_at = ? WHERE id = ?", (to_iso(started), run.id)
        )
    if with_dir and data_root is not None:
        target = run_dir(data_root, run.id)
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.json").write_text("{}", encoding="utf-8")
        (target / "a.npz").write_bytes(b"x" * 128)
    return run.id


# ---------- 纯函数：保留窗口 ----------


def test_prunable_respects_run_count_limit(tmp_path):
    """次数上限：保留最近 N 次，其余待删。"""
    store, job_id = _make_store(tmp_path)
    ids = [_add_run(store, job_id) for _ in range(5)]
    runs = store.all_runs()  # all_runs 已经是 id 倒序（新的在前）

    prunable = select_prunable_runs(
        runs, RetentionPolicy(max_age_hours=999, max_runs_per_job=2), now=utcnow()
    )
    assert set(prunable) == set(ids[:-2])


def test_prunable_respects_age_window(tmp_path):
    """时间窗口：超过保留时长的待删。"""
    store, job_id = _make_store(tmp_path)
    old = _add_run(store, job_id, age_hours=48)
    fresh = _add_run(store, job_id, age_hours=1)
    runs = store.all_runs()

    prunable = select_prunable_runs(
        runs, RetentionPolicy(max_age_hours=24, max_runs_per_job=100), now=utcnow()
    )
    assert prunable == [old]
    assert fresh not in prunable


def test_prunable_keeps_latest_run_even_when_expired(tmp_path):
    """⚠️ 最新一次**永远**保留 —— 告警中心只读最新 run，删了它整个页面就空了。

    这是功能破坏，不是「清理过头」。
    """
    store, job_id = _make_store(tmp_path)
    latest = _add_run(store, job_id, age_hours=999)
    runs = store.all_runs()

    prunable = select_prunable_runs(
        runs, RetentionPolicy(max_age_hours=1, max_runs_per_job=1), now=utcnow()
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
    oldest = _add_run(store, job_id, age_hours=48)
    _add_run(store, job_id, age_hours=0.5)
    _add_run(store, job_id, age_hours=0)
    runs = store.all_runs()  # id 倒序

    policy = RetentionPolicy(max_age_hours=1, max_runs_per_job=2)
    # 不保护时：最老的那次会因数量上限被删
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
    exact = now - timedelta(hours=24)
    with store._conn() as conn:
        conn.execute(
            "UPDATE runs SET started_at = ? WHERE id = ?", (to_iso(exact), run.id)
        )
    runs = store.all_runs()
    prunable = select_prunable_runs(
        runs, RetentionPolicy(max_age_hours=24, max_runs_per_job=100), now=now
    )
    assert prunable == []


# ---------- 集成：prune ----------


def test_prune_deletes_rows_and_dirs(tmp_path):
    """超窗的运行：DB 行与结果目录一起清掉。"""
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    old = _add_run(store, job_id, age_hours=48, with_dir=True, data_root=data_root)
    _add_run(store, job_id, age_hours=1, with_dir=True, data_root=data_root)

    result = prune(
        store,
        data_root,
        RetentionPolicy(max_age_hours=24, max_runs_per_job=100),
        now=utcnow(),
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
    old = _add_run(store, job_id, age_hours=48)
    _add_run(store, job_id, age_hours=1)
    store.add_feedback(
        job_id=job_id,
        run_id=old,
        series_id="cpu-1",
        start_ts="2026-01-01T00:00:00Z",
        end_ts="2026-01-01T00:05:00Z",
        kind="false_alarm",
    )

    prune(
        store,
        data_root,
        RetentionPolicy(max_age_hours=24, max_runs_per_job=100),
        now=utcnow(),
    )
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
    old = _add_run(store, job_id, age_hours=48, with_dir=True, data_root=data_root)
    _add_run(store, job_id, age_hours=1)

    result = prune(
        store, data_root, RetentionPolicy(max_age_hours=24), now=utcnow(), dry_run=True
    )
    assert result.deleted_runs == 1
    assert result.freed_bytes > 0
    assert run_dir(data_root, old).exists(), "dry-run 不该删目录"
    assert len(store.all_runs()) == 2, "dry-run 不该删 DB 行"


def test_prune_enforces_run_limit_over_many_runs(tmp_path):
    """造 300 次运行 → 清完每任务保留数 ≤ 上限。"""
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    for _ in range(300):
        _add_run(store, job_id, age_hours=0.1, with_dir=True, data_root=data_root)

    prune(
        store,
        data_root,
        RetentionPolicy(max_age_hours=999, max_runs_per_job=10),
        now=utcnow(),
    )
    assert len(store.all_runs()) == 10
    dirs = list(run_dir(data_root, 0).parent.iterdir())
    assert len(dirs) == 10, "目录也要跟着清"


def test_prune_records_state(tmp_path):
    """清理状态写进库里 —— 「上次清理时间」要跨进程可见。"""
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    _add_run(store, job_id, age_hours=48)
    _add_run(store, job_id, age_hours=1)

    prune(store, data_root, RetentionPolicy(max_age_hours=24), now=utcnow())
    state = store.get_retention_state()
    assert state["pruned_at"] is not None
    assert state["deleted_runs"] == 1


def test_prune_protects_inflight_run(tmp_path, monkeypatch):
    """端到端：正在执行的 run 不会被清掉。

    ⚠️ 同样要把「正在执行的那次」设成**不是最新的一次** ——
       否则测的是 D84（最新保留），不是 D85。
    """
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    running = _add_run(store, job_id, age_hours=48, with_dir=True, data_root=data_root)
    _add_run(store, job_id, age_hours=0.5)
    _add_run(store, job_id, age_hours=0)
    monkeypatch.setattr(
        "anomaly_lab.platform.retention.inflight_run_ids", lambda: {running}
    )

    prune(
        store, data_root, RetentionPolicy(max_age_hours=1, max_runs_per_job=2),
        now=utcnow(),
    )
    assert run_dir(data_root, running).exists()
    assert running in {run.id for run in store.all_runs()}


# ---------- 策略参数 ----------


def test_policy_from_env(monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_HOURS", "3")
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_MAX_RUNS", "7")
    policy = RetentionPolicy.from_env()
    assert policy.max_age_hours == 3
    assert policy.max_runs_per_job == 7


def test_policy_from_env_falls_back_on_garbage(monkeypatch):
    """非法值回落到默认值 —— 不能因为一个环境变量写错就整个平台起不来。"""
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_HOURS", "不是数字")
    monkeypatch.setenv("ANOMALY_LAB_RETENTION_MAX_RUNS", "-5")
    policy = RetentionPolicy.from_env()
    assert policy.max_age_hours == DEFAULT_MAX_AGE_HOURS
    assert policy.max_runs_per_job == DEFAULT_MAX_RUNS_PER_JOB


def test_policy_defaults():
    policy = RetentionPolicy()
    assert policy.max_age_hours == DEFAULT_MAX_AGE_HOURS
    assert policy.max_runs_per_job == DEFAULT_MAX_RUNS_PER_JOB


# ---------- 占用统计 ----------


def test_storage_usage_reports_disk_and_policy(tmp_path):
    store, job_id = _make_store(tmp_path)
    data_root = tmp_path / "data"
    _add_run(store, job_id, with_dir=True, data_root=data_root)

    usage = storage_usage(store, data_root, RetentionPolicy())
    assert usage["policy"]["max_runs_per_job"] == DEFAULT_MAX_RUNS_PER_JOB
    assert usage["runs"]["kept"] == 1
    assert usage["runs"]["n_dirs"] == 1
    assert usage["runs"]["bytes"] > 0
    assert usage["database"]["bytes"] > 0
    assert usage["last_pruned_at"] is None


@pytest.mark.parametrize("hours", [0.5, 24])
def test_policy_age_window_accepts_fractional_hours(hours):
    """保留时长允许小数小时。"""
    assert RetentionPolicy(max_age_hours=hours).max_age_hours == hours


def test_prune_handles_empty_store(tmp_path):
    """没有任何运行时不能崩。"""
    store, _job_id = _make_store(tmp_path)
    result = prune(store, tmp_path / "data", RetentionPolicy(), now=utcnow())
    assert result.deleted_runs == 0
    assert result.kept_runs == 0


def test_now_can_be_injected(tmp_path):
    """`now` 可注入 —— 判定必须可复现，不能依赖真实时钟。"""
    store, job_id = _make_store(tmp_path)
    old = _add_run(store, job_id, age_hours=48)
    _add_run(store, job_id, age_hours=0)
    future = utcnow() + timedelta(hours=72)
    prune(
        store,
        tmp_path / "data",
        RetentionPolicy(max_age_hours=24),
        now=future,
    )
    assert old not in {run.id for run in store.all_runs()}
