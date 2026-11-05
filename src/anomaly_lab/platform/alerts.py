"""告警后处理：把检测输出（分数 / 数值）按规则映射成等级。

定位：告警是异常检测的**后处理步骤**，不是独立引擎——
没有事件生命周期、没有通知、没有抑制，只有一层规则映射。

两类条件：

- **倍数条件（主判定）**：分数 >= multiplier。multiplier 就是缩放因子
  （scaleFactor）：偏离基线多少倍正常波动算异常。
- **绝对值条件（并行补充）**：值 op value，例如「值 > 50 记 P1」。
  它只能**抬高**等级、不会压低分数判定的结果。

规则表的**顺序即档位顺序**（从低到高严重）；命中多条时取最高档。

⚠️ `merge_alert_intervals` 放在这里而不是 `alert_events.py` ——
   runner 要用它把告警区间**写进数据库**，而 `alert_events.py` 反过来
   依赖 runner（读产物目录）。放这里就切断了循环依赖。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

SEVERITY_NORMAL = 0

#: 绝对值条件支持的比较符
ABSOLUTE_OPS = (">", ">=", "<", "<=")


def merge_alert_intervals(severity: np.ndarray) -> list[tuple[int, int, int]]:
    """把逐点 severity 合并成连续区间。

    返回 `[(起始下标, 结束下标, 区间内最高档位序号), ...]`（闭区间）。

    - `severity > 0` 的点算告警；`0` 是正常。
    - 连续的告警点合成一个区间；中间隔着正常点就断开。
    - 区间里的档位取**最大值**（最严重的那一档代表这个区间）。
    """
    severity = np.asarray(severity)
    if severity.size == 0:
        return []
    intervals: list[tuple[int, int, int]] = []
    start: int | None = None
    for index in range(len(severity)):
        if severity[index] > SEVERITY_NORMAL:
            if start is None:
                start = index
        elif start is not None:
            intervals.append((start, index - 1, int(severity[start:index].max())))
            start = None
    if start is not None:
        intervals.append((start, len(severity) - 1, int(severity[start:].max())))
    return intervals


@dataclass(frozen=True)
class AlertRule:
    """一条后处理规则：条件命中 → 等级。

    `multiplier` 与 `op/value` 二选一：前者是倍数条件，后者是绝对值条件。
    """

    level: str
    multiplier: float | None = None
    op: str | None = None
    value: float | None = None

    @property
    def is_absolute(self) -> bool:
        return self.multiplier is None

    def as_dict(self) -> dict:
        if self.is_absolute:
            return {"op": self.op, "value": float(self.value), "level": self.level}
        return {"multiplier": float(self.multiplier), "level": self.level}

    def matches(self, scores: np.ndarray, values: np.ndarray | None) -> np.ndarray:
        """该规则命中的位置。"""
        if not self.is_absolute:
            return scores >= float(self.multiplier)
        if values is None:
            return np.zeros(len(scores), dtype=bool)
        if self.op == ">":
            return values > self.value
        if self.op == ">=":
            return values >= self.value
        if self.op == "<":
            return values < self.value
        return values <= self.value


def parse_rules(raw: object) -> list[AlertRule]:
    """解析规则列表；**保持输入顺序**（顺序即档位：从低到高严重）。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    rules: list[AlertRule] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("告警规则必须是对象列表")
        level = str(item.get("level", "")).strip()
        if not level:
            raise ValueError("告警规则缺少 level")
        multiplier = item.get("multiplier")
        if multiplier is not None:
            factor = float(multiplier)
            if not np.isfinite(factor) or factor <= 0:
                raise ValueError(f"告警规则的 multiplier 必须为正数: {multiplier}")
            rules.append(AlertRule(level=level, multiplier=factor))
            continue
        op = item.get("op")
        value = item.get("value")
        if op is None or value is None:
            raise ValueError(
                "告警规则需要 multiplier（倍数条件）或 op+value（绝对值条件）"
            )
        if str(op) not in ABSOLUTE_OPS:
            raise ValueError(f"绝对值条件的 op 只支持 {list(ABSOLUTE_OPS)}: {op!r}")
        bound = float(value)
        if not np.isfinite(bound):
            raise ValueError(f"绝对值条件的 value 必须是有限数字: {value}")
        rules.append(AlertRule(level=level, op=str(op), value=bound))
    if not rules:
        raise ValueError("至少需要一条告警规则")
    return rules


def rules_to_dicts(rules: list[AlertRule]) -> list[dict]:
    return [rule.as_dict() for rule in rules]


def default_rules(alert: float, critical: float) -> list[AlertRule]:
    """旧的两个阈值折算成两条倍数规则，保持既有语义。"""
    return [
        AlertRule(level="P1", multiplier=float(alert)),
        AlertRule(level="P0", multiplier=float(critical)),
    ]


def severity_from_conditions(
    scores: np.ndarray, values: np.ndarray | None, rules: list[AlertRule]
) -> np.ndarray:
    """后处理：把检测输出映射成等级档位（0 = 正常）。

    倍数条件是主判定；绝对值条件并行生效。因为档位按规则顺序取最高，
    绝对值条件只会抬高等级，不会把分数判定的高等级压低。
    """
    scores = np.asarray(scores, dtype=float)
    values = None if values is None else np.asarray(values, dtype=float)
    result = np.full(len(scores), SEVERITY_NORMAL, dtype=np.int16)
    for index, rule in enumerate(rules, start=1):
        result[rule.matches(scores, values)] = index
    return result


def level_labels(rules: list[AlertRule]) -> list[str]:
    """等级序号 → 名称，0 号固定是「正常」。"""
    return ["正常"] + [rule.level for rule in rules]


def band_multiplier(rules: list[AlertRule]) -> float:
    """上下界宽度用最低档的倍数条件：带外即至少触发最低等级。"""
    multipliers = [rule.multiplier for rule in rules if rule.multiplier is not None]
    if not multipliers:
        raise ValueError("至少需要一条倍数规则来定义上下界宽度")
    return float(min(multipliers))


def band_multiplier_or_none(rules: list[AlertRule]) -> float | None:
    """最低档倍数条件；**没有倍数条件时返回 None 而不是抛错**。

    规则表可以全是绝对值条件（「值 > 50 记 P0」），这时「上下界宽度」无从谈起 ——
    对本来就不画基线带的检测器（如 Chronos，分数是 0~1 的相对越界程度）
    更是如此。调用方据此退回到检测器自己的默认阈值。

    告警等级判定走的是规则表（`severity_from_conditions`），与这里的宽度无关，
    所以没有倍数条件**不影响**分级，只是没有「带」可画。
    """
    multipliers = [rule.multiplier for rule in rules if rule.multiplier is not None]
    return float(min(multipliers)) if multipliers else None


def highest_multiplier(rules: list[AlertRule]) -> float | None:
    """最高一档的分数阈值；没有倍数条件时为 None。"""
    multipliers = [rule.multiplier for rule in rules if rule.multiplier is not None]
    return float(max(multipliers)) if multipliers else None
