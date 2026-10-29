"""执行一个检测任务：取数 → 打分 → 分级 → 落盘。

结果按「一次 run 一个目录」组织：index.json 描述有哪些序列，
每条序列一个 npz（实际值、分数、基线、上下界、告警等级）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from anomaly_lab.detectors.bands import compute_bands
from anomaly_lab.platform.detectors import create_detector
from anomaly_lab.platform.sqlite_source import load_series
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import freq_delta, to_iso, utcnow

SEVERITY_NORMAL = 0
SEVERITY_P1 = 1
SEVERITY_P0 = 2


def run_dir(data_root: Path, run_id: int) -> Path:
    return Path(data_root) / "cache" / "platform" / "runs" / str(run_id)


def resolve_source_path(source_path: str, data_root: Path) -> Path:
    path = Path(source_path)
    return path if path.is_absolute() else Path(data_root) / path


def severity_from_scores(
    scores: np.ndarray, alert_threshold: float, critical_threshold: float
) -> np.ndarray:
    """0=正常，1=P1，2=P0；分数严格大于阈值才升级。"""
    result = np.zeros(len(scores), dtype=np.int8)
    result[scores > alert_threshold] = SEVERITY_P1
    result[scores > critical_threshold] = SEVERITY_P0
    return result


def _file_name(series_id: str) -> str:
    digest = hashlib.sha1(series_id.encode("utf-8")).hexdigest()[:16]
    return f"{digest}.npz"


def execute_job(
    store: PlatformStore,
    job_id: int,
    *,
    data_root: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> int:
    """执行一次任务，返回 run_id；失败会记录到 runs 表后重新抛出。"""
    job = store.get_job(job_id)
    run = store.create_run(job.id)
    try:
        metric = store.get_metric(job.metric_id)
        source = store.get_source(metric.source_id)
        end_time = end or now or utcnow()
        start_time = start or (
            end_time - freq_delta(metric.freq) * job.window_points
        )
        source_path = resolve_source_path(source.path, data_root)
        series_list = load_series(metric, source_path, start_time, end_time)

        target = run_dir(data_root, run.id)
        target.mkdir(parents=True, exist_ok=True)
        entries: list[dict] = []
        total_alerts = 0

        for series in series_list:
            detector = create_detector(job.detector).fit(series)
            result = detector.detect(series, threshold=job.alert_threshold)
            bands = compute_bands(detector, series, job.alert_threshold)
            severity = severity_from_scores(
                result.scores, job.alert_threshold, job.critical_threshold
            )
            file_name = _file_name(series.series_id)
            np.savez_compressed(
                target / file_name,
                timestamps=series.timestamps.astype("datetime64[ns]").astype(np.int64),
                values=series.values,
                scores=result.scores,
                baseline=np.asarray(bands.baseline if bands else [], dtype=float),
                lower=np.asarray(bands.lower if bands else [], dtype=float),
                upper=np.asarray(bands.upper if bands else [], dtype=float),
                severity=severity,
                alert_threshold=np.array(job.alert_threshold),
                critical_threshold=np.array(job.critical_threshold),
                detector=np.array(result.detector),
                score_type=np.array(result.score_type),
                series_id=np.array(series.series_id),
                group=np.array("" if series.meta.get("group") is None else str(series.meta["group"])),
            )
            n_alerts = int((severity > SEVERITY_NORMAL).sum())
            total_alerts += n_alerts
            entries.append(
                {
                    "series_id": series.series_id,
                    "group": series.meta.get("group"),
                    "n": int(series.n),
                    "n_alerts": n_alerts,
                    "n_p0": int((severity == SEVERITY_P0).sum()),
                    "file": file_name,
                }
            )

        index = {
            "run_id": run.id,
            "job_id": job.id,
            "detector": job.detector,
            "generated_at": to_iso(utcnow()),
            "series": entries,
        }
        (target / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        store.finish_run(
            run.id, "success", n_series=len(entries), n_alerts=total_alerts
        )
        return run.id
    except Exception as exc:
        store.finish_run(run.id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise


def read_run_index(data_root: Path, run_id: int) -> dict:
    path = run_dir(data_root, run_id) / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"运行结果不存在: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))
