"""进程内定时调度：到点执行任务，重启后错过的窗口只补跑一次。

调度语义：
- 每个任务有自己的 `next_run_at`，到期才执行；
- 执行后统一推进到 `now + interval`，失败不重试风暴（失败详情在 runs 表）；
- 进程重启时 `reconcile` 把错过的窗口收敛到「现在」，所以只补跑一次。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from anomaly_lab.platform import retention
from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow

logger = logging.getLogger(__name__)

Runner = Callable[..., object]


class Scheduler:
    def __init__(
        self,
        store: PlatformStore,
        data_root: Path,
        poll_seconds: float = 2.0,
        runner: Runner | None = None,
        prune_every_seconds: float = 3600.0,
    ) -> None:
        self.store = store
        self.data_root = Path(data_root)
        self.poll_seconds = float(poll_seconds)
        self.runner = runner or execute_job
        #: 多久清理一次超窗数据（秒）；≤ 0 表示关掉自动清理。
        self.prune_every_seconds = float(prune_every_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_prune: float | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def reconcile(self, now: datetime | None = None) -> int:
        """把错过的窗口收敛到现在，只留一次补跑。"""
        return self.store.reconcile_missed(to_iso(now or utcnow()))

    def tick(self, now: datetime | None = None) -> list[int]:
        """执行所有到期任务，返回本次产生的 run_id。"""
        current = now or utcnow()
        run_ids: list[int] = []
        with self._lock:
            for job in self.store.due_jobs(to_iso(current)):
                try:
                    run_ids.append(
                        int(
                            self.runner(
                                self.store, job.id, data_root=self.data_root, now=current
                            )
                        )
                    )
                except Exception:
                    # 失败详情已落在 runs 表，这里只记日志，避免重试风暴
                    logger.exception("任务 %s 执行失败", job.name)
                next_run = current + timedelta(seconds=job.interval_seconds)
                self.store.update_job_schedule(job.id, to_iso(current), to_iso(next_run))
        self._maybe_prune(current)
        return run_ids

    def _maybe_prune(self, now: datetime) -> None:
        """到点就清理一次超窗数据（运行记录 + 检测结果文件）。

        ⚠️ **必须节流** —— tick 默认每 2 秒一次，每次都全表扫描 +
           遍历所有 run 目录太浪费。而清理本身是「低频的例行公事」。

        ⚠️ **失败只记日志** —— 清理失败不该把调度线程带走
           （否则整个平台再也不会执行任务了）。
        """
        if self.prune_every_seconds <= 0:
            return
        stamp = now.timestamp()
        if (
            self._last_prune is not None
            and stamp - self._last_prune < self.prune_every_seconds
        ):
            return
        self._last_prune = stamp
        try:
            result = retention.prune(self.store, self.data_root, now=now)
        except Exception:
            logger.exception("数据保留清理失败")
            return
        if result.deleted_runs or result.orphan_dirs:
            logger.info(
                "数据保留清理：删了 %d 次运行、%d 个孤儿目录，释放 %.1f KB",
                result.deleted_runs,
                result.orphan_dirs,
                result.freed_bytes / 1024,
            )

    def start(self) -> None:
        if self.is_running:
            return
        self.reconcile()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="anomaly-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            self.tick()
