"""数据保留与清理：删掉超出保留期的运行记录与检测结果文件。

平台的任务每 5 分钟产生一次运行记录（DB 一行 + 一个 npz 目录）。
不清理的话一年就是 21 万行、几个 GB —— 而且「803 条一模一样的运行记录」
在作品集演示时是负分。

**保留期只有一个维度：时间。** 配「保留 180 天」就是保留 180 天 ——
可预测，而且跟 Prometheus / Grafana Cloud 的心智模型一致。

⚠️ **不是「保留最近 N 次」**：两个维度都要解释、都要测，收益却只是给
   高频任务兜底。兜底该由**磁盘上限**做（见 `MAX_BYTES_PER_JOB`），
   而不是塞进策略里让人去理解「∩」。

**范围**：只管平台侧。

- 人工反馈（`feedback` 表）与标注**不删** —— 那是人工产生的数据，
  删它等于丢弃用户的劳动成果（只把指向已删运行的 `run_id` 断开）。
- 假远端的数据在 `data/mock_tsdb/`，它自己滚动保留最近 6 小时 ——
  **不归平台管**，本模块的路径跟它完全不相交。
- 回测侧的检测结果（`data/cache/detections/`）是 `make detect` 的一次性产物，
  也不归本模块管。
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from anomaly_lab.platform.models import Run
from anomaly_lab.platform.runner import inflight_run_ids, run_dir
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import parse_iso, to_iso, utcnow

logger = logging.getLogger(__name__)

#: 默认保留多少天。
DEFAULT_RETENTION_DAYS = 180

ENV_RETENTION_DAYS = "ANOMALY_LAB_RETENTION_DAYS"

#: 单个任务的结果目录上限（字节）。
#:
#: ⚠️ 这是**最后一道保险**，不是策略维度 —— 用户配的保留期永远优先。
#:    存在的理由只有一个：**磁盘写满会让整个平台崩掉**。
#:    任务频率极高时（每 10 秒一次），「保留 180 天」要 27 GB ——
#:    那时候宁可少留，也不能让平台撑不住。
#:    触发时会记进清理结果，不藏着。
MAX_BYTES_PER_JOB = 4 * 1024**3


@dataclass(frozen=True)
class RetentionPolicy:
    """保留策略：**只有保留期天数这一个参数**。"""

    #: 保留最近多少天内的运行。
    retention_days: int = DEFAULT_RETENTION_DAYS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RetentionPolicy:
        """从环境变量读保留期；非法值回落到默认值（并记警告）。

        ⚠️ 保留策略是**部署参数**，不是业务配置 —— 所以放环境变量而不是数据库。
           放库里意味着要加设置界面、加校验、加审计，超出这套东西的职责。
        """
        source = os.environ if env is None else env
        return cls(retention_days=_env_int(source, ENV_RETENTION_DAYS, DEFAULT_RETENTION_DAYS))


@dataclass
class PruneResult:
    """一次清理的结果。"""

    #: 删掉的运行记录（DB 行）。
    deleted_runs: int = 0
    #: 删掉的运行目录。
    deleted_dirs: int = 0
    #: 顺带清掉的孤儿目录（DB 里已经没有对应记录）。
    orphan_dirs: int = 0
    #: 释放的字节数。
    freed_bytes: int = 0
    #: 清理后保留的运行记录数。
    kept_runs: int = 0
    #: 触发了磁盘上限兜底的任务（它们的实际保留期比配的短）。
    disk_capped_jobs: list[int] | None = None
    #: 只报告没真删。
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            "deleted_runs": self.deleted_runs,
            "deleted_dirs": self.deleted_dirs,
            "orphan_dirs": self.orphan_dirs,
            "freed_bytes": self.freed_bytes,
            "kept_runs": self.kept_runs,
            "disk_capped_jobs": self.disk_capped_jobs or [],
            "dry_run": self.dry_run,
        }


def _env_int(source: Mapping[str, str], key: str, default: int) -> int:
    raw = source.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s 不是整数（%r），用默认值 %s", key, raw, default)
        return default
    if value < 0:
        logger.warning("%s 不能为负（%r），用默认值 %s", key, raw, default)
        return default
    return value


def _expired(run: Run, cutoff: datetime) -> bool:
    """这次运行是不是已经超出保留期。"""
    try:
        return parse_iso(run.started_at) < cutoff
    except ValueError:
        # 时间戳坏了 —— 当成过期处理（它在列表里也不可信）
        return True


def select_prunable_runs(
    runs_desc: Sequence[Run],
    policy: RetentionPolicy,
    *,
    now: datetime,
    protected: Collection[int] = (),
) -> list[int]:
    """选出该任务下**可以删**的运行 id。

    `runs_desc` 是该任务的全部运行，按 id 倒序（新的在前）。

    判据只有一个：**早于保留期**。

    两条**功能性**保护（不是策略维度，破坏任何一条都是功能坏了）：

    1. **最新一次永远保留** —— 告警中心只读最新 run
       （`collect_alert_events` → `latest_runs()`）。删了它整个告警页就空了。
       ⚠️ 这条在「任务停了半年、然后你打开平台看告警」时是刚需：
          那个任务不会再产生新运行，清理每轮都会把最后一条删掉，
          告警中心就**永久**空了。
    2. `protected`（正在执行的）一律不删 —— 删了它的目录，
       runner 往里写 npz 时就会失败，**清理由别人触发却把别人的运行搞坏**。
    """
    cutoff = now - timedelta(days=policy.retention_days)
    prunable: list[int] = []
    for index, run in enumerate(runs_desc):
        if run.id in protected:
            continue
        if index == 0:
            # 最新一次：永远保留 —— 告警中心只读它
            continue
        if _expired(run, cutoff):
            prunable.append(run.id)
    return prunable


def _dir_size(path: Path) -> int:
    """目录占用的字节数（递归）。"""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                # 文件刚好被别人删了 —— 算它 0 字节，不当错误
                continue
    return total


def _enforce_disk_cap(
    by_job: dict[int, list[Run]],
    data_root: Path,
    already_pruned: set[int],
    protected: Collection[int],
) -> tuple[list[int], list[int]]:
    """单任务结果目录超过上限时，额外删掉最老的运行。

    ⚠️ 这是**最后一道保险**，不是策略维度 —— 用户配的保留期永远优先，
       只有它兜不住（任务频率太高）时才生效。

    返回 `(要删的 run_id, 触发了上限的任务 id)`。
    """
    extra: list[int] = []
    capped: list[int] = []
    for job_id, job_runs in by_job.items():
        if not job_runs:
            continue
        # 最新一次与正在执行的都不参与删（与时间窗口同一套保护）
        keep = {job_runs[0].id} | set(protected)
        candidates = [
            run for run in job_runs if run.id not in already_pruned and run.id not in keep
        ]
        total = sum(_dir_size(run_dir(data_root, run.id)) for run in candidates)
        if total <= MAX_BYTES_PER_JOB:
            continue
        capped.append(job_id)
        # 从最老开始删（candidates 是 id 倒序，反过来就是从最老开始）
        for run in reversed(candidates):
            if total <= MAX_BYTES_PER_JOB:
                break
            size = _dir_size(run_dir(data_root, run.id))
            extra.append(run.id)
            total -= size
    return extra, capped


def _prune_orphans(
    store: PlatformStore, data_root: Path, *, dry_run: bool
) -> tuple[int, int]:
    """清孤儿目录：目录还在，但 `runs` 表里已经没有对应记录。

    手动删库、异常退出、手工删表都会留下它们 —— 纯垃圾。

    返回 `(目录数, 字节数)`。
    """
    root = data_root / "cache" / "platform" / "runs"
    if not root.is_dir():
        return 0, 0
    known = {run.id for run in store.all_runs()}
    count = 0
    freed = 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            run_id = int(entry.name)
        except ValueError:
            # 非数字目录名 —— **跳过**（可能是人放进去的东西，不该乱删）
            continue
        if run_id in known:
            continue
        freed += _dir_size(entry)
        if not dry_run:
            shutil.rmtree(entry, ignore_errors=True)
        count += 1
    return count, freed


def prune(
    store: PlatformStore,
    data_root: Path,
    policy: RetentionPolicy | None = None,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> PruneResult:
    """按保留期清理运行记录与检测结果文件。

    ⚠️ **先删文件、再删数据库行** —— 两个方向都有自愈路径，
       但磁盘占用的释放是本模块的主要目标，而「DB 里有条记录但文件没了」
       只是暂时的展示层不一致（下轮清理会把它带走）。
    """
    policy = policy or RetentionPolicy.from_env()
    now = now or utcnow()
    data_root = Path(data_root)

    runs = store.all_runs()
    by_job: dict[int, list[Run]] = {}
    for run in runs:
        by_job.setdefault(run.job_id, []).append(run)

    protected = inflight_run_ids()
    prunable: list[int] = []
    for job_runs in by_job.values():
        prunable.extend(
            select_prunable_runs(job_runs, policy, now=now, protected=protected)
        )

    # 磁盘上限兜底：保留期兜不住时（任务频率太高）再删一些最老的
    extra, capped = _enforce_disk_cap(by_job, data_root, set(prunable), protected)
    prunable.extend(extra)

    result = PruneResult(
        dry_run=dry_run,
        kept_runs=len(runs) - len(prunable),
        disk_capped_jobs=capped,
    )

    freed = 0
    dirs = 0
    for run_id in prunable:
        target = run_dir(data_root, run_id)
        if not target.exists():
            continue
        freed += _dir_size(target)
        if not dry_run:
            shutil.rmtree(target, ignore_errors=True)
        dirs += 1

    result.deleted_runs = len(prunable)
    result.deleted_dirs = dirs
    result.freed_bytes = freed

    if not dry_run and prunable:
        # ⚠️ 反馈**不删** —— 只把指向已删运行的引用断开（表里没有外键约束）
        store.delete_runs(prunable)

    orphans, orphan_bytes = _prune_orphans(store, data_root, dry_run=dry_run)
    result.orphan_dirs = orphans
    result.freed_bytes += orphan_bytes

    if not dry_run:
        store.set_retention_state(
            pruned_at=to_iso(now),
            deleted_runs=result.deleted_runs,
            freed_bytes=result.freed_bytes,
        )
    return result


def storage_usage(
    store: PlatformStore,
    data_root: Path,
    policy: RetentionPolicy | None = None,
) -> dict:
    """当前占用与保留策略 —— 给「存储」端点与概览页用。

    ⚠️ 「自动清理」如果完全不可见，用户没法判断它在不在工作 ——
       作品集演示时，「数据在自动滚动」本身就是个卖点。
    """
    policy = policy or RetentionPolicy.from_env()
    data_root = Path(data_root)
    runs_root = data_root / "cache" / "platform" / "runs"

    n_dirs = 0
    run_bytes = 0
    if runs_root.is_dir():
        for entry in runs_root.iterdir():
            if entry.is_dir():
                n_dirs += 1
                run_bytes += _dir_size(entry)

    db_path = Path(store.db_path)
    db_bytes = db_path.stat().st_size if db_path.exists() else 0
    state = store.get_retention_state()

    return {
        "policy": {"retention_days": policy.retention_days},
        "runs": {
            "kept": len(store.all_runs()),
            "n_dirs": n_dirs,
            "bytes": run_bytes,
        },
        "database": {"path": str(db_path), "bytes": db_bytes},
        "feedback": {"total": sum(store.feedback_stats().values())},
        "last_pruned_at": state["pruned_at"],
        "last_pruned": {
            "deleted_runs": state["deleted_runs"],
            "freed_bytes": state["freed_bytes"],
        },
    }
