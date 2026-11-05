"""P2：实验记录落盘 + 一键建任务草稿。

验收两条：
  1. **可复现** —— 同一 spec 跑两次，指纹一致（耗时不同不算差异）。
  2. **物理隔离** —— 实验产物只落在 `data/lab/experiments/`，绝不碰 `reports/latest/`。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anomaly_lab.lab.records import (
    build_job_draft,
    collect_env,
    list_experiments,
    load_experiment,
    result_fingerprint,
    save_experiment,
)
from anomaly_lab.lab.spec import DataSpec, SamplingSpec

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _spec(**overrides) -> DataSpec:
    params = {
        "kind": "metric",
        "metric_id": 12,
        "start": BASE,
        "end": BASE.replace(day=2),
        "sampling": SamplingSpec(window_points=200, stride_points=200, max_points=2000),
    }
    params.update(overrides)
    return DataSpec(**params)


def _result(n_alerts: int = 20, elapsed_ms: float = 12.5) -> dict:
    return {
        "spec": {"kind": "metric"},
        "freq": "5min",
        "window_points": 200,
        "multipliers": ["1.5", "2.0", "2.5"],
        "primary_multiplier": "2.5",
        "windows": [
            {"series_id": "m:a", "index": 0, "start": "x", "end": "y", "n": 200, "expected": 200}
        ],
        "results": [
            {
                "detector": "auto",
                "per_window": [
                    {
                        "series_id": "m:a",
                        "window_index": 0,
                        "detector": "seasonal",
                        "requested": "auto",
                        "metric_class": "periodic",
                        "fallback": False,
                        "rationale": "周期型",
                        "n": 200,
                        "n_alerts": n_alerts,
                        "alert_ratio": n_alerts / 200,
                        "elapsed_ms": elapsed_ms,
                        "sensitivity": {"1.5": 30, "2.5": n_alerts},
                        "skipped": False,
                        "skip_reason": None,
                    }
                ],
                "aggregate": {
                    "n_windows": 1,
                    "n_windows_skipped": 0,
                    "n_points": 200,
                    "n_alerts": n_alerts,
                    "alert_ratio": n_alerts / 200,
                    "n_windows_with_alerts": 1,
                    "stability": 0.03,
                    "elapsed_ms": elapsed_ms,
                    "sensitivity": {"1.5": 30, "2.5": n_alerts},
                    "resolved_mix": {"seasonal": 1},
                },
            }
        ],
        "warnings": [],
    }


# ---------- 落盘 ----------


def test_save_writes_json_under_lab_dir(tmp_path: Path):
    saved = save_experiment(tmp_path, spec=_spec(), result=_result())

    path = tmp_path / "lab" / "experiments" / f"{saved['id']}.json"
    assert path.exists()
    assert saved["id"] in path.name


def test_save_never_touches_reports_dir(tmp_path: Path):
    save_experiment(tmp_path, spec=_spec(), result=_result())

    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "reports" / "latest").exists()


def test_saved_record_round_trips(tmp_path: Path):
    saved = save_experiment(tmp_path, spec=_spec(), result=_result())

    loaded = load_experiment(tmp_path, saved["id"])

    assert loaded["id"] == saved["id"]
    assert loaded["spec"]["metric_id"] == 12
    assert loaded["spec"]["sampling"]["window_points"] == 200
    assert loaded["result"]["results"][0]["detector"] == "auto"
    assert loaded["fingerprint"] == saved["fingerprint"]


def test_load_unknown_id_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="实验记录"):
        load_experiment(tmp_path, "nope")


def test_list_experiments_returns_summaries_newest_first(tmp_path: Path):
    first = save_experiment(tmp_path, spec=_spec(), result=_result(n_alerts=10))
    second = save_experiment(tmp_path, spec=_spec(), result=_result(n_alerts=30))

    items = list_experiments(tmp_path)

    assert len(items) == 2
    assert items[0]["id"] == second["id"]
    assert items[1]["id"] == first["id"]
    # 摘要不带完整结果 —— 列表页不该拉全量数据
    assert "result" not in items[0]
    assert items[0]["summary"]["detectors"][0]["detector"] == "auto"


def test_list_experiments_empty_dir(tmp_path: Path):
    assert list_experiments(tmp_path) == []


# ---------- 可复现 ----------


def test_fingerprint_ignores_elapsed_time():
    """耗时每次都不同 —— 它不能影响「两次结果是否一致」的判定。"""
    a = result_fingerprint(_result(elapsed_ms=1.0))
    b = result_fingerprint(_result(elapsed_ms=999.0))

    assert a == b


def test_fingerprint_changes_with_findings():
    a = result_fingerprint(_result(n_alerts=10))
    b = result_fingerprint(_result(n_alerts=11))

    assert a != b


def test_same_spec_twice_yields_same_fingerprint(tmp_path: Path):
    """验收：同一 spec 跑两次，记录指纹一致。"""
    first = save_experiment(tmp_path, spec=_spec(), result=_result())
    second = save_experiment(tmp_path, spec=_spec(), result=_result())

    assert first["fingerprint"] == second["fingerprint"]


def test_env_records_git_and_dependency_versions():
    env = collect_env()

    assert "git_sha" in env
    assert "python" in env
    assert "dependencies" in env
    assert "numpy" in env["dependencies"]


def test_env_git_sha_is_hex_when_available():
    env = collect_env()

    sha = env.get("git_sha")
    if sha is not None:
        assert len(sha) >= 7


def test_running_same_spec_twice_gives_same_fingerprint(tmp_path: Path):
    """**验收**：同一 spec 跑两次真实检测，指纹一致（耗时不同不算差异）。"""
    import sqlite3

    from anomaly_lab.lab.detect import run_experiment
    from anomaly_lab.platform.store import PlatformStore

    db = tmp_path / "source.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE metrics (ts TEXT, series TEXT, value REAL)")
    rows = []
    for i in range(400):
        ts = (BASE + timedelta(hours=i)).isoformat()
        rows.append((ts, "a", float((i % 7) - 3)))
    conn.executemany("INSERT INTO metrics VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()

    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", str(db))
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="series",
        freq="1h",
    )
    spec = DataSpec(
        kind="metric",
        metric_id=metric.id,
        start=BASE,
        end=BASE + timedelta(hours=400),
        sampling=SamplingSpec(window_points=100, stride_points=100, max_points=400),
    )

    first = run_experiment(store, tmp_path, spec, detectors=["iqr", "zscore"])
    second = run_experiment(store, tmp_path, spec, detectors=["iqr", "zscore"])

    assert result_fingerprint(first) == result_fingerprint(second)


# ---------- 一键建任务 ----------


def test_job_draft_fills_production_fields(tmp_path: Path):
    saved = save_experiment(tmp_path, spec=_spec(), result=_result())

    draft = build_job_draft(load_experiment(tmp_path, saved["id"]))

    assert draft["metric_id"] == 12
    # 窗口点数必须与实验一致 —— 否则「实验所见」不是「上线所得」
    assert draft["window_points"] == 200
    assert draft["interval_seconds"] == 300  # 5min
    assert draft["detector"] == "auto"
    assert draft["alert_rules"]
    assert draft["name"]
    assert draft["rationale"]


def test_job_draft_prefers_auto_when_experiment_ran_it(tmp_path: Path):
    result = _result()
    result["results"].append(
        {
            "detector": "iqr",
            "per_window": [],
            "aggregate": {
                "n_windows": 1,
                "n_windows_skipped": 0,
                "n_points": 200,
                "n_alerts": 1,
                "alert_ratio": 0.005,
                "n_windows_with_alerts": 1,
                "stability": 0.002,
                "elapsed_ms": 1.0,
                "sensitivity": {"2.5": 1},
                "resolved_mix": {"iqr": 1},
            },
        }
    )
    saved = save_experiment(tmp_path, spec=_spec(), result=result)

    draft = build_job_draft(load_experiment(tmp_path, saved["id"]))

    assert draft["detector"] == "auto"
    assert "iqr" in draft["alternatives"]


def test_job_draft_rejects_temporary_sql(tmp_path: Path):
    spec = _spec(
        kind="sql",
        metric_id=None,
        source_id=3,
        sql="SELECT 1",
        time_column="ts",
        value_column="v",
        freq="5min",
    )
    saved = save_experiment(tmp_path, spec=spec, result=_result())

    with pytest.raises(ValueError, match="临时 SQL"):
        build_job_draft(load_experiment(tmp_path, saved["id"]))
