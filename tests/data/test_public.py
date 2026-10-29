import json
from pathlib import Path

import pytest

from anomaly_lab.data.public import DatasetUnavailable, load_public_series, series_available


def test_offline_mode_raises_when_cache_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_OFFLINE", "1")
    with pytest.raises(DatasetUnavailable):
        load_public_series("some_series", cache_dir=tmp_path)


def test_offline_mode_reads_existing_cache(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANOMALY_LAB_OFFLINE", "1")
    d = tmp_path / "some_series"
    d.mkdir(parents=True)
    (d / "values.txt").write_text("1.0\n2.0\n3.0\n")
    (d / "meta.json").write_text(
        json.dumps(
            {
                "source": "test",
                "n": 3,
                "freq": "1min",
                "anomaly_intervals": [[1, 1]],
            }
        )
    )
    s = load_public_series("some_series", cache_dir=tmp_path)
    assert s.n == 3
    assert s.label_source == "public"
    assert s.anomaly_indices().sum() == 1


def test_series_available_reports_false_for_missing(tmp_path: Path):
    assert series_available("nope", cache_dir=tmp_path) is False
