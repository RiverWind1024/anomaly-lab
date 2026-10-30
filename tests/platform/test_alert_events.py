"""告警事件：把逐点 severity 合并成连续区间。"""

from __future__ import annotations

import numpy as np

from anomaly_lab.platform.alert_events import merge_alert_intervals


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
