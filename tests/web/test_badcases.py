"""`/api/badcases` 的 `detector` 参数：默认兼容 + 路径穿越防护。

⚠️ 一条检测记录是 **序列 × 算法** —— 端点必须能按算法取到对应的那份结果，
   否则列表里点了「mad」看到的还是 iqr 的。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from anomaly_lab.data.loader import save_dataset
from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.web.app import create_app
from anomaly_lab.web.biz_state import BIZ_STATE_HEADER


@pytest.fixture
def dataset(tmp_path: Path, monkeypatch) -> str:
    """一套最小数据集 + 两个算法（iqr / mad）的检测结果。"""
    monkeypatch.setenv("ANOMALY_LAB_DATA_DIR", str(tmp_path))
    series = generate_series("stationary", n=60, seed=7)
    save_dataset([series], tmp_path / "synthetic")
    # 两个算法的阈值故意不同 —— 测「读到的是不是请求的那个算法」
    for detector, threshold in (("iqr", 2.5), ("mad", 9.0)):
        out = tmp_path / "cache" / "detections" / detector
        out.mkdir(parents=True, exist_ok=True)
        np.savez(
            out / f"{series.series_id}.npz",
            scores=np.zeros(len(series.values)),
            is_anomaly=np.zeros(len(series.values), dtype=bool),
            threshold=np.array(threshold),
            score_type=np.array("zscore"),
            detector=np.array(detector),
            elapsed_ms=np.array(1.0),
        )
    return series.series_id


def test_badcases_defaults_to_iqr(dataset: str):
    """⚠️ 老调用方（不带 detector）行为不变。"""
    client = TestClient(create_app())
    body = client.get("/api/badcases", params={"series_id": dataset}).json()
    assert body["detector"] == "iqr"
    assert body["threshold"] == pytest.approx(2.5)


def test_badcases_honours_detector(dataset: str):
    """请求 mad → 读到 mad 的那份结果，不是 iqr 的。"""
    client = TestClient(create_app())
    body = client.get(
        "/api/badcases", params={"series_id": dataset, "detector": "mad"}
    ).json()
    assert body["detector"] == "mad"
    assert body["threshold"] == pytest.approx(9.0)


@pytest.mark.parametrize(
    "detector",
    [
        "../../etc",
        "..",
        "a/b",
        "iqr.detector",
        "iqr detector",
        "",
    ],
)
def test_badcases_rejects_illegal_detector(dataset: str, detector: str):
    """⚠️ `detector` 会拼进文件路径 —— 不校验就是路径穿越。

    必须是 **400**（用户配错了），不能是 404（路径没找到）
    也不能是 500（服务端炸了）。
    """
    client = TestClient(create_app())
    resp = client.get(
        "/api/badcases", params={"series_id": dataset, "detector": detector}
    )
    assert resp.status_code == 400


def test_badcases_unknown_detector_is_business_state(dataset: str):
    """算法名合法但没有结果 → 业务态空态（404 + 响应头），不是红色错误框。"""
    client = TestClient(create_app())
    resp = client.get(
        "/api/badcases", params={"series_id": dataset, "detector": "nope"}
    )
    assert resp.status_code == 404
    assert resp.headers.get(BIZ_STATE_HEADER) == "no_result"


def test_badcases_unknown_series_is_404(dataset: str):
    client = TestClient(create_app())
    resp = client.get("/api/badcases", params={"series_id": "no-such-series"})
    assert resp.status_code == 404
    assert resp.headers.get(BIZ_STATE_HEADER) is None
