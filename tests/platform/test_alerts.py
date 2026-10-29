"""告警后处理：规则表 → 等级档位。"""

import numpy as np
import pytest

from anomaly_lab.platform.alerts import (
    AlertRule,
    band_multiplier,
    default_rules,
    highest_multiplier,
    parse_rules,
    severity_from_conditions,
)


def test_rules_keep_input_order_as_severity_order():
    """规则表顺序即档位顺序（从低到高严重），不再按倍数重排。"""
    rules = parse_rules([{"multiplier": 3.0, "level": "P1"}, {"multiplier": 1.0, "level": "P2"}])
    assert [rule.multiplier for rule in rules] == [3.0, 1.0]
    assert [rule.level for rule in rules] == ["P1", "P2"]


def test_severity_picks_the_highest_matching_rule():
    rules = [AlertRule(level="P2", multiplier=1.0), AlertRule(level="P1", multiplier=3.0)]
    scores = np.array([0.5, 1.5, 2.9, 3.0, 5.0])
    severity = severity_from_conditions(scores, None, rules)
    assert list(severity) == [0, 1, 1, 2, 2]


def test_default_rules_keep_old_two_threshold_semantics():
    rules = default_rules(2.5, 4.0)
    assert [(rule.multiplier, rule.level) for rule in rules] == [
        (2.5, "P1"),
        (4.0, "P0"),
    ]
    scores = np.array([2.0, 3.0, 4.5])
    assert list(severity_from_conditions(scores, None, rules)) == [0, 1, 2]


def test_band_uses_the_lowest_multiplier():
    rules = [AlertRule(level="P2", multiplier=1.0), AlertRule(level="P1", multiplier=3.0)]
    assert band_multiplier(rules) == 1.0
    assert highest_multiplier(rules) == 3.0


def test_invalid_rule_is_rejected():
    with pytest.raises(ValueError, match="level"):
        parse_rules([{"multiplier": 1.0}])
    with pytest.raises(ValueError, match="multiplier"):
        parse_rules([{"multiplier": 0, "level": "P1"}])
    with pytest.raises(ValueError, match="op"):
        parse_rules([{"op": "=", "value": 5, "level": "P1"}])
    with pytest.raises(ValueError, match="multiplier"):
        parse_rules([{"level": "P1"}])


def test_absolute_condition_raises_the_level():
    """绝对值条件与倍数条件并行：值 > 50 直接抬到该档。"""
    rules = parse_rules(
        [
            {"multiplier": 1.0, "level": "P2"},
            {"op": ">", "value": 50, "level": "P1"},
        ]
    )
    scores = np.array([0.2, 0.2, 0.2])
    values = np.array([10.0, 50.0, 80.0])
    severity = severity_from_conditions(scores, values, rules)
    # 分数都没到 1 倍，但 80 > 50 → 抬到 P1（档位 2）；50 不满足「>」→ 仍是 P2
    assert list(severity) == [0, 0, 2]


def test_absolute_condition_never_lowers_the_score_level():
    """绝对值条件只抬不压：分数判到 P1 的点不会被绝对值条件压回 P2。"""
    rules = parse_rules(
        [
            {"op": ">", "value": 50, "level": "P2"},
            {"multiplier": 3.0, "level": "P1"},
        ]
    )
    scores = np.array([0.0, 5.0])
    values = np.array([80.0, 80.0])
    severity = severity_from_conditions(scores, values, rules)
    assert list(severity) == [1, 2]


def test_absolute_condition_supports_all_comparators():
    rules = parse_rules(
        [
            {"op": "<", "value": 0, "level": "P2"},
            {"op": ">=", "value": 100, "level": "P1"},
        ]
    )
    scores = np.zeros(4)
    values = np.array([-1.0, 1.0, 100.0, 200.0])
    severity = severity_from_conditions(scores, values, rules)
    assert list(severity) == [1, 0, 2, 2]


def test_band_requires_at_least_one_multiplier_rule():
    """纯绝对值规则无法定出上下界宽度，必须显式报错而不是静默。"""
    rules = parse_rules([{"op": ">", "value": 50, "level": "P1"}])
    with pytest.raises(ValueError, match="倍数规则"):
        band_multiplier(rules)
    assert highest_multiplier(rules) is None


def test_rules_round_trip_through_dicts():
    raw = [
        {"multiplier": 1.0, "level": "P2"},
        {"op": ">", "value": 50, "level": "P1"},
    ]
    rules = parse_rules(raw)
    assert [rule.as_dict() for rule in rules] == raw
