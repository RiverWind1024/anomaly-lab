from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.evaluation.badcases import attribute_badcases


def test_backtest_returns_one_row_per_series():
    series = [
        generate_series(c, n=300, seed=60 + i)
        for i, c in enumerate(["stationary", "periodic", "trending"])
    ]
    rows = backtest_detector(series, IQRDetector)
    assert len(rows) == 3
    for r in rows:
        assert 0.0 <= r.precision <= 1.0
        assert 0.0 <= r.recall <= 1.0
        assert r.n_truth > 0
        assert r.elapsed_ms >= 0


def test_backtest_rows_carry_time_range_and_source():
    """回测记录要带时间范围与来源维度 —— 前端按它们筛选与聚合。"""
    series = [generate_series("stationary", n=300, seed=71)]
    row = backtest_detector(series, IQRDetector)[0]
    assert row.start_ts and row.end_ts
    assert row.start_ts <= row.end_ts
    # 秒精度（不带纳秒）—— 前端按字符串比时间，格式必须统一
    assert len(row.start_ts) == 19
    assert row.source


def test_badcase_attribution_produces_reasons():
    s = generate_series(
        "periodic", n=600, seed=61, n_anomalies=1, anomaly_types=["spike"]
    )
    result = IQRDetector().fit(s).detect(s)
    cases = attribute_badcases(s, result)
    assert isinstance(cases, list)
    for c in cases:
        assert c.kind in {"false_positive", "false_negative"}
        assert c.reason
        assert c.indices is not None


def test_badcase_reasons_are_grouped_by_shape():
    s = generate_series("stationary", n=600, seed=63, n_anomalies=2)
    result = IQRDetector().fit(s).detect(s)
    cases = attribute_badcases(s, result)
    kinds = {c.group for c in cases}
    assert all(k for k in kinds)
