"""`/api/badcases` 的基线三件套：向后兼容 + NaN 处理。

⚠️ **旧版落盘的 npz 没有基线键** —— 接口不能因此崩，要返回 null。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from anomaly_lab.data.loader import save_dataset
from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.web.app import create_app


@pytest.fixture
def series_id(tmp_path: Path, monkeypatch) -> str:
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    series = generate_series("stationary", n=60, seed=7)
    save_dataset([series], tmp_path / "synthetic")
    return series.series_id


def _write_npz(root: Path, series_id: str, detector: str, **extra) -> None:
    out = root / "cache" / "detections" / detector
    out.mkdir(parents=True, exist_ok=True)
    n = 60
    payload = {
        "scores": np.zeros(n),
        "is_anomaly": np.zeros(n, dtype=bool),
        "threshold": np.array(2.5),
        "score_type": np.array("zscore"),
        "detector": np.array(detector),
        "elapsed_ms": np.array(1.0),
    }
    payload.update(extra)
    np.savez(out / f"{series_id}.npz", **payload)


def test_legacy_npz_without_bands_returns_null(tmp_path: Path, series_id: str):
    """⚠️ 旧版落盘的 npz 没有 expected/lower/upper 键 —— 不能崩，返回 null。"""
    _write_npz(tmp_path, series_id, "iqr")
    client = TestClient(create_app())
    body = client.get("/api/badcases", params={"series_id": series_id}).json()
    assert body["baseline"] is None
    assert body["lower"] is None
    assert body["upper"] is None


def test_bands_are_returned_when_present(tmp_path: Path, series_id: str):
    _write_npz(
        tmp_path,
        series_id,
        "iqr",
        expected=np.ones(60),
        lower=np.zeros(60),
        upper=np.full(60, 2.0),
        band_kind=np.array("alert_boundary"),
    )
    client = TestClient(create_app())
    body = client.get("/api/badcases", params={"series_id": series_id}).json()
    assert body["baseline"] == pytest.approx([1.0] * 60)
    assert body["lower"] == pytest.approx([0.0] * 60)
    assert body["upper"] == pytest.approx([2.0] * 60)
    assert body["band_kind"] == "alert_boundary"


def test_nan_becomes_null_not_invalid_json(tmp_path: Path, series_id: str):
    """NaN 不是合法 JSON —— 必须转成 null（前端会断线，不画假基线）。"""
    lower = np.zeros(60)
    lower[10] = np.nan
    _write_npz(
        tmp_path,
        series_id,
        "iqr",
        expected=np.ones(60),
        lower=lower,
        upper=np.full(60, 2.0),
        band_kind=np.array("alert_boundary"),
    )
    client = TestClient(create_app())
    body = client.get("/api/badcases", params={"series_id": series_id}).json()
    assert body["lower"][10] is None
    assert body["lower"][9] == pytest.approx(0.0)


def test_empty_band_arrays_are_treated_as_absent(tmp_path: Path, series_id: str):
    """没有基线的检测器存空数组 —— 长度不对齐，不能当成有带。"""
    _write_npz(
        tmp_path,
        series_id,
        "iqr",
        expected=np.asarray([]),
        lower=np.asarray([]),
        upper=np.asarray([]),
        band_kind=np.array(""),
    )
    client = TestClient(create_app())
    body = client.get("/api/badcases", params={"series_id": series_id}).json()
    assert body["baseline"] is None
    assert body["lower"] is None
    assert body["upper"] is None
    assert body["band_kind"] is None
