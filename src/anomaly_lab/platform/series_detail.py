"""读取单条检测记录的 npz 产物，转成 API 返回结构。

平台运行详情（`/api/runs/{run_id}/series/{series_id}`）与归档详情共用这一段，
避免两处各写一份、字段慢慢漂移。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def npz_list(data: Any, key: str) -> list[float]:
    """npz 里的可选浮点数组 → 列表；缺键 / 空数组都给 `[]`。

    ⚠️ 不能直接 `list(data[key])`：标量（0 维）会抛 `TypeError`，
       而老产物里这些键可能缺失。
    """
    if key not in data:
        return []
    return [float(v) for v in np.asarray(data[key], dtype=float).ravel()]


def build_series_detail(
    npz_path: Path,
    *,
    run_id: int,
    series_id: str,
    decision: dict | None = None,
) -> dict:
    """读一份检测产物 → 前端画波形 / 决策链要的结构。"""
    with np.load(npz_path) as data:
        stamps = np.asarray(data["timestamps"], dtype=np.int64)
        # ⚠️ **先按 ns 解释，再降到秒** —— 直接 `astype("datetime64[s]")`
        #    会把纳秒数值当成秒数，数值直接溢出。
        seconds = stamps.astype("datetime64[ns]").astype("datetime64[s]")
        return {
            "run_id": run_id,
            "series_id": series_id,
            "detector": str(data["detector"]) if "detector" in data else "",
            # ⚠️ 老产物没有这两个键 —— 缺失时按「正常尺度」兜底。
            "scale_source": str(data["scale_source"]) if "scale_source" in data else "",
            "status": str(data["status"]) if "status" in data else "ok",
            "scale_fallback": bool(data["scale_fallback"])
            if "scale_fallback" in data
            else False,
            # 决策链来自本次运行的 index.json；老产物没有这一段 → 空对象。
            "decision": decision or {},
            "timestamps": [str(ts)[:19] for ts in seconds],
            "values": [float(v) for v in np.asarray(data["values"], dtype=float)],
            "scores": [float(v) for v in np.asarray(data["scores"], dtype=float)],
            "severity": [int(v) for v in np.asarray(data["severity"], dtype=int)],
            # 基线三件套 / 阈值 / 档位名 —— 有就带上，老产物缺键时给空值。
            # ⚠️ 空数组 ≠ null：前端按长度判断「有没有带」，别把空数组当「有带」。
            "baseline": npz_list(data, "baseline"),
            "lower": npz_list(data, "lower"),
            "upper": npz_list(data, "upper"),
            "alert_threshold": (
                float(data["alert_threshold"]) if "alert_threshold" in data else 0.0
            ),
            "critical_threshold": (
                float(data["critical_threshold"]) if "critical_threshold" in data else 0.0
            ),
            "score_type": str(data["score_type"]) if "score_type" in data else "",
            "levels": (json.loads(str(data["levels"])) if "levels" in data else ["正常"]),
            # ⚠️ 生产数据没有自带真值 —— 恒为空，真值来自人工标注。
            "labels": [],
        }
