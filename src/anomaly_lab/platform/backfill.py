"""把已有产物目录里的检测结果**补录**进数据库。

⚠️ **为什么需要**：检测记录（序列摘要 + 告警区间）现在落库，
   但在这套机制之前产生的运行，产物只在磁盘上 —— 库里查不到。
   这个脚本把两边对齐。

⚠️ **幂等** —— 重跑不会写重复行（`INSERT OR REPLACE` + 先删后插）。
   所以它可以随时用来补新增的运行。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from anomaly_lab.platform.alerts import merge_alert_intervals
from anomaly_lab.platform.runner import content_hash, run_dir
from anomaly_lab.platform.store import PlatformStore


def _iso(ns: int) -> str:
    """纳秒时间戳 → naive ISO 字符串（秒精度）。"""
    return str(np.datetime64(int(ns), "ns").astype("datetime64[s]"))


def _read_index(data_root: Path, run_id: int) -> dict[str, Any] | None:
    path = run_dir(data_root, run_id) / "index.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alert_rows(
    *,
    series_id: str,
    group: str | None,
    timestamps: np.ndarray,
    severity: np.ndarray,
    scores: np.ndarray | None,
    levels: list[str],
    detector: str,
    score_type: str,
) -> list[dict[str, Any]]:
    """一条序列的告警区间 —— 与 runner 写库的口径完全一致。"""
    rows: list[dict[str, Any]] = []
    for start, end, level_index in merge_alert_intervals(severity):
        level = levels[level_index] if 0 < level_index < len(levels) else "未知"
        window = scores[start : end + 1] if scores is not None else None
        rows.append(
            {
                "series_id": series_id,
                "group": group,
                "level": level,
                "level_index": level_index,
                "start_ts": _iso(timestamps[start]),
                "end_ts": _iso(timestamps[end]),
                "n_points": end - start + 1,
                "max_score": float(window.max()) if window is not None and window.size else 0.0,
                "detector": detector,
                "score_type": score_type,
            }
        )
    return rows


def sync_run(store: PlatformStore, data_root: Path, run_id: int) -> int:
    """把一次运行的产物补录进库，返回补录的序列条数。

    ⚠️ 产物缺失就跳过（不是错误 —— 目录可能已被保留策略清掉）。
    """
    index = _read_index(data_root, run_id)
    if not index:
        return 0
    job_id = int(index.get("job_id", 0))

    entries: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for entry in index.get("series", []):
        file_name = entry.get("file")
        fingerprint = ""
        start_ts = end_ts = ""
        if file_name:
            npz_path = run_dir(data_root, run_id) / file_name
            if npz_path.is_file():
                try:
                    with np.load(npz_path, allow_pickle=False) as payload:
                        timestamps = np.asarray(payload["timestamps"], dtype=np.int64)
                        severity = np.asarray(payload["severity"], dtype=int)
                        scores = payload.get("scores", None)
                        levels = json.loads(str(payload["levels"]))
                        detector = str(payload["detector"])
                        score_type = str(payload["score_type"])
                except (OSError, ValueError, KeyError):
                    timestamps = None
                if timestamps is not None:
                    fingerprint = content_hash(
                        str(entry.get("series_id", "")), timestamps, severity
                    )
                    if len(timestamps):
                        start_ts = _iso(timestamps[0])
                        end_ts = _iso(timestamps[-1])
                    alerts.extend(
                        _alert_rows(
                            series_id=str(entry.get("series_id", "")),
                            group=entry.get("group"),
                            timestamps=timestamps,
                            severity=severity,
                            scores=scores,
                            levels=levels,
                            detector=detector,
                            score_type=score_type,
                        )
                    )
        entries.append(
            {
                **entry,
                "content_hash": fingerprint,
                "start_ts": start_ts,
                "end_ts": end_ts,
            }
        )

    store.record_run_series(run_id, entries)
    store.record_alert_events(run_id, job_id, alerts)
    return len(entries)


def sync_detections(
    store: PlatformStore,
    data_root: Path,
    *,
    only_missing: bool = True,
) -> dict[str, int]:
    """把产物目录里的检测结果补录进数据库。

    ⚠️ `only_missing=True`（默认）→ 只补**库里还没有**的运行，
       不重复读已经同步过的 npz。
    """
    root = Path(data_root) / "cache" / "platform" / "runs"
    if not root.is_dir():
        return {"runs": 0, "series": 0}

    # ⚠️ **只有库里已有 `runs` 行的运行才能补录** ——
    #    `run_series.run_id` 有外键约束指向 `runs(id)`。
    known = {run.id for run in store.all_runs()}
    pending = [
        int(entry.name)
        for entry in root.iterdir()
        if entry.is_dir() and entry.name.isdigit() and int(entry.name) in known
    ]
    pending.sort()

    if only_missing:
        synced = store.synced_run_ids()
        pending = [run_id for run_id in pending if run_id not in synced]

    total_series = 0
    for run_id in pending:
        total_series += sync_run(store, data_root, run_id)
    return {"runs": len(pending), "series": total_series}
