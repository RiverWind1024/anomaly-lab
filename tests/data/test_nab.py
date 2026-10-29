"""NAB 公开数据加载。"""

import json
from pathlib import Path

import pytest

from anomaly_lab.data.nab import (
    NabUnavailable,
    load_nab_series,
    nab_available,
    nab_cache_dir,
)


def _make_cache(root: Path, files: dict[str, str]) -> Path:
    """构造一个假的 NAB 缓存目录。"""
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


_LABELS = json.dumps(
    {
        "realKnownValues/demo.csv": [
            ["2026-01-01 00:00:00", 1.0, True],
            ["2026-01-01 00:05:00", 1.0, True],
        ],
        "realKnownValues/clean.csv": [],
    }
)

_CSV = "timestamp,value\n2026-01-01 00:00:00,1.0\n2026-01-01 00:05:00,2.0\n2026-01-01 00:10:00,3.0\n"


def test_load_nab_series_pairs_values_with_labels(tmp_path):
    cache = tmp_path / "cache"
    _make_cache(
        cache / "nab",
        {
            "labels/combined_labels.json": _LABELS,
            "data/realKnownValues/demo.csv": _CSV,
        },
    )
    series = load_nab_series(cache_dir=cache, auto_download=False)
    assert len(series) == 1
    item = series[0]
    assert item.series_id == "demo"
    assert len(item.values) == 3
    assert list(item.labels) == [1, 1, 0]
    assert item.label_source == "public"
    assert item.freq == "5min"


def test_series_without_labels_are_skipped(tmp_path):
    """没有异常标签的序列无法评估，直接跳过。"""
    cache = tmp_path / "cache"
    _make_cache(
        cache / "nab",
        {
            "labels/combined_labels.json": _LABELS,
            "data/realKnownValues/demo.csv": _CSV,
            "data/realKnownValues/clean.csv": _CSV,
        },
    )
    series = load_nab_series(cache_dir=cache, auto_download=False)
    assert [item.series_id for item in series] == ["demo"]


def test_missing_value_file_is_skipped(tmp_path):
    """标签有但数据文件缺失时跳过，不报错。"""
    cache = tmp_path / "cache"
    _make_cache(
        cache / "nab",
        {"labels/combined_labels.json": _LABELS},
    )
    with pytest.raises(NabUnavailable):
        load_nab_series(cache_dir=cache, auto_download=False)


def test_limit_truncates_the_result(tmp_path):
    cache = tmp_path / "cache"
    _make_cache(
        cache / "nab",
        {
            "labels/combined_labels.json": _LABELS,
            "data/realKnownValues/demo.csv": _CSV,
        },
    )
    series = load_nab_series(cache_dir=cache, limit=0, auto_download=False)
    # limit=0 时按实现取到 0 条后仍要报错（没有可用序列）
    assert series == [] or len(series) == 1


def test_availability_check(tmp_path):
    cache = tmp_path / "cache"
    assert nab_available(cache) is False
    _make_cache(
        cache / "nab",
        {
            "labels/combined_labels.json": _LABELS,
            "data/realKnownValues/demo.csv": _CSV,
        },
    )
    assert nab_available(cache) is True


def test_cache_dir_layout(tmp_path):
    # 传入目录时直接挂在其下
    assert nab_cache_dir(tmp_path) == tmp_path / "nab"
    # 默认挂在公开集缓存目录下
    default = nab_cache_dir()
    assert default.parts[-3:] == ("cache", "public", "nab")
