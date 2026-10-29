"""告警规则：以异常分数为准，用「倍数 → 等级」的一组规则判级。

用户视角：缩放因子（scaleFactor）决定敏感度，规则表决定哪个敏感度对应哪个等级。
例：1 倍 → P2，3 倍 → P1。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SEVERITY_NORMAL = 0


@dataclass(frozen=True)
class AlertRule:
    multiplier: float
    level: str

    def as_dict(self) -> dict:
        return {"multiplier": float(self.multiplier), "level": self.level}


def parse_rules(raw: object) -> list[AlertRule]:
    """把存储/接口里的规则列表解析成 AlertRule 列表（按倍数升序）。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        import json

        raw = json.loads(raw)
    rules: list[AlertRule] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("告警规则必须是对象列表")
        multiplier = float(item.get("multiplier", 0))
        level = str(item.get("level", "")).strip()
        if not level:
            raise ValueError("告警规则缺少 level")
        if not np.isfinite(multiplier) or multiplier <= 0:
            raise ValueError(f"告警规则的 multiplier 必须为正数: {multiplier}")
        rules.append(AlertRule(multiplier=multiplier, level=level))
    if not rules:
        raise ValueError("至少需要一条告警规则")
    rules.sort(key=lambda rule: rule.multiplier)
    return rules


def rules_to_dicts(rules: list[AlertRule]) -> list[dict]:
    return [rule.as_dict() for rule in rules]


def default_rules(alert: float, critical: float) -> list[AlertRule]:
    """旧的两个阈值折算成两条规则，保持既有语义。"""
    return [AlertRule(float(alert), "P1"), AlertRule(float(critical), "P0")]


def severity_from_scores(scores: np.ndarray, rules: list[AlertRule]) -> np.ndarray:
    """分数命中的最高档位（0 表示正常）。

    规则按倍数升序遍历、后者覆盖前者，因此最终留下的是命中的最高档。
    判定用「达到即命中」（>=），与静态阈值告警的直觉一致。
    """
    result = np.full(len(scores), SEVERITY_NORMAL, dtype=np.int16)
    for index, rule in enumerate(rules, start=1):
        result[np.asarray(scores) >= rule.multiplier] = index
    return result


def level_labels(rules: list[AlertRule]) -> list[str]:
    """等级序号 → 名称，0 号固定是「正常」。"""
    return ["正常"] + [rule.level for rule in rules]


def band_multiplier(rules: list[AlertRule]) -> float:
    """上下界用最低档的倍数：带外即至少触发最低等级。"""
    if not rules:
        raise ValueError("至少需要一条告警规则")
    return float(rules[0].multiplier)
