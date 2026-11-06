"""一次检测的决策链 —— 跑的时候填充，不重算。

⚠️ 原则：**记录的是「屏幕上看到的那份结果」**。
   trace 的每一段都必须来自本次 run 实际用到的对象，
   不能事后根据配置推断（配置改过就对不上了）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionTrace:
    quality: dict[str, Any] = field(default_factory=dict)
    capability: dict[str, Any] = field(default_factory=dict)
    classify: dict[str, Any] = field(default_factory=dict)
    select: dict[str, Any] = field(default_factory=dict)
    threshold: dict[str, Any] = field(default_factory=dict)
    detect: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value}
