"""自动推荐算法的质量验证。"""

import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.evaluation.auto_validation import validate_auto


def _bundle(values: list[float], labels: list[int] | None = None) -> SeriesBundle:
    n = len(values)
    truth = None
    if labels is not None:
        truth = np.asarray(labels, dtype=np.int8)
    return SeriesBundle(
        series_id="s",
        values=np.asarray(values, dtype=float),
        timestamps=np.arange(n).astype("datetime64[ns]"),
        freq="5min",
        labels=truth,
    )


def _periodic_with_spike(n: int = 200) -> list[float]:
    t = np.arange(n)
    values = np.sin(2 * np.pi * t / 24)
    values[100] = 50.0
    return values.tolist()


def test_validation_reports_per_detector_means():
    series = _bundle(_periodic_with_spike(), [0] * 100 + [1] + [0] * 99)
    report = validate_auto([series])
    assert len(report.rows) == 1
    assert set(report.detector_mean_f1) == {
        "iqr",
        "mad",
        "zscore",
        "seasonal",
        "stl_residual",
        "deseasonalized_iqr",
    }
    for score in report.detector_mean_f1.values():
        assert 0.0 <= score <= 1.0


def test_validation_compares_auto_against_fixed_baselines():
    series = _bundle(_periodic_with_spike(), [0] * 100 + [1] + [0] * 99)
    report = validate_auto([series], baseline_detector="iqr")
    assert report.baseline_detector == "iqr"
    assert report.best_fixed_detector in report.detector_mean_f1
    assert 0.0 <= report.auto_top1_rate <= 1.0
    assert 0.0 <= report.fallback_rate <= 1.0


def test_series_without_labels_are_skipped():
    unlabeled = _bundle(_periodic_with_spike())
    with pytest.raises(ValueError, match="标签"):
        validate_auto([unlabeled])


def test_series_without_anomalies_are_skipped():
    normal = _bundle(_periodic_with_spike(), [0] * 200)
    with pytest.raises(ValueError, match="标签"):
        validate_auto([normal])


def test_auto_choice_is_recorded_per_series():
    series = _bundle(_periodic_with_spike(), [0] * 100 + [1] + [0] * 99)
    report = validate_auto([series])
    row = report.rows[0]
    assert row.auto_detector in report.detector_mean_f1
    assert row.ranks[row.auto_detector] >= 1
    assert row.metric_class


def test_tied_detectors_share_the_same_rank():
    """并列时名次相同，且下一个名次跳号（标准竞赛排名）。"""
    from anomaly_lab.evaluation.auto_validation import _ranks

    ranks = _ranks({"a": 0.5, "b": 0.5, "c": 0.2})
    assert ranks["a"] == 1
    assert ranks["b"] == 1
    assert ranks["c"] == 3


def test_short_series_falls_back_and_records_it():
    """点数太少时形态推断不可靠，必须如实回退并记录。"""
    short = _bundle([1.0, 2.0, 3.0], [0, 0, 1])
    report = validate_auto([short])
    assert report.rows[0].fallback is True
    assert report.fallback_rate == 1.0
