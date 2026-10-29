"""告警规则表：以异常分数为准，按「倍数 → 等级」判级。"""

import numpy as np
import pytest

from anomaly_lab.platform.alerts import (
    AlertRule,
    band_multiplier,
    default_rules,
    parse_rules,
    severity_from_scores,
)


def test_rules_are_sorted_by_multiplier():
    rules = parse_rules([{"multiplier": 3.0, "level": "P1"}, {"multiplier": 1.0, "level": "P2"}])
    assert [rule.multiplier for rule in rules] == [1.0, 3.0]
    assert [rule.level for rule in rules] == ["P2", "P1"]


def test_severity_picks_the_highest_matching_rule():
    rules = [AlertRule(1.0, "P2"), AlertRule(3.0, "P1")]
    scores = np.array([0.5, 1.5, 2.9, 3.0, 5.0])
    severity = severity_from_scores(scores, rules)
    assert list(severity) == [0, 1, 1, 2, 2]


def test_default_rules_keep_old_two_threshold_semantics():
    rules = default_rules(2.5, 4.0)
    assert [(rule.multiplier, rule.level) for rule in rules] == [
        (2.5, "P1"),
        (4.0, "P0"),
    ]
    scores = np.array([2.0, 3.0, 4.5])
    assert list(severity_from_scores(scores, rules)) == [0, 1, 2]


def test_band_uses_the_lowest_rule():
    rules = [AlertRule(1.0, "P2"), AlertRule(3.0, "P1")]
    assert band_multiplier(rules) == 1.0


def test_invalid_rule_is_rejected():
    with pytest.raises(ValueError, match="level"):
        parse_rules([{"multiplier": 1.0}])
    with pytest.raises(ValueError, match="multiplier"):
        parse_rules([{"multiplier": 0, "level": "P1"}])
