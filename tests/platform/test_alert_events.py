"""告警事件：把逐点 severity 合并成连续区间。"""

from __future__ import annotations

import numpy as np

from anomaly_lab.platform.alert_events import events_from_series, merge_alert_intervals


def test_single_alert_point_becomes_one_interval():
    intervals = merge_alert_intervals(np.array([0, 0, 1, 0, 0]))
    assert intervals == [(2, 2, 1)]


def test_consecutive_alert_points_merge_into_one_interval():
    intervals = merge_alert_intervals(np.array([0, 1, 1, 1, 0]))
    assert intervals == [(1, 3, 1)]


def test_normal_point_between_alerts_splits_intervals():
    intervals = merge_alert_intervals(np.array([1, 1, 0, 1, 1]))
    assert intervals == [(0, 1, 1), (3, 4, 1)]


def test_interval_level_is_the_maximum_severity_inside_it():
    intervals = merge_alert_intervals(np.array([1, 2, 1, 0]))
    assert intervals == [(0, 2, 2)]


def test_no_alert_yields_no_interval():
    assert merge_alert_intervals(np.array([0, 0, 0])) == []


def test_severity_zero_is_normal_not_alert():
    # severity 是 int16，0 = 正常；负数不存在但也不该被当成告警
    assert merge_alert_intervals(np.array([0, -1, 0])) == []


def test_empty_input_yields_no_interval():
    assert merge_alert_intervals(np.array([], dtype="int16")) == []


def _events(severity, scores, levels=("正常", "P1", "P0")):
    return events_from_series(
        severity=np.asarray(severity, dtype="int16"),
        timestamps=np.arange(len(severity)).astype("datetime64[m]"),
        scores=np.asarray(scores, dtype=float),
        levels=list(levels),
        job_id=1,
        job_name="demo-job",
        metric_id=2,
        metric_name="demo-metric",
        series_id="demo-metric:web-api",
        group="web-api",
        detector="iqr",
        score_type="zscore",
        run_id=7,
    )


def test_event_carries_interval_bounds_and_peak_score():
    events = _events([0, 1, 1, 0, 2], [0.1, 0.5, 0.9, 0.2, 1.5])
    assert len(events) == 2
    first = events[0]
    assert first.start_ts == "1970-01-01T00:01:00"
    assert first.end_ts == "1970-01-01T00:02:00"
    assert first.n_points == 2
    assert first.max_score == 0.9
    assert first.level_index == 1
    assert first.level == "P1"


def test_event_level_name_comes_from_levels_table():
    events = _events([0, 2], [0.1, 1.0])
    assert events[0].level_index == 2
    assert events[0].level == "P0"


def test_event_level_falls_back_when_index_out_of_range():
    """档位表比实际严重度短时不能崩 —— 退回「未知」而不是 IndexError。"""
    events = _events([0, 2], [0.1, 1.0], levels=("正常", "P1"))
    assert events[0].level == "未知"
    assert events[0].level_index == 2


def test_event_carries_job_and_series_identity():
    events = _events([0, 1], [0.1, 1.0])
    event = events[0]
    assert event.job_id == 1
    assert event.job_name == "demo-job"
    assert event.metric_id == 2
    assert event.metric_name == "demo-metric"
    assert event.series_id == "demo-metric:web-api"
    assert event.group == "web-api"
    assert event.detector == "iqr"
    assert event.score_type == "zscore"
    assert event.run_id == 7
