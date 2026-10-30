"""评估记录的排除清单。

「删除一条检测记录」= 把它记进排除清单，而不是改 report.json ——
report.json 是 `make evaluate` 的产物，重跑会把它整个覆盖掉，
直接改文件的话删掉的记录下次又回来了。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def exclusion_key(series_id: str, detector: str) -> str:
    """一条检测记录的唯一键：序列 + 算法。"""
    return f"{series_id}::{detector}"


class ExclusionStore:
    """排除清单的读写。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        items = data.get("excluded")
        return items if isinstance(items, list) else []

    def keys(self) -> set[str]:
        return {str(item.get("key", "")) for item in self.list()}

    def add(self, series_id: str, detector: str) -> dict:
        items = self.list()
        key = exclusion_key(series_id, detector)
        for item in items:
            if item.get("key") == key:
                return item
        record = {
            "key": key,
            "series_id": series_id,
            "detector": detector,
            "excluded_at": datetime.now(UTC).isoformat(),
        }
        items.append(record)
        self._save(items)
        return record

    def remove(self, series_id: str, detector: str) -> bool:
        items = self.list()
        key = exclusion_key(series_id, detector)
        kept = [item for item in items if item.get("key") != key]
        if len(kept) == len(items):
            return False
        self._save(kept)
        return True

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"excluded": items}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
