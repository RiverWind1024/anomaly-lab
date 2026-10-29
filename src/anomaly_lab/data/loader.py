"""合成数据集的落盘与加载（npz + index.json）。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from anomaly_lab.config import CONFIG
from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.data.synthetic import METRIC_CLASSES, generate_series


def _entry_path(key: str) -> str:
    return key


def save_dataset(series: list[SeriesBundle], out_dir: Path) -> Path:
    """保存为 out_dir/<class>/<series_id>.npz + index.json。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for s in series:
        metric_class = s.meta.get("metric_class", "unknown")
        class_dir = out_dir / metric_class
        class_dir.mkdir(parents=True, exist_ok=True)
        rel_path = Path(metric_class) / f"{s.series_id}.npz"
        timestamps_ns = s.timestamps.astype("datetime64[ns]").astype(np.int64)
        labels = s.labels if s.labels is not None else np.zeros(0, dtype=np.int8)
        np.savez_compressed(
            out_dir / rel_path,
            values=s.values,
            timestamps=timestamps_ns,
            labels=labels,
        )
        entries.append(
            {
                "series_id": s.series_id,
                "metric_class": metric_class,
                "label_source": s.label_source,
                "meta": s.meta,
                "freq": s.freq,
                "n": s.n,
                "path": rel_path.as_posix(),
            }
        )
    index = {"series": entries}
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out_dir


def load_dataset(data_dir: Path, classes: list[str] | None = None) -> list[SeriesBundle]:
    """加载 index.json 描述的全部序列。"""
    data_dir = Path(data_dir)
    index_path = data_dir / "index.json"
    if not index_path.exists():
        return []
    index = json.loads(index_path.read_text(encoding="utf-8"))
    result: list[SeriesBundle] = []
    for entry in index.get("series", []):
        if classes and entry["metric_class"] not in classes:
            continue
        payload = np.load(data_dir / _entry_path(entry["path"]))
        values = np.asarray(payload["values"], dtype=float)
        timestamps = np.asarray(payload["timestamps"]).astype("datetime64[ns]")
        labels_arr = np.asarray(payload["labels"])
        labels = labels_arr.astype(np.int8) if labels_arr.size == len(values) else None
        if entry.get("label_source", "none") == "none":
            labels = None
        result.append(
            SeriesBundle(
                series_id=entry["series_id"],
                values=values,
                timestamps=timestamps,
                freq=entry["freq"],
                labels=labels,
                label_source=entry.get("label_source", "none"),
                meta=entry.get("meta", {}),
            )
        )
    return result


def build_synthetic_dataset(
    n_per_class: int = 20,
    seed: int = 42,
    out_dir: Path | None = None,
    n_total: int | None = None,
) -> list[SeriesBundle]:
    """生成 + 保存 + 返回。n_total 给出时按总数在 6 类间分配。"""
    out_dir = Path(out_dir) if out_dir is not None else CONFIG.synthetic_dir
    if n_total is not None:
        base, remainder = divmod(max(0, n_total), len(METRIC_CLASSES))
        counts = [base + (1 if i < remainder else 0) for i in range(len(METRIC_CLASSES))]
    else:
        counts = [n_per_class] * len(METRIC_CLASSES)

    series: list[SeriesBundle] = []
    for class_idx, (metric_class, count) in enumerate(zip(METRIC_CLASSES, counts)):
        for j in range(count):
            series_seed = seed + class_idx * 1000 + j
            series.append(generate_series(metric_class, seed=series_seed))
    save_dataset(series, out_dir)
    return series
