"""`POST /api/platform/jobs/{id}/test-run`：试跑端点。"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient

from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app


def _client(tmp_path):
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
    _write_series(tmp_path)
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    return TestClient(app), store, job.id


def _write_series(tmp_path) -> None:
    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (ts TEXT, value REAL)")
    end = utcnow().replace(second=0, microsecond=0)
    base = [10.0, 11.0, 9.5, 10.5, 10.0, 11.5, 9.0, 10.2, 10.8, 9.8, 10.1, 11.0]
    values = list(base)
    values[5] = 80.0  # 尖峰
    n = len(values)
    rows = [
        (to_iso(end - timedelta(minutes=5 * (n - 1 - index))), float(value))
        for index, value in enumerate(values)
    ]
    conn.executemany("INSERT INTO t VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_test_run_returns_alerts(tmp_path):
    """试跑返回告警点 —— 而且**逐个列出**，不抽样。"""
    client, _store, job_id = _client(tmp_path)
    resp = client.post(f"/api/platform/jobs/{job_id}/test-run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_alerts"] >= 1
    assert len(body["alerts"]) == body["n_alerts"]
    alert = body["alerts"][0]
    for key in ("series_id", "timestamp", "value", "score", "severity", "level"):
        assert key in alert


def test_test_run_does_not_create_run_row(tmp_path):
    """⚠️ 试跑不落库 —— `runs` 表一行都不多。"""
    client, store, job_id = _client(tmp_path)
    before = len(store.all_runs())
    client.post(f"/api/platform/jobs/{job_id}/test-run")
    assert len(store.all_runs()) == before


def test_test_run_does_not_write_files(tmp_path):
    """⚠️ 试跑不落盘。"""
    client, _store, job_id = _client(tmp_path)
    runs_root = tmp_path / "cache" / "platform" / "runs"
    before = set(runs_root.iterdir()) if runs_root.exists() else set()
    client.post(f"/api/platform/jobs/{job_id}/test-run")
    after = set(runs_root.iterdir()) if runs_root.exists() else set()
    assert after == before


def test_test_run_returns_series_results(tmp_path):
    """每条序列都要有结果 —— 前端要画图。"""
    client, _store, job_id = _client(tmp_path)
    body = client.post(f"/api/platform/jobs/{job_id}/test-run").json()
    assert body["n_series"] == 1
    result = body["results"][0]
    for key in ("series_id", "timestamps", "values", "scores", "severity"):
        assert key in result
    assert len(result["timestamps"]) == len(result["values"])


def test_test_run_timestamps_are_readable_dates(tmp_path):
    """⚠️ 时间戳必须是**能读的日期**，不能是「五百年后」那种。

    ⚠️ 这个坑很隐蔽：结果里存的是 int64 **纳秒**，
       直接 `astype("datetime64[s]")` 会把纳秒当成秒 ——
       时间戳会变成 53870857431 年，界面上完全看不出错在哪。
       必须先转 `datetime64[ns]` 再转 `[s]`。
    """
    client, _store, job_id = _client(tmp_path)
    body = client.post(f"/api/platform/jobs/{job_id}/test-run").json()
    timestamps = body["results"][0]["timestamps"]
    assert timestamps, "应该有时间戳"
    for value in timestamps:
        # ⚠️ 断言「是 2026 年的 ISO 时间」——
        #   只断言「不是数字」的话，别的错法也能混过去
        assert value.startswith("2026-"), f"时间戳不该是 {value}"
        assert "T" in value


def test_试跑返回能力警告(tmp_path):
    # ⚠️ 前端 TestRunPanel 渲染的是 `results`（不是 `series`）—— 两处都要带
    client, _store, job_id = _client(tmp_path)
    body = client.post(f"/api/platform/jobs/{job_id}/test-run").json()
    caps = [item.get("capability") for item in body["results"]]
    assert caps and caps[0]["verdict"] in {"ok", "unsuitable", "undetermined"}
    # 前端据此判断「泊松 / 事件计数类算法是否适用」
    assert isinstance(caps[0]["count_ready"], bool)
    # `series` 与 `results` 是同一次探测的两份数据，结论必须一致
    assert body["series"][0]["capability"] == caps[0]


def _overwrite_series(tmp_path, values: list[float]) -> None:
    """把源库里的序列换成给定的值 —— 需要精确控制零值比例时用。"""
    path = tmp_path / "platform" / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM t")
    end = utcnow().replace(second=0, microsecond=0)
    n = len(values)
    rows = [
        (to_iso(end - timedelta(minutes=5 * (n - 1 - index))), float(value))
        for index, value in enumerate(values)
    ]
    conn.executemany("INSERT INTO t VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_零膨胀数据判定为不可用并给出_iqr_警告(tmp_path):
    """97.5% 以上是零 → IQR 退化为 0，必须明确指出这个算法不可靠。"""
    values = [0.0] * 60
    values[0] = 12.0
    client, _store, job_id = _client(tmp_path)
    _overwrite_series(tmp_path, values)

    body = client.post(f"/api/platform/jobs/{job_id}/test-run").json()
    capability = body["results"][0]["capability"]
    assert capability["verdict"] == "unsuitable"
    assert capability["zero_ratio"] == 1 - 1 / 60
    assert "iqr" in {item["detector"] for item in capability["warnings"]}


def test_无周期数据在试跑里提示季节性算法不适用(tmp_path):
    """零值率不高、但完全没有周期 —— 这时 seasonal / stl_residual 的前提不成立。"""
    rng = random.Random(0)
    values = [10.0 + rng.gauss(0, 2) for _ in range(200)]
    client, _store, job_id = _client(tmp_path)
    _overwrite_series(tmp_path, values)

    capacity = client.post(f"/api/platform/jobs/{job_id}/test-run").json()["results"][0][
        "capability"
    ]
    # ⚠️ 形态不适配不改变 verdict —— 数据本身没问题
    assert capacity["verdict"] == "ok"
    assert capacity["has_period"] is False
    names = {item["detector"] for item in capacity["shape_warnings"]}
    assert "seasonal" in names and "stl_residual" in names


def test_周期数据在试跑里提示趋势算法拟合不完整(tmp_path):
    rng = random.Random(1)
    # ⚠️ 任务窗口只有 60 点 —— 周期要选得让窗口里至少 3 个完整周期（此处 6 个）
    values = [10.0 + 3 * math.sin(2 * math.pi * index / 10) + rng.gauss(0, 0.3) for index in range(60)]
    client, _store, job_id = _client(tmp_path)
    _overwrite_series(tmp_path, values)

    capacity = client.post(f"/api/platform/jobs/{job_id}/test-run").json()["results"][0][
        "capability"
    ]
    assert capacity["has_period"] is True
    names = {item["detector"] for item in capacity["shape_warnings"]}
    assert "seasonal" not in names
    assert "trend_residual_iqr" in names and "theil_sen" in names


def test_test_run_unknown_job_returns_404(tmp_path):
    client, _store, _job_id = _client(tmp_path)
    assert client.post("/api/platform/jobs/9999/test-run").status_code == 404


def test_test_run_reports_failure_detail(tmp_path):
    """失败要把原因告诉调用方，而不是 500。"""
    client, _store, job_id = _client(tmp_path)
    # 把源库删掉 —— 取数会失败
    (tmp_path / "platform" / "source.db").unlink()
    resp = client.post(f"/api/platform/jobs/{job_id}/test-run")
    assert resp.status_code == 400
    assert resp.json()["detail"]
