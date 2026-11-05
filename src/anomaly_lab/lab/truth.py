"""P3：真值的来源与对齐。

⚠️ **三种真值来源，只有一种需要这个模块**：

| 来源 | 标签从哪来 | 本模块要做的事 |
|---|---|---|
| 合成（`kind="synthetic"`） | 生成器直接写在 `SeriesBundle.labels` 里 | 无 |
| 公开集（`kind="public"`） | loader 写在 `SeriesBundle.labels` 里 | 无 |
| 人工标注（`truth="annotation"`） | 标注页写的 `annotations/<series_id>.jsonl` | **把区间对齐到时间轴上** |

⚠️ **标注按「序列 + 时间区间」存，不按运行**：

   真值是**数据的属性**，不是某次运行的属性。生产任务是滚动窗口，
   同一个异常会被连续几十次运行反复报出 —— 如果标注绑 run，
   用户就得把同一段异常标几十次，标注预算全浪费在重复劳动上。

   时间区间本身就是定位（`start` / `end`），run 只是「看哪次波形」的入口：
   标注一次，**所有时间轴覆盖该时段的检测记录**都复用它。

⚠️ 人工标注的 `start` / `end` 是**时间戳**，区间是**闭区间** ——
   与切窗的「左闭右开」不是一回事，别混用。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.timeutil import parse_iso

#: 一毫秒 = 一百万纳秒（numpy 的时间精度是 ns）。
_MS_TO_NS = 1_000_000

#: 「整条记录核对过」的标注类型 —— **不是真值，是覆盖率声明**。
REVIEWED_TYPE = "reviewed"


def is_reviewed(record: dict[str, Any]) -> bool:
    """这条标注是「核对过」，不是「这里是异常」。"""
    return str(record.get("type", "")) == REVIEWED_TYPE


def annotations_path(data_root: Path, series_id: str) -> Path:
    """某条序列的标注文件 —— **按序列存，不按运行**。"""
    return Path(data_root) / "annotations" / f"{series_id}.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读一个 JSONL 文件；**坏行跳过，不整体失败**。

    ⚠️ 标注是人工写的，有一行手滑不该让整个预检挂掉。
    """
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一段区间只留一条（旧格式迁移后可能重复）。"""
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for record in records:
        key = (
            str(record.get("start", "")),
            str(record.get("end", "")),
            str(record.get("type", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def load_annotations(data_root: Path, series_id: str) -> list[dict[str, Any]]:
    """读一条序列的人工标注（**含旧格式**：`run-<id>/<series_id>.jsonl`）。

    ⚠️ 旧格式按 run 存，是「标注绑定运行」时代的产物；
       读的时候合并进来，写的时候只写按序列的那份。
    """
    root = Path(data_root) / "annotations"
    records = _read_jsonl(annotations_path(data_root, series_id))
    if root.is_dir():
        for legacy in sorted(root.glob(f"run-*/{series_id}.jsonl")):
            records.extend(_read_jsonl(legacy))
    return _dedupe(records)


def load_all_annotations(data_root: Path) -> dict[str, list[dict[str, Any]]]:
    """一次读完**所有**标注 —— `{series_id: [记录, ...]}`。

    ⚠️ **一次扫描，不是每条候选读一次** ——
       评估时可能有上万条检测记录，逐条开文件会把页面拖垮。
    """
    root = Path(data_root) / "annotations"
    if not root.is_dir():
        return {}

    collected: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(root.glob("*.jsonl")):
        collected.setdefault(path.stem, []).extend(_read_jsonl(path))
    # ⚠️ 旧格式：annotations/run-<id>/<series_id>.jsonl
    for path in sorted(root.glob("run-*/*.jsonl")):
        collected.setdefault(path.stem, []).extend(_read_jsonl(path))
    return {series_id: _dedupe(records) for series_id, records in collected.items()}


def _boundary_ns(value: object) -> int | None:
    """把标注的边界转成纳秒时间戳。

    支持两种写法：**毫秒时间戳**（标注页发的）与 **ISO 字符串**（手写 / 导出）。
    """
    if isinstance(value, (int, float)):
        return int(value) * _MS_TO_NS
    if isinstance(value, str) and value.strip():
        try:
            parsed: datetime = parse_iso(value)
        except ValueError:
            return None
        return int(np.datetime64(parsed.replace(tzinfo=None), "ns").astype(np.int64))
    return None


def _intervals_to_mask(series: SeriesBundle, records: list[dict[str, Any]]) -> np.ndarray:
    """标注区间 → 点级真值掩码。

    ⚠️ 区间是**闭区间** `[start, end]` —— 右边界用 `side="right"`，
       跟切窗的左闭右开不一样。

    ⚠️ 落在序列时间轴**之外**的部分直接丢掉（`searchsorted` 天然裁剪）——
       标注是按序列存的，不保证覆盖每一条窗口。
    """
    stamps = series.timestamps.astype("datetime64[ns]").astype(np.int64)
    mask = np.zeros(series.n, dtype=np.int8)
    for record in records:
        # ⚠️ 「核对过」不是真值 —— 它只说明这段被看过，不代表有异常。
        if is_reviewed(record):
            continue
        start = _boundary_ns(record.get("start"))
        end = _boundary_ns(record.get("end"))
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        lo = int(np.searchsorted(stamps, start, side="left"))
        hi = int(np.searchsorted(stamps, end, side="right"))
        if hi > lo:
            mask[lo:hi] = 1
    return mask


def attach_annotations(series: SeriesBundle, data_root: Path) -> SeriesBundle:
    """把人工标注贴到序列上。

    ⚠️ 序列自带真值时**不覆盖** —— 合成 / 公开集的标签比人工标注更权威。
    """
    if series.labels is not None and series.label_source != "none":
        return series

    records = load_annotations(data_root, series.series_id)
    if not records:
        return series

    mask = _intervals_to_mask(series, records)
    if not mask.any():
        # 标注区间没落在序列的时间轴上 —— 多半是序列 id 对不上。
        return series

    return SeriesBundle(
        series_id=series.series_id,
        values=series.values,
        timestamps=series.timestamps,
        freq=series.freq,
        labels=mask,
        label_source="human",
        meta={**series.meta, "n_annotated": int(mask.sum())},
    )
