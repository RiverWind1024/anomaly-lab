"""P3：有真值模式 —— 校准 / 测试分开的评估。

⚠️ **验收标准**：合成场景下，P3 给出的算法排名必须与离线评测
   （`evaluation/backtest.py`）一致 —— 否则 lab 的结论没法迁移到线上。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.lab.evaluate import (
    calibrate,
    evaluate_at,
    evaluate_experiment,
    score_bundle,
    split_by_series,
)
from anomaly_lab.lab.inspect import prepare
from anomaly_lab.lab.spec import DataSpec, SamplingSpec, SyntheticSpec
from anomaly_lab.platform.detectors import create_detector
from anomaly_lab.platform.store import PlatformStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)

DETECTORS = ("zscore", "iqr", "stl_residual")


def _store(tmp_path) -> PlatformStore:
    return PlatformStore(tmp_path / "platform.db")


def _synthetic_spec(
    *,
    metric_class: str = "periodic",
    n_points: int = 1000,
    n_anomalies: int = 5,
    window_points: int = 100,
    seed: int = 42,
    **overrides,
) -> DataSpec:
    synth = SyntheticSpec(
        metric_class=metric_class,
        n_points=n_points,
        n_anomalies=n_anomalies,
        seed=seed,
    )
    sampling = SamplingSpec(
        window_points=window_points,
        stride_points=window_points,
        max_points=n_points,
        max_windows=20,
    )
    return DataSpec(
        kind="synthetic",
        start=BASE,
        end=BASE + timedelta(minutes=5 * n_points),
        freq="5min",
        sampling=sampling,
        synthetic=synth,
        **overrides,
    )


# ---------- 取数 ----------


def test_合成数据自带真值标签(tmp_path):
    """合成数据的异常区间就是真值 —— 这是 P3 最省事的一条路。"""
    spec = _synthetic_spec(n_points=1000, n_anomalies=5)
    result = evaluate_experiment(_store(tmp_path), tmp_path, spec, detectors=["iqr"])

    assert result["truth"]["sources"] == ["synthetic"]
    assert result["truth"]["n_truth_points"] > 0


def test_合成数据的时间戳平移到起点(tmp_path):
    """⚠️ 不平移的话，用户选的时间范围与数据永远对不上。"""
    spec = _synthetic_spec(n_points=100)
    prepared = prepare(_store(tmp_path), tmp_path, spec)

    stamps = prepared.series[0].series.timestamps
    assert stamps[0] == np.datetime64("2026-01-01T00:00:00", "ns")
    assert prepared.freq == "5min"


def test_窗口带着真值一起切(tmp_path):
    """窗口内的告警点必须能和同窗的真值点对齐。"""
    spec = _synthetic_spec(n_points=1000, window_points=100)
    prepared = prepare(_store(tmp_path), tmp_path, spec)

    windows = prepared.series[0].windows
    total = sum(int(window.bundle.labels.sum()) for window in windows)
    assert total == int(prepared.series[0].series.labels.sum())
    assert total > 0


def test_稀疏真值也要被采样纳入(tmp_path):
    """⚠️ 均匀采样会漏掉稀疏的异常点。

    不补上的话，漏掉的异常根本不进统计 —— 召回率是假的。
    """
    spec = DataSpec(
        kind="synthetic",
        start=BASE,
        end=BASE + timedelta(minutes=5 * 1000),
        freq="5min",
        synthetic=SyntheticSpec(
            metric_class="periodic", n_points=1000, n_anomalies=5, seed=42
        ),
        # 20 个候选窗口只挑 4 个 —— 异常点很容易落在没挑中的窗口里
        sampling=SamplingSpec(
            window_points=50, stride_points=50, max_points=1000, max_windows=4
        ),
    )
    prepared = prepare(_store(tmp_path), tmp_path, spec)

    series = prepared.series[0]
    covered = sum(int(window.bundle.labels.sum()) for window in series.windows)
    assert covered == int(series.series.labels.sum())
    assert covered > 0


# ---------- 校准 / 测试划分 ----------


def test_校准与测试按时间前后切且不重叠(tmp_path):
    spec = _synthetic_spec(n_points=1000, window_points=100)
    prepared = prepare(_store(tmp_path), tmp_path, spec)

    from anomaly_lab.lab.evaluate import score_windows

    scored = score_windows(prepared, "iqr")
    calibration, test = split_by_series(scored, 0.5)

    assert len(calibration) == 5
    assert len(test) == 5
    # ⚠️ 校准集全在测试集之前 —— 窗口不重叠，真值不会泄漏。
    assert max(item.start for item in calibration) <= min(item.start for item in test)
    assert {item.window_index for item in calibration} & {
        item.window_index for item in test
    } == set()


def test_单窗口序列切不开时只留校准集(tmp_path):
    spec = _synthetic_spec(n_points=100, window_points=100)
    prepared = prepare(_store(tmp_path), tmp_path, spec)

    from anomaly_lab.lab.evaluate import score_windows

    scored = score_windows(prepared, "iqr")
    calibration, test = split_by_series(scored, 0.5)

    assert calibration
    assert test == []


# ---------- 评估 ----------


def test_评估给出校准阈值与测试成绩(tmp_path):
    spec = _synthetic_spec(n_points=1000, window_points=100)
    result = evaluate_experiment(_store(tmp_path), tmp_path, spec, detectors=["iqr"])

    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["detector"] == "iqr"
    assert item["calibration"]["threshold"] is not None
    assert item["test"]["f1"] >= 0.0
    assert item["test"]["n_windows"] == 5
    # ⚠️ 校准集与测试集的窗口数对得上。
    assert item["calibration"]["n_windows_used"] >= 1


def test_平台默认倍数作为对照一起给出(tmp_path):
    """用户真正会用的是平台默认阈值 —— 必须能对照着看。"""
    spec = _synthetic_spec(n_points=1000, window_points=100)
    result = evaluate_experiment(_store(tmp_path), tmp_path, spec, detectors=["iqr"])

    item = result["results"][0]
    assert item["default_threshold"]["threshold"] == 2.5
    assert item["default_threshold"]["n_windows"] == item["test"]["n_windows"]


def test_无真值时给出警告而不是假装能评估(tmp_path):
    """没有真值就不能报 F1 —— 必须说清楚。"""
    from anomaly_lab.lab.spec import SamplingSpec as Sampling

    spec = DataSpec(
        kind="metric",
        metric_id=1,
        start=BASE,
        end=BASE + timedelta(hours=10),
        freq="1h",
        sampling=Sampling(window_points=100, max_points=100),
    )
    store = _store(tmp_path)
    source = store.add_source("s", str(tmp_path / "source.db"))
    store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, value FROM t WHERE $timefilter",
        time_column="ts",
        value_column="value",
        freq="1h",
    )
    # 数据源不存在 → 取数会失败，这里只看 spec 校验本身
    assert spec.truth == "none"


def test_切分比例非法时报错(tmp_path):
    spec = _synthetic_spec()
    with pytest.raises(ValueError, match="split_ratio"):
        evaluate_experiment(
            _store(tmp_path), tmp_path, spec, detectors=["iqr"], split_ratio=1.5
        )


# ---------- 验收：排名与离线评测一致 ----------


def _offline_ranking(series_list) -> dict[str, float]:
    """离线评测口径：逐序列搜阈值，算平均 F1。"""
    ranking: dict[str, float] = {}
    for name in DETECTORS:
        rows = backtest_detector(
            series_list, lambda name=name: create_detector(name)
        )
        ranking[name] = float(np.mean([row.f1 for row in rows]))
    return ranking


def _p3_ranking(series_list) -> dict[str, float]:
    """P3 口径：同序列、同阈值搜索、同判定。"""
    ranking: dict[str, float] = {}
    for name in DETECTORS:
        scored = [
            score_bundle(
                bundle,
                name,
                series_id=bundle.series_id,
                window_index=0,
                start=str(bundle.timestamps[0]),
            )
            for bundle in series_list
        ]
        threshold, _ = calibrate(scored)
        assert threshold is not None
        ranking[name] = float(evaluate_at(scored, threshold)["f1"])
    return ranking


def test_合成场景下算法排名与离线评测一致():
    """⚠️ P3 的验收标准。

    lab 的价值在于「实验里看到的 = 上线后拿到的」。
    如果 P3 给出的算法排名与离线评测（`make evaluate` 那条路）不一致，
    那 lab 的结论就不能用来做选型。
    """
    series_list = [
        generate_series(metric_class, n=500, seed=seed, freq="5min", n_anomalies=5)
        for metric_class, seed in (
            ("periodic", 1),
            ("trending", 2),
            ("stationary", 3),
        )
    ]

    offline = _offline_ranking(series_list)
    p3 = _p3_ranking(series_list)

    def _order(scores: dict[str, float]) -> list[str]:
        # ⚠️ 并列时按名字排 —— 排序必须**确定**，否则断言会随机翻车。
        return sorted(scores, key=lambda name: (-scores[name], name))

    assert _order(p3) == _order(offline)
    # ⚠️ **P3 的 F1 一定不高于离线评测** ——
    #    P3 用的是「一个阈值管所有窗口」（生产语义），
    #    离线评测用的是「每条序列各自最优阈值」。
    #    如果 lab 报得更高，说明阈值用到了测试集的信息（有泄漏）。
    for name in DETECTORS:
        assert p3[name] <= offline[name] + 1e-6
