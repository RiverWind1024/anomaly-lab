"""尺度来源与「无法判定」必须一路传到 API。"""

import json
import sqlite3
from datetime import timedelta

import numpy as np
from fastapi.testclient import TestClient

from anomaly_lab.platform.runner import execute_job, run_dir
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _make_job(tmp_path, *, detector="iqr", alert_direction="both"):
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
        name="job",
        detector=detector,
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
        alert_direction=alert_direction,
    )
    return store, job.id


def _write_series(tmp_path, values) -> None:
    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (ts TEXT, value REAL)")
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


def _client(store, tmp_path) -> TestClient:
    return TestClient(create_app(platform_store=store, platform_data_root=tmp_path))


def test_预览返回尺度来源(tmp_path):
    store, job_id = _make_job(tmp_path)
    # 60 个完全相同的点 —— 尺度必然是 0，结果确定是「无法判定」
    _write_series(tmp_path, [7.0] * 60)
    execute_job(store, job_id, data_root=tmp_path)

    body = _client(store, tmp_path).get(f"/api/platform/jobs/{job_id}/preview").json()
    # ⚠️ 这个 fixture 是 60 个完全相同的点 —— 结果**确定**是不可判，
    #    不能用 `in {...}` 这种宽松断言，否则接口兜底默认值也能通过。
    assert body["scale_source"] == "none"
    assert body["status"] == "undetermined"
    # ⚠️ 「不可判」不是「降级」—— 两者语义不同，别把 none 也算成 fallback
    assert body["scale_fallback"] is False


def test_有波动序列不会被判成无法判定(tmp_path):
    """正向路径：不能只测负例 —— 否则实现恒定返回 undetermined 也能通过。"""
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, np.random.default_rng(0).normal(10, 2, 60))
    execute_job(store, job_id, data_root=tmp_path)

    body = _client(store, tmp_path).get(f"/api/platform/jobs/{job_id}/preview").json()
    assert body["scale_source"] == "iqr"
    assert body["status"] == "ok"
    assert body["scale_fallback"] is False


def test_zscore的原生std不算降级(tmp_path):
    """zscore 的首选尺度就是 std —— 那是原生，不能标成「降级」。"""
    store, job_id = _make_job(tmp_path, detector="zscore")
    _write_series(tmp_path, np.random.default_rng(1).normal(10, 2, 60))
    execute_job(store, job_id, data_root=tmp_path)

    body = _client(store, tmp_path).get(f"/api/platform/jobs/{job_id}/preview").json()
    assert body["scale_source"] == "std"
    assert body["scale_fallback"] is False


def test_iqr退化到std会被标记为降级(tmp_path):
    """真实降级：IQR 为 0、std 不为 0 —— 这个才该报「尺度降级」。"""
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [10.0] * 50 + [12.0] * 10)
    execute_job(store, job_id, data_root=tmp_path)

    body = _client(store, tmp_path).get(f"/api/platform/jobs/{job_id}/preview").json()
    assert body["scale_source"] == "std"
    assert body["status"] == "ok"
    assert body["scale_fallback"] is True


def test_预览返回告警方向是否真的生效(tmp_path):
    """⚠️ 配置了「只报偏低」但算法无基线时，必须让用户看到「没生效」。

    `poisson_count` 没有 `bands()`，`direction="below"` 一条都不会报 ——
    如果 preview 不返回 `direction_applied`，用户只会看到 0 告警。
    """
    store, job_id = _make_job(
        tmp_path, detector="poisson_count", alert_direction="below"
    )
    _write_series(tmp_path, np.array([0, 0, 1, 0, 2, 0, 1, 0, 0, 3] * 6, dtype=float))
    execute_job(store, job_id, data_root=tmp_path)

    body = _client(store, tmp_path).get(f"/api/platform/jobs/{job_id}/preview").json()
    assert body["alert_direction"] == "below"
    assert body["direction_applied"] is False


def test_老产物缺少新字段时回落默认值(tmp_path):
    """⚠️ 老 npz 没有 scale_source/status/scale_fallback —— 不能 500。"""
    store, job_id = _make_job(tmp_path)
    _write_series(tmp_path, [7.0] * 60)
    run_id = execute_job(store, job_id, data_root=tmp_path)

    # 模拟老产物：preview() 读的是 index.json，删的也是这里的键
    index_path = run_dir(tmp_path, run_id) / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for key in ("scale_source", "status", "scale_fallback"):
        index["series"][0].pop(key)
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    body = _client(store, tmp_path).get(f"/api/platform/jobs/{job_id}/preview").json()
    assert body["scale_source"] == ""
    assert body["status"] == "ok"
    assert body["scale_fallback"] is False
