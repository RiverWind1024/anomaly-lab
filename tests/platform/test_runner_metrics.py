"""任务执行与算法调用的埋点：跑完一次任务后，监控数据里要看得到。"""

import json
import sqlite3
from datetime import timedelta

import pytest

from anomaly_lab.observability import (
    configure_observability,
    get_observability,
    reset_observability,
)
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
        window_seconds=60 * 300,
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


def _configure(tmp_path):
    reset_observability()
    # ⚠️ 显式配置到 tmp_path —— 默认实例是 no-op，不会写仓库里的 data/。
    return configure_observability(data_root=tmp_path, export_interval_seconds=3600)


def _total(obs, metric: str, **match: str) -> dict | None:
    for row in obs.store().total_rows():
        if row["metric"] != metric:
            continue
        labels = json.loads(row["labels"] or "{}")
        if all(labels.get(key) == value for key, value in match.items()):
            return row
    return None


def test_一次成功运行记录任务与算法指标(tmp_path):
    obs = _configure(tmp_path)
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [10.0 + (i % 7) for i in range(60)])

    execute_job(store, job_id, data_root=tmp_path)
    obs.force_flush()

    assert _total(obs, "job.runs", job="job", status="success")["value"] == 1
    assert _total(obs, "detector.calls", detector="iqr", status="ok")["value"] == 1
    # 阶段与总耗时都该有样本
    rows = obs.store().total_rows()
    stages = {json.loads(row["labels"] or "{}").get("stage") for row in rows if row["metric"] == "job.stage_ms"}
    assert {"load", "detect", "persist"} <= stages
    assert any(row["metric"] == "job.duration_ms" for row in rows)
    assert any(row["metric"] == "detector.duration_ms" for row in rows)


def test_失败运行记为_failed(tmp_path, monkeypatch):
    obs = _configure(tmp_path)
    store, job_id = _make_job(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("取数炸了")

    monkeypatch.setattr(runner, "_compute_job", boom)
    with pytest.raises(RuntimeError):
        execute_job(store, job_id, data_root=tmp_path)

    obs.force_flush()
    assert _total(obs, "job.runs", job="job", status="failed")["value"] == 1
    # 失败也要留下耗时 —— 「挂在哪一步、挂了多久」是排查的起点
    assert any(row["metric"] == "job.duration_ms" for row in obs.store().total_rows())


def test_算法回退单独计数(tmp_path, monkeypatch):
    """形态推荐了别的算法、实际回退时，监控页要能看出「这个任务在回退」."""
    from types import SimpleNamespace

    obs = _configure(tmp_path)
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
    obs.force_flush()

    assert _total(obs, "detector.calls", detector="iqr", status="fallback")["value"] == 1
    assert _total(obs, "detector.calls", detector="iqr", status="ok") is None


def test_没有配置时埋点不落盘(tmp_path, monkeypatch):
    """默认实例必须是 no-op，否则测试会往仓库里写 data/metrics.db。"""
    reset_observability()
    monkeypatch.chdir(tmp_path)
    obs = get_observability()
    assert obs.configured is False
    obs.inc("http.requests", 1)
    obs.force_flush()
    assert not (tmp_path / "data" / "metrics.db").exists()
