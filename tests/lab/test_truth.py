"""P3：人工标注的对齐。

⚠️ 标注页写的是**毫秒时间戳**，区间是**闭区间** ——
   与切窗的「左闭右开」不是一回事，对齐时最容易搞错。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.lab.inspect import prepare
from anomaly_lab.lab.spec import DataSpec, SamplingSpec
from anomaly_lab.lab.truth import attach_annotations, load_annotations
from anomaly_lab.platform.store import PlatformStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _bundle(n: int = 10) -> SeriesBundle:
    stamps = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ns") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ns]",
    )
    return SeriesBundle(
        series_id="m:a",
        values=np.arange(n, dtype=float),
        timestamps=stamps,
        freq="1h",
    )


def _write_annotations(data_root: Path, series_id: str, records: list[dict]) -> Path:
    path = data_root / "annotations" / f"{series_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records),
        encoding="utf-8",
    )
    return path


def test_读不到标注时返回空列表(tmp_path):
    assert load_annotations(tmp_path, "m:a") == []


def test_坏行跳过不影响其余(tmp_path):
    path = tmp_path / "annotations" / "m:a.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"start": 0, "end": 1}\n'
        "这不是 JSON\n"
        '{"start": 2, "end": 3}\n',
        encoding="utf-8",
    )

    records = load_annotations(tmp_path, "m:a")

    assert len(records) == 2


def test_毫秒时间戳区间对齐到点(tmp_path):
    """第 2、3 小时被标注 —— 对应第 2、3 个点。"""
    bundle = _bundle()
    start_ms = int(BASE.timestamp() * 1000)
    _write_annotations(
        tmp_path,
        "m:a",
        [{"start": start_ms + 2 * 3600_000, "end": start_ms + 3 * 3600_000, "type": "spike"}],
    )

    labeled = attach_annotations(bundle, tmp_path)

    assert labeled.label_source == "human"
    assert labeled.labels is not None
    assert labeled.labels.tolist() == [0, 0, 1, 1, 0, 0, 0, 0, 0, 0]


def test_区间是闭区间_右边界算在内(tmp_path):
    bundle = _bundle()
    start_ms = int(BASE.timestamp() * 1000)
    _write_annotations(
        tmp_path,
        "m:a",
        [{"start": start_ms + 2 * 3600_000, "end": start_ms + 3 * 3600_000, "type": "spike"}],
    )

    labeled = attach_annotations(bundle, tmp_path)

    assert labeled.labels is not None
    # ⚠️ 第 3 小时是闭区间的右边界 —— 必须算在内。
    assert int(labeled.labels[3]) == 1


def test_也认_iso_字符串(tmp_path):
    bundle = _bundle()
    _write_annotations(
        tmp_path,
        "m:a",
        [{"start": "2026-01-01T02:00:00+00:00", "end": "2026-01-01T03:00:00+00:00"}],
    )

    labeled = attach_annotations(bundle, tmp_path)

    assert labeled.labels is not None
    assert labeled.labels.tolist() == [0, 0, 1, 1, 0, 0, 0, 0, 0, 0]


def test_认标注页实际写出的_naive_iso(tmp_path):
    """⚠️ 标注页存的是**naive ISO**（与序列时间戳同格式，无时区后缀）。

    带时区与不带时区差几个小时 —— 认错了，标注就整段错位。
    """
    bundle = _bundle()
    _write_annotations(
        tmp_path,
        "m:a",
        [{"start": "2026-01-01T02:00:00", "end": "2026-01-01T03:00:00"}],
    )

    labeled = attach_annotations(bundle, tmp_path)

    assert labeled.labels is not None
    assert labeled.labels.tolist() == [0, 0, 1, 1, 0, 0, 0, 0, 0, 0]


def test_序列自带真值时不覆盖(tmp_path):
    """合成 / 公开集的标签比人工标注更权威。"""
    bundle = SeriesBundle(
        series_id="m:a",
        values=np.arange(10, dtype=float),
        timestamps=_bundle().timestamps,
        freq="1h",
        labels=np.ones(10, dtype=np.int8),
        label_source="synthetic",
    )
    start_ms = int(BASE.timestamp() * 1000)
    _write_annotations(tmp_path, "m:a", [{"start": start_ms, "end": start_ms}])

    labeled = attach_annotations(bundle, tmp_path)

    assert labeled.label_source == "synthetic"
    assert labeled.labels is not None
    assert int(labeled.labels.sum()) == 10


def test_标注区间没落在时间轴上就不贴(tmp_path):
    bundle = _bundle()
    _write_annotations(tmp_path, "m:a", [{"start": 0, "end": 1}])

    labeled = attach_annotations(bundle, tmp_path)

    assert labeled.labels is None


def test_端到端_指标来源能贴上标注(tmp_path):
    """`kind="metric"` + `truth="annotation"` —— 标注要在切窗前贴上。"""
    db = tmp_path / "source.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, value REAL)")
    rows = []
    for i in range(200):
        ts = (BASE + timedelta(hours=i)).isoformat()
        rows.append((ts, float(np.sin(2 * np.pi * i / 8))))
    conn.executemany("INSERT INTO metrics VALUES (?, ?)", rows)
    conn.commit()
    conn.close()

    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db))
    store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    start_ms = int(BASE.timestamp() * 1000)
    _write_annotations(
        tmp_path,
        "m",
        [{"start": start_ms + 10 * 3600_000, "end": start_ms + 12 * 3600_000, "type": "spike"}],
    )

    spec = DataSpec(
        kind="metric",
        metric_id=1,
        start=BASE,
        end=BASE + timedelta(hours=200),
        freq="1h",
        truth="annotation",
        sampling=SamplingSpec(window_points=50, stride_points=50, max_points=200),
    )
    prepared = prepare(store, tmp_path, spec)

    labels = prepared.series[0].series.labels
    assert labels is not None
    assert int(labels.sum()) == 3
    assert prepared.series[0].series.label_source == "human"
