"""任务执行与算法调用的埋点：跑完一次任务后，监控页要能看到数字。"""

import sqlite3
from datetime import timedelta

import pytest

from anomaly_lab.observability import get_observability, reset_observability
from anomaly_lab.platform import runner
from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow


def _make_job(tmp_path, *, name="job", detector="iqr"):
    """⚠️ tests/ 不是 package，不能跨文件 import helper —— 就地复制建库代码。"""
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
        name=name,
        detector=detector,
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


def _write_series(tmp_path, values) -> None:
    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (ts TEXT, value REAL)")
    end = utcnow().replace(second=0, microsecond=0)
    n = len(values)
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [
            (to_iso(end - timedelta(minutes=5 * (n - 1 - i))), float(value))
            for i, value in enumerate(values)
        ],
    )
    conn.commit()
    conn.close()


def test_一次成功运行记录任务与算法指标(tmp_path):
    reset_observability()
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [10.0 + (i % 7) for i in range(60)])

    execute_job(store, job_id, data_root=tmp_path)

    registry = get_observability().registry
    assert registry.counter("job.runs", job="job", status="success") == 1
    assert registry.counter("detector.calls", detector="iqr", status="ok") == 1
    # 阶段与总耗时都该有样本
    assert registry.histogram_with_prefix("job.stage_ms")
    assert registry.histogram_with_prefix("job.duration_ms")
    assert registry.histogram_with_prefix("detector.duration_ms")


def test_失败运行记为_failed(tmp_path, monkeypatch):
    reset_observability()
    store, job_id = _make_job(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("取数炸了")

    monkeypatch.setattr(runner, "_compute_job", boom)
    with pytest.raises(RuntimeError):
        execute_job(store, job_id, data_root=tmp_path)

    registry = get_observability().registry
    assert registry.counter("job.runs", job="job", status="failed") == 1
    # 失败也要留下耗时 —— 「挂在哪一步、挂了多久」是排查的起点
    assert registry.histogram_with_prefix("job.duration_ms")


def test_算法回退单独计数(tmp_path, monkeypatch):
    """形态推荐了别的算法、实际回退时，监控页要能看出「这个任务在回退」。

    ⚠️ 回退本身是 `auto` 的决策逻辑，这里用 monkeypatch 固定它 ——
       本测试只关心「回退有没有被单独记账」，不重复测选择算法。
    """
    from types import SimpleNamespace

    reset_observability()
    store, job_id = _make_job(tmp_path, detector="auto")
    _write_series(tmp_path, [10.0 + (i % 7) for i in range(60)])
    monkeypatch.setattr(
        runner,
        "resolve_detector",
        lambda *_args, **_kwargs: SimpleNamespace(
            detector="iqr",
            requested="auto",
            fallback=True,
            metric_class="stationary",
            confidence=0.5,
            reasons=[],
            rationale="测试固定回退",
            candidates=["stl_residual"],
        ),
    )

    execute_job(store, job_id, data_root=tmp_path)

    registry = get_observability().registry
    assert registry.counter("detector.calls", detector="iqr", status="fallback") == 1
    assert registry.counter("detector.calls", detector="iqr", status="ok") == 0
