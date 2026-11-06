"""告警方向：偏低 / 偏高 / 双向。"""

import numpy as np
import pytest

from anomaly_lab.platform.alerts import apply_direction, parse_direction


def test_方向解析与校验():
    assert parse_direction(None) == "both"
    assert parse_direction("above") == "above"
    with pytest.raises(ValueError, match="告警方向"):
        parse_direction("up")


def test_above只保留高于基线的告警():
    severity = np.array([0, 2, 3, 0])
    values = np.array([10.0, 12.0, 8.0, 10.0])
    baseline = np.array([10.0, 10.0, 10.0, 10.0])
    out, applied = apply_direction(severity, values, baseline, "above")
    assert applied is True
    assert list(out) == [0, 2, 0, 0]


def test_below只保留低于基线的告警():
    severity = np.array([0, 2, 3, 0])
    values = np.array([10.0, 12.0, 8.0, 10.0])
    baseline = np.array([10.0, 10.0, 10.0, 10.0])
    out, applied = apply_direction(severity, values, baseline, "below")
    assert applied is True
    assert list(out) == [0, 0, 3, 0]


def test_both不改变结果():
    severity = np.array([0, 2, 3])
    out, applied = apply_direction(severity, np.zeros(3), None, "both")
    assert applied is True
    assert list(out) == [0, 2, 3]


def test_无基线时below一条都不报():
    """⚠️ 计数型检测器的分数只衡量偏高 —— 配了 below 必须不报，不能退化成双向。"""
    severity = np.array([0, 2, 3])
    out, applied = apply_direction(severity, np.array([0.0, 1.0, 5.0]), None, "below")
    assert applied is False
    assert not out.any()


def test_无基线时above保持原样():
    severity = np.array([0, 2, 3])
    out, applied = apply_direction(severity, np.array([0.0, 1.0, 5.0]), None, "above")
    assert applied is True
    assert list(out) == [0, 2, 3]


def test_基线长度不符时不假装过滤过():
    """长度对不上说明检测器坏了 —— 原样返回并标记未过滤，不能宣称已按方向筛过。"""
    severity = np.array([0, 2, 3])
    out, applied = apply_direction(severity, np.arange(3.0), np.array([10.0]), "above")
    assert applied is False
    assert list(out) == [0, 2, 3]
