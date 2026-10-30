"""Chronos 接入平台：能力探测、创建校验、对比跳过。

⚠️ 这些测试**不依赖本机是否装了 chronos** —— 可用性一律用 monkeypatch
固定成 True / False 两种状态，避免「有 chronos 的机器过、没装的机器挂」。
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from anomaly_lab.platform.detectors import (
    DETECTOR_FACTORIES,
    detector_available,
    detector_catalog,
)
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso, utcnow
from anomaly_lab.web.app import create_app

CHRONOS = "chronos"


@pytest.fixture
def unavailable(monkeypatch):
    """把 chronos 固定成「不可用」。"""
    monkeypatch.setattr(
        "anomaly_lab.detectors.chronos.chronos_available", lambda: False
    )


@pytest.fixture
def available(monkeypatch):
    """把 chronos 固定成「可用」。"""
    monkeypatch.setattr(
        "anomaly_lab.detectors.chronos.chronos_available", lambda: True
    )


def _client(tmp_path):
    db = tmp_path / "platform" / "source.db"
    db.parent.mkdir()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, host TEXT, value REAL)")
    start = utcnow() - timedelta(minutes=5 * 61)
    for i in range(61):
        conn.execute(
            "INSERT INTO metrics VALUES (?, ?, ?)",
            (to_iso(start + timedelta(minutes=5 * i)), "a", float(i % 10)),
        )
    conn.commit()
    conn.close()
    store = PlatformStore(tmp_path / "platform.db")
    app = create_app(platform_store=store, platform_data_root=tmp_path)
    return TestClient(app), store


def _make_job(client, detector: str):
    """建好 source/metric，再建一个任务，返回建任务的响应。"""
    source = client.post(
        "/api/platform/sources", json={"name": "local", "path": "platform/source.db"}
    ).json()
    metric = client.post(
        "/api/platform/metrics",
        json={
            "source_id": source["id"],
            "name": "m",
            "query": "SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
            "time_column": "ts",
            "value_column": "value",
            "group_column": "host",
            "time_format": "iso_utc",
            "freq": "5min",
        },
    ).json()
    return client.post(
        "/api/platform/jobs",
        json={
            "metric_id": metric["id"],
            "name": "j",
            "detector": detector,
            "window_points": 60,
            "interval_seconds": 300,
        },
    )


# ---------- 注册表 ----------


def test_chronos_is_registered():
    """Chronos 进平台注册表。"""
    assert CHRONOS in DETECTOR_FACTORIES


def test_catalog_marks_availability_and_slow_flag(available):
    """catalog 要告诉前端「能不能用」和「慢不慢」。"""
    rows = {row["name"]: row for row in detector_catalog()}
    assert CHRONOS in rows
    assert rows[CHRONOS]["available"] is True
    assert rows[CHRONOS]["reason"] is None
    # 慢 —— 2 秒/序列，定时任务要留足间隔
    assert rows[CHRONOS]["slow"] is True
    # 其余算法恒可用
    assert rows["iqr"]["available"] is True
    assert rows["iqr"]["slow"] is False


def test_catalog_reports_unavailable_with_reason(unavailable):
    rows = {row["name"]: row for row in detector_catalog()}
    assert rows[CHRONOS]["available"] is False
    assert rows[CHRONOS]["reason"]


def test_detector_available_statistical_always_true():
    assert detector_available("iqr") == (True, None)


def test_detector_available_unknown_name():
    ok, reason = detector_available("不存在的算法")
    assert ok is False
    assert reason


def test_default_detector_set_excludes_slow_detectors():
    """「遍历整个注册表」的地方不能带上慢模型。

    离线评测（validate_auto）与算法建议的兜底列表都用这个集合 ——
    带上 Chronos 会让一次评测从几秒变成十几分钟，还把慢算法塞进给用户的建议。
    """
    from anomaly_lab.platform.detectors import DEFAULT_DETECTOR_SET, SLOW_DETECTORS

    assert not set(DEFAULT_DETECTOR_SET) & SLOW_DETECTORS
    assert "iqr" in DEFAULT_DETECTOR_SET
    assert "chronos" in DETECTOR_FACTORIES  # 仍然可选，只是不在默认集合里


# ---------- 建任务 ----------


def test_create_job_with_chronos_when_unavailable_returns_400(tmp_path, unavailable):
    client, _ = _client(tmp_path)
    resp = _make_job(client, CHRONOS)
    assert resp.status_code == 400
    assert "chronos" in resp.json()["detail"]


def test_create_job_with_chronos_when_available_ok(tmp_path, available):
    client, _ = _client(tmp_path)
    resp = _make_job(client, CHRONOS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["detector"] == CHRONOS


# ---------- 对比 ----------


def test_compare_skips_unavailable_chronos(tmp_path, unavailable):
    """勾了不可用的算法 → 跳过并说明原因，不整个失败。"""
    client, _ = _client(tmp_path)
    job = _make_job(client, "iqr").json()
    resp = client.get(
        f"/api/platform/jobs/{job['id']}/compare?detectors=iqr,{CHRONOS}"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["name"] for item in body["detectors"]] == ["iqr"]
    assert body["skipped"]
    assert body["skipped"][0]["name"] == CHRONOS
    assert body["skipped"][0]["reason"]


def test_compare_only_unavailable_returns_400(tmp_path, unavailable):
    client, _ = _client(tmp_path)
    job = _make_job(client, "iqr").json()
    resp = client.get(f"/api/platform/jobs/{job['id']}/compare?detectors={CHRONOS}")
    assert resp.status_code == 400
    assert resp.headers.get("X-Anomaly-Biz-State") == "no_algorithms"


# ---------- auto 不会选 chronos ----------


def test_auto_never_picks_chronos():
    """auto 按形态推荐，候选里没有预训练模型 —— 不该被顺手带进来。"""
    import numpy as np

    from anomaly_lab.contracts import SeriesBundle
    from anomaly_lab.platform.detectors import AUTO_DETECTOR, resolve_detector

    series = SeriesBundle(
        series_id="demo",
        values=np.arange(100, dtype=float),
        timestamps=np.arange(
            "2026-01-01T00:00:00", "2026-01-01T01:40:00", dtype="datetime64[m]"
        ),
        freq="5min",
    )
    resolution = resolve_detector(AUTO_DETECTOR, series)
    assert resolution.detector != CHRONOS
    assert CHRONOS not in resolution.candidates
