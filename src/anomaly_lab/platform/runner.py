"""执行一个检测任务：取数 → 打分 → 分级 → 落盘。

结果按「一次 run 一个目录」组织：index.json 描述有哪些序列，
每条序列一个 npz（实际值、分数、基线、上下界、告警等级）。
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.bands import compute_bands
from anomaly_lab.platform.alerts import (
    SEVERITY_NORMAL,
    apply_direction,
    band_multiplier_or_none,
    default_rules,
    highest_multiplier,
    level_labels,
    merge_alert_intervals,
    parse_direction,
    parse_rules,
    rules_to_dicts,
    severity_from_conditions,
)
from anomaly_lab.platform.detectors import create_detector, resolve_detector
from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.sources import get_connector
from anomaly_lab.platform.sources.base import series_from_frame
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import freq_delta, to_iso, utcnow

# 正在执行的任务：job_id -> run_id。避免「手动触发」和「调度到点」重复跑同一个任务。
_INFLIGHT: dict[int, int] = {}
_INFLIGHT_LOCK = threading.Lock()


def run_dir(data_root: Path, run_id: int) -> Path:
    return Path(data_root) / "cache" / "platform" / "runs" / str(run_id)


def load_series(
    store: PlatformStore,
    metric: Metric,
    data_root: Path,
    start: datetime,
    end: datetime,
) -> list[SeriesBundle]:
    """按指标所属数据源取数（走连接器层）。

    ⚠️ 模块级函数名保留 `load_series` —— 既有测试 monkeypatch 的目标就是它。
    """
    source = store.get_source_raw(metric.source_id)
    connector = get_connector(source, data_root)
    frame = connector.fetch(metric, start, end)
    return series_from_frame(frame, metric)


def job_rules(job) -> list:
    """任务规则表；老数据没有规则时回落到两个阈值。"""
    rules = parse_rules(getattr(job, "alert_rules", None) or [])
    if rules:
        return rules
    return default_rules(job.alert_threshold, job.critical_threshold)


def is_running(job_id: int) -> bool:
    """任务是不是正在跑。

    手动触发与调度到点都登记在 `_INFLIGHT` 里，所以这里能覆盖两种来源。
    删除任务前要检查 —— 否则 run 还在写、文件已经被删掉了。
    """
    with _INFLIGHT_LOCK:
        return job_id in _INFLIGHT


def inflight_run_ids() -> set[int]:
    """当前正在执行的 run_id 集合。

    保留策略用它来避开「正在写」的那次运行 ——
    删掉它的目录，runner 往里写 npz 时就会失败。
    """
    with _INFLIGHT_LOCK:
        return set(_INFLIGHT.values())


def _file_name(series_id: str) -> str:
    digest = hashlib.sha1(series_id.encode("utf-8")).hexdigest()[:16]
    return f"{digest}.npz"


def content_hash(series_id: str, timestamps: np.ndarray, severity: np.ndarray) -> str:
    """**检测内容指纹** —— 识别「这是同一次检测」。

    ⚠️ 滚动窗口下，同一段异常会被连续多次运行反复报出 ——
       如果只用 run_id 区分，每次运行都是「一条新记录」，
       抽样会抽到一堆内容完全相同的记录，人工要重复标同一件事。
       指纹相同 = 检测内容相同（同样的序列、同样的时间轴、同样的告警分布）。
    """
    digest = hashlib.sha1()
    digest.update(series_id.encode("utf-8"))
    digest.update(np.asarray(timestamps, dtype=np.int64).tobytes())
    digest.update(np.asarray(severity, dtype=np.int16).tobytes())
    return digest.hexdigest()[:16]


def _iso(ns: int) -> str:
    """纳秒时间戳 → naive ISO 字符串（秒精度）。"""
    return str(np.datetime64(int(ns), "ns").astype("datetime64[s]"))


def _alert_rows(outcome: SeriesOutcome) -> list[dict]:
    """一条序列报出的告警区间 —— 写进 `alert_events` 表的行。

    ⚠️ **逐点的 severity 才是事实**；区间是它的合并视图。
       区间边界取「连续告警点」的首尾，与告警页展示的口径一致。
    """
    severity = outcome.arrays.get("severity")
    timestamps = outcome.arrays.get("timestamps")
    if severity is None or timestamps is None:
        return []
    scores = outcome.arrays.get("scores")
    levels = outcome.levels
    detector = str(outcome.entry.get("detector") or "")
    score_type = str(outcome.arrays.get("score_type") or "")

    rows: list[dict] = []
    for start, end, level_index in merge_alert_intervals(severity):
        level = levels[level_index] if 0 < level_index < len(levels) else "未知"
        window = scores[start : end + 1] if scores is not None else None
        rows.append(
            {
                "series_id": str(outcome.entry.get("series_id", "")),
                "group": outcome.entry.get("group"),
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


def execute_job(
    store: PlatformStore,
    job_id: int,
    *,
    data_root: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> int:
    """执行一次任务，返回 run_id；已在执行时直接复用那次 run。"""
    job = store.get_job(job_id)
    with _INFLIGHT_LOCK:
        existing = _INFLIGHT.get(job.id)
        if existing is not None:
            return existing
        run = store.create_run(job.id)
        _INFLIGHT[job.id] = run.id
    try:
        return _run_job(
            store, job, run, data_root=data_root, start=start, end=end, now=now
        )
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(job.id, None)


def execute_job_test(
    store: PlatformStore,
    job_id: int,
    *,
    data_root: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> TestResult:
    """**试跑**一次任务：真实执行，但不落库、不落盘。

    ⚠️ **与真实执行走同一段代码** —— `_compute_job` 是共用的，
       取数、检测器选择、打分、分级全都一致。
       差别只有两处：不写 `runs` 表、不写结果文件。

    ⚠️ 所以「试跑的结果」**就是**「真跑一次的结果」，
       而不是「另一套近似逻辑算出来的近似结果」。
    """
    job = store.get_job(job_id)
    outcomes = _compute_job(
        store, job, data_root=data_root, start=start, end=end, now=now
    )
    return TestResult(job=job, outcomes=outcomes)


@dataclass
class SeriesOutcome:
    """一条序列的检测结果（内存态）。

    ⚠️ `arrays` 的键名与**落盘的 npz 完全一致** ——
       真实执行把它存成 npz，试跑把它直接序列化成 JSON，
       两条路给前端的东西是同一套。
    """

    #: 索引条目 —— 与 index.json 里那条同构
    entry: dict
    #: 检测结果数组（timestamps / values / scores / severity / 基线带…）
    arrays: dict[str, np.ndarray]
    #: 告警规则表（序列化后给前端）
    alert_rules: list[dict]
    #: 档位名（["正常", "P1", "P0"]）
    levels: list[str]


@dataclass
class TestResult:
    """一次试跑的完整结果。"""

    job: object
    outcomes: list[SeriesOutcome]

    @property
    def n_alerts(self) -> int:
        return sum(int(o.entry.get("n_alerts", 0)) for o in self.outcomes)

    @property
    def n_p0(self) -> int:
        return sum(int(o.entry.get("n_p0", 0)) for o in self.outcomes)

    @property
    def n_insufficient(self) -> int:
        return sum(1 for o in self.outcomes if not o.entry.get("sufficient", True))


def _compute_job(
    store: PlatformStore,
    job,
    *,
    data_root: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> list[SeriesOutcome]:
    """取数 → 打分 → 分级。**不落盘**。

    ⚠️ 真实执行（`_run_job`）与试跑（`execute_job_test`）**共用这一段** ——
       两者的结果一致是结构性保证，不是靠两边手写得像。
    """
    metric = store.get_metric(job.metric_id)
    end_time = end or now or utcnow()
    start_time = start or (end_time - freq_delta(metric.freq) * job.window_points)
    series_list = load_series(store, metric, data_root, start_time, end_time)
    rules = job_rules(job)
    direction = parse_direction(getattr(job, "alert_direction", "both"))
    # 没有倍数条件时（规则全是绝对值条件）没有「上下界宽度」可言 ——
    # 退回到检测器自己的默认阈值。分级由规则表决定，不受影响。
    band_width = band_multiplier_or_none(rules)
    levels = level_labels(rules)
    critical_ref = highest_multiplier(rules) or band_width
    # 最高档的序号 = 规则条数（0 号固定是「正常」）
    top_level = len(rules)

    outcomes: list[SeriesOutcome] = []
    for series in series_list:
        sufficient = bool(series.meta.get("sufficient", True))
        if not sufficient:
            # 有效点太少：明确标记「数据不足」，绝不能当成「一切正常」
            outcomes.append(
                SeriesOutcome(
                    entry={
                        "series_id": series.series_id,
                        "group": series.meta.get("group"),
                        "n": int(series.n),
                        "n_valid": int(series.meta.get("n_valid", series.n)),
                        "n_missing": int(series.meta.get("n_missing", 0)),
                        "n_alerts": 0,
                        "n_p0": 0,
                        "sufficient": False,
                        "file": None,
                        "alert_direction": direction,
                        "direction_applied": True,
                    },
                    arrays={},
                    alert_rules=rules_to_dicts(rules),
                    levels=levels,
                )
            )
            continue
        resolution = resolve_detector(job.detector, series)
        detector = create_detector(resolution.detector).fit(series)
        # 没有倍数条件时用检测器自己的默认阈值（如 Chronos 的 0.5）
        width = band_width if band_width is not None else float(detector.default_threshold)
        result = detector.detect(series, threshold=width)
        bands = compute_bands(detector, series, width)
        severity = severity_from_conditions(result.scores, series.values, rules)
        severity, direction_applied = apply_direction(
            severity, series.values, result.expected, direction
        )
        outcomes.append(
            SeriesOutcome(
                entry={
                    "series_id": series.series_id,
                    "group": series.meta.get("group"),
                    "n": int(series.n),
                    "n_valid": int(series.meta.get("n_valid", series.n)),
                    "n_missing": int(series.meta.get("n_missing", 0)),
                    "n_alerts": int((severity > SEVERITY_NORMAL).sum()),
                    "n_p0": int((severity == top_level).sum()),
                    "sufficient": True,
                    "detector": resolution.detector,
                    "metric_class": resolution.metric_class,
                    "fallback": resolution.fallback,
                    "scale_source": result.scale_source or "",
                    "status": result.status,
                    "scale_fallback": bool(result.scale_fallback),
                    # 算法的首选尺度 —— 前端据此把「IQR/MAD 失效」的警告
                    # 匹配到 seasonal / stl_residual 这类复用同一尺度族的算法上
                    "scale_prefer": getattr(detector, "prefer_scale", "") or "",
                    "file": _file_name(series.series_id),
                    "alert_direction": direction,
                    "direction_applied": bool(direction_applied),
                },
                arrays={
                    "timestamps": series.timestamps.astype("datetime64[ns]").astype(np.int64),
                    "values": series.values,
                    "scores": result.scores,
                    "baseline": np.asarray(bands.baseline if bands else [], dtype=float),
                    "lower": np.asarray(bands.lower if bands else [], dtype=float),
                    "upper": np.asarray(bands.upper if bands else [], dtype=float),
                    "severity": severity,
                    "alert_threshold": np.array(width),
                    "critical_threshold": np.array(
                        critical_ref if critical_ref is not None else width
                    ),
                    "alert_rules": np.array(json.dumps(rules_to_dicts(rules), ensure_ascii=False)),
                    "levels": np.array(json.dumps(levels, ensure_ascii=False)),
                    "detector": np.array(result.detector),
                    "requested_detector": np.array(job.detector),
                    "metric_class": np.array(resolution.metric_class or ""),
                    "detector_rationale": np.array(resolution.rationale),
                    "score_type": np.array(result.score_type),
                    "scale_source": np.array(result.scale_source or ""),
                    "status": np.array(result.status),
                    "scale_fallback": np.array(result.scale_fallback),
                    "series_id": np.array(series.series_id),
                    "group": np.array(
                        "" if series.meta.get("group") is None else str(series.meta["group"])
                    ),
                },
                alert_rules=rules_to_dicts(rules),
                levels=levels,
            )
        )
    return outcomes


def _run_job(
    store: PlatformStore,
    job,
    run,
    *,
    data_root: Path,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> int:
    try:
        outcomes = _compute_job(
            store, job, data_root=data_root, start=start, end=end, now=now
        )
        target = run_dir(data_root, run.id)
        target.mkdir(parents=True, exist_ok=True)
        entries: list[dict] = []
        db_entries: list[dict] = []
        alert_rows: list[dict] = []
        total_alerts = 0
        n_insufficient = 0

        for outcome in outcomes:
            entry = dict(outcome.entry)
            file_name = entry.get("file")
            fingerprint = ""
            start_ts = end_ts = ""
            if file_name:
                np.savez_compressed(target / file_name, **outcome.arrays)
                stamps = outcome.arrays["timestamps"]
                fingerprint = content_hash(
                    str(entry.get("series_id", "")),
                    stamps,
                    outcome.arrays["severity"],
                )
                # ⚠️ 时间范围要落库 —— 标注按序列存，得靠它判断
                #    「这条标注落在哪几次检测里」，逐条读 npz 太慢。
                if len(stamps):
                    start_ts = _iso(stamps[0])
                    end_ts = _iso(stamps[-1])
                alert_rows.extend(_alert_rows(outcome))
            else:
                n_insufficient += 1
            total_alerts += int(entry.get("n_alerts", 0))
            entries.append(entry)
            db_entries.append(
                {
                    **entry,
                    "content_hash": fingerprint,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                }
            )

        index = {
            "run_id": run.id,
            "job_id": job.id,
            "detector": job.detector,
            "generated_at": to_iso(utcnow()),
            "n_insufficient": n_insufficient,
            "series": entries,
        }
        (target / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # ⚠️ **检测记录落库** —— 索引与告警区间都要进数据库，
        #    否则「有哪些检测记录」只能扫产物目录（实测 8700 多个目录 = 0.47s）。
        store.record_run_series(run.id, db_entries)
        store.record_alert_events(run.id, job.id, alert_rows)
        status = "insufficient_data" if entries and n_insufficient == len(entries) else "success"
        store.finish_run(
            run.id, status, n_series=len(entries), n_alerts=total_alerts
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
