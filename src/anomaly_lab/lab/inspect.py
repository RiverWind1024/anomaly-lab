"""预检的数据准备阶段：取数 → 切窗 → 体检 → 形态推断。

⚠️ P0 的 `inspect` 与 P1 的 `run_experiment` **共用这一段** ——
   「预检看到的窗口」与「实验跑检测的窗口」必须是同一批，否则结论不可迁移。

P0 只做「看」：不跑检测、不落盘、不写报告。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from anomaly_lab.classification.classifier import classify
from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.data.nab import load_nab_series
from anomaly_lab.data.public import load_public_series
from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.lab.quality import PeriodCapability, period_capability, window_quality
from anomaly_lab.lab.sampling import (
    Window,
    plan_windows,
    stratify_windows,
    window_labels,
    window_slice,
)
from anomaly_lab.lab.spec import DataSpec
from anomaly_lab.lab.truth import attach_annotations
from anomaly_lab.platform.detectors import MIN_AUTO_POINTS
from anomaly_lab.platform.models import Metric
from anomaly_lab.platform.sources import get_connector
from anomaly_lab.platform.sources.base import series_from_frame
from anomaly_lab.platform.store import PlatformStore
from anomaly_lab.platform.timeutil import to_iso


@dataclass
class PreparedWindow:
    """一个已切好、已体检、已推断形态的窗口。"""

    window: Window
    quality: Any
    #: 窗口内的值与时间戳 —— 检测阶段直接用它，不必再切一次。
    bundle: SeriesBundle
    classification: dict[str, Any] | None
    classification_reason: str | None


@dataclass
class PreparedSeries:
    """一条序列的全部采样窗口。"""

    series: SeriesBundle
    windows: list[PreparedWindow]


@dataclass
class Prepared:
    """一次预检的数据准备结果。"""

    spec: DataSpec
    metric: Metric
    freq: str
    capability: PeriodCapability
    series: list[PreparedSeries]
    warnings: list[str]


def _resolve_metric(store: PlatformStore, spec: DataSpec) -> Metric:
    """把 DataSpec 变成一条 Metric。

    `kind="metric"` 用已有指标，但显式传的 freq / missing_policy 必须与指标一致 ——
    否则「实验所见」就不是「上线所得」。
    """
    if spec.kind == "metric":
        metric = store.get_metric(spec.metric_id)  # type: ignore[arg-type]
        if spec.freq is not None and spec.freq != metric.freq:
            raise ValueError(
                f"freq 与指标不一致：实验给的是 {spec.freq!r}，指标是 {metric.freq!r}"
            )
        if spec.missing_policy is not None and spec.missing_policy != metric.missing_policy:
            raise ValueError(
                "missing_policy 与指标不一致："
                f"实验给的是 {spec.missing_policy!r}，指标是 {metric.missing_policy!r}"
            )
        return metric

    # 临时 SQL：不落库，用 id=-1 的临时指标走同一条取数链路。
    return Metric(
        id=-1,
        source_id=spec.source_id,  # type: ignore[arg-type]
        name="lab",
        query=spec.sql,  # type: ignore[arg-type]
        time_column=spec.time_column,  # type: ignore[arg-type]
        value_column=spec.value_column,  # type: ignore[arg-type]
        group_column=spec.group_column,
        time_format=spec.time_format,
        freq=spec.freq,  # type: ignore[arg-type]
        created_at="",
        source_timezone=spec.source_timezone,
        missing_policy=spec.missing_policy or "drop",
    )


def _fetch_series(
    store: PlatformStore,
    metric: Metric,
    data_root: Path,
    start: datetime,
    end: datetime,
) -> list[SeriesBundle]:
    """与 runner.load_series 走同一条取数链路。"""
    source = store.get_source_raw(metric.source_id)
    connector = get_connector(source, data_root)
    frame = connector.fetch(metric, start, end)
    return series_from_frame(frame, metric)


def _fetch_synthetic(spec: DataSpec) -> list[SeriesBundle]:
    """合成数据 —— **自带真值标签**（P3）。

    ⚠️ **时间戳要平移到 `spec.start`** —— 生成器固定从 `SYNTHETIC_EPOCH`
       起算，不平移的话用户选的时间范围与数据永远对不上，
       切出来的窗口全是空的。
    """
    synth = spec.synthetic
    freq = spec.freq or "5min"
    bundle = generate_series(
        synth.metric_class,
        n=synth.n_points,
        seed=synth.seed,
        freq=freq,
        n_anomalies=synth.n_anomalies,
        anomaly_types=list(synth.anomaly_types) or None,
    )
    origin = np.datetime64(spec.start.replace(tzinfo=None), "ns")
    shift = origin - bundle.timestamps[0]
    return [
        SeriesBundle(
            series_id=bundle.series_id,
            values=bundle.values,
            timestamps=bundle.timestamps + shift,
            freq=bundle.freq,
            labels=bundle.labels,
            label_source=bundle.label_source,
            meta={**bundle.meta, "source": "synthetic"},
        )
    ]


def _fetch_public(spec: DataSpec, data_root: Path) -> list[SeriesBundle]:
    """公开集 —— **自带真值标签**（P3）。

    ⚠️ **不自动下载** —— 公开集动辄几十 MB，预检是交互式操作，
       不该在用户点一下按钮时偷偷下载。缓存缺失就直接报错，
       让用户显式去准备数据。
    """
    public = spec.public
    if public.dataset == "nab":
        return load_nab_series(
            cache_dir=data_root / "cache" / "nab",
            limit=public.limit,
            auto_download=False,
        )
    if public.name is None:
        raise ValueError("公开集必须指定序列名（public.name）")
    return [
        load_public_series(
            public.name,
            cache_dir=data_root / "cache" / "public",
            offline=True,
        )
    ]


def _select_windows(
    series: SeriesBundle,
    spec: DataSpec,
    freq: str,
) -> list[Window]:
    sampling = spec.sampling
    if sampling.mode != "stratified":
        return plan_windows(
            spec.start,
            spec.end,
            freq,
            window_points=sampling.window_points,
            stride_points=sampling.stride_points,
            max_points=sampling.max_points,
            max_windows=sampling.max_windows,
            mode=sampling.mode,
        )

    # 分层采样需要先拿到**全部**候选窗口，再按可疑度挑选。
    candidates = plan_windows(
        spec.start,
        spec.end,
        freq,
        window_points=sampling.window_points,
        stride_points=sampling.stride_points,
        max_points=10**9,
        max_windows=10_000,
        mode="even",
    )
    budget = min(sampling.max_windows, sampling.max_points // sampling.window_points)
    if budget <= 0:
        return []
    return stratify_windows(series, candidates, max_windows=budget)


def _window_bundle(series: SeriesBundle, window: Window, freq: str) -> SeriesBundle:
    values, timestamps = window_slice(series, window)
    return SeriesBundle(
        series_id=series.series_id,
        values=values,
        timestamps=timestamps,
        freq=freq,
        # ⚠️ 真值要**跟着窗口切** —— 否则窗口内的告警点无法与真值点对齐。
        labels=window_labels(series, window),
        label_source=series.label_source if series.labels is not None else "none",
    )


def _classify_window(
    bundle: SeriesBundle,
    n: int,
) -> tuple[dict[str, Any] | None, str | None]:
    if n < MIN_AUTO_POINTS:
        return None, f"点数不足：窗口只有 {n} 点，形态推断至少需要 {MIN_AUTO_POINTS} 点"
    result = classify(bundle)
    return (
        {
            "metric_class": result.metric_class,
            "confidence": round(float(result.confidence), 4),
            "reasons": list(result.reasons),
            "candidates": list(result.recommendation.detectors),
            "params": result.recommendation.params,
            "rationale": result.recommendation.rationale,
        },
        None,
    )


def _shape_summary(windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """把多个窗口的形态聚合成一个「这条序列大概是什么形态」。"""
    classified = [w["classification"] for w in windows if w["classification"]]
    if not classified:
        return None

    counts = Counter(item["metric_class"] for item in classified)
    majority, hits = counts.most_common(1)[0]
    same = [item for item in classified if item["metric_class"] == majority]
    return {
        "metric_class": majority,
        "confidence": round(sum(item["confidence"] for item in same) / len(same), 4),
        "consistency": round(hits / len(classified), 4),
        "candidates": same[0]["candidates"],
        "n_classified": len(classified),
        "n_windows": len(windows),
    }


def _data_span(series: SeriesBundle) -> tuple[str | None, str | None]:
    """序列**实际**覆盖的时间跨度（UTC ISO）。

    ⚠️ 这是「数据真的有在哪」—— 用户选的范围可能远大于它。
       窗口切在没数据的地方，只会得到一堆空窗口。
    """
    if series.n == 0:
        return None, None
    stamps = series.timestamps.astype("datetime64[s]")
    first = datetime.fromtimestamp(int(stamps[0].astype(int)), tz=UTC)
    last = datetime.fromtimestamp(int(stamps[-1].astype(int)), tz=UTC)
    return to_iso(first), to_iso(last)


def _short(iso_value: str) -> str:
    """`2026-10-28T16:03:00+00:00` → `10-28 16:03` —— 告警文案里用的紧凑写法。"""
    text = iso_value.replace("T", " ")
    return text[:16]


def _cover_span(bundles: list[SeriesBundle]) -> tuple[datetime, datetime] | None:
    """一批序列**实际**覆盖的时间跨度。"""
    starts = [item.timestamps[0] for item in bundles if item.n]
    ends = [item.timestamps[-1] for item in bundles if item.n]
    if not starts:
        return None
    low = min(starts).astype("datetime64[s]").astype(int)
    high = max(ends).astype("datetime64[s]").astype(int)
    return (
        datetime.fromtimestamp(int(low), tz=UTC),
        datetime.fromtimestamp(int(high), tz=UTC),
    )


def _placeholder_metric(spec: DataSpec, freq: str) -> Metric:
    """合成 / 公开集的占位指标。

    ⚠️ 它们**没有指标实体** —— 但 `Prepared` 里要有一个 `Metric` 槽位，
       这里只填「占得住」的默认值，不让下游误以为真能拿去建任务。
    """
    return Metric(
        id=-1,
        source_id=-1,
        name=f"lab:{spec.kind}",
        query="",
        time_column="ts",
        value_column="value",
        group_column=None,
        time_format=spec.time_format,
        freq=freq,
        created_at="",
        source_timezone=spec.source_timezone,
        missing_policy="drop",
    )


def _ensure_truth_windows(
    series: SeriesBundle,
    windows: list[Window],
    spec: DataSpec,
    freq: str,
) -> tuple[list[Window], int]:
    """把**含真值点的窗口**补进采样结果。

    ⚠️ **为什么必须补**：
       采样是「均匀挑选 N 个窗口」，真值点很稀疏时（公开集尤其明显）
       挑中的窗口可能一个异常都不含 —— 那评估出来的「召回率」是假的，
       漏报根本没被统计进去。

    ⚠️ 超出 `max_windows` 时**优先保留真值窗口** ——
       宁可少看几个正常窗口，也不能漏掉异常。
    """
    labels = series.labels
    if labels is None or not labels.any():
        return windows, 0

    sampling = spec.sampling
    candidates = plan_windows(
        spec.start,
        spec.end,
        freq,
        window_points=sampling.window_points,
        stride_points=sampling.stride_points,
        max_points=10**9,
        max_windows=10_000,
        mode="even",
    )
    picked = {item.index for item in windows}
    missing = [
        item
        for item in candidates
        if item.index not in picked and window_labels(series, item).any()
    ]
    if not missing:
        return windows, 0

    merged = sorted(windows + missing, key=lambda item: item.index)
    if len(merged) > sampling.max_windows:
        # ⚠️ **所有**含真值的窗口都要留 —— 包括原先就选中的那些。
        #    只留「后补的」会把原选中窗口里的真值点又漏掉。
        keep = [item for item in merged if window_labels(series, item).any()]
        room = max(0, sampling.max_windows - len(keep))
        others = [item for item in merged if not window_labels(series, item).any()]
        merged = sorted(keep + others[:room], key=lambda item: item.index)
    return merged, len(missing)


def prepare(
    store: PlatformStore,
    data_root: Path,
    spec: DataSpec,
) -> Prepared:
    """取数 → 切窗 → 体检 → 形态推断。**不跑检测**。

    这是 P0 与 P1 共享的唯一数据入口 —— 保证两阶段看的是同一批窗口。
    """
    warnings: list[str] = []

    if spec.kind == "synthetic":
        bundles = _fetch_synthetic(spec)
        freq = spec.freq or "5min"
        metric = _placeholder_metric(spec, freq)
    elif spec.kind == "public":
        bundles = _fetch_public(spec, data_root)
        freq = spec.freq or (bundles[0].freq if bundles else "5min")
        metric = _placeholder_metric(spec, freq)
        # ⚠️ 公开集的时间范围是**数据自己定的**（NAB 是 2014 年的真实数据）。
        #    让用户去猜范围没有意义 —— 直接按数据实际覆盖区间切窗，
        #    并把 spec 改成实际生效的范围（复现要靠它）。
        span = _cover_span(bundles)
        if span is not None:
            spec = replace(spec, start=span[0], end=span[1])
            metric = _placeholder_metric(spec, freq)
            warnings.append(
                f"公开集按数据实际覆盖区间切窗：{span[0].isoformat()} ~ {span[1].isoformat()}"
            )
        # ⚠️ 公开集各序列频率可能不同 —— 切窗按第一条的频率走，
        #    频率不同的那条会被切歪，必须说出来。
        others = sorted({item.freq for item in bundles} - {freq})
        if others:
            warnings.append(
                f"公开集里各序列频率不一致（{freq} / {', '.join(others)}）—— "
                "已按第一条的频率切窗，其它序列的窗口可能有偏移"
            )
    else:
        metric = _resolve_metric(store, spec)
        freq = metric.freq
        bundles = _fetch_series(store, metric, data_root, spec.start, spec.end)

    capability = period_capability(spec.sampling.window_points, freq)

    if not bundles:
        warnings.append("没有取到数据：请检查时间范围、查询条件与数据源连接")
        return Prepared(spec, metric, freq, capability, [], warnings)

    if len(bundles) > spec.max_series:
        warnings.append(
            f"共 {len(bundles)} 条序列，按 max_series 只纳入前 {spec.max_series} 条，"
            f"其余 {len(bundles) - spec.max_series} 条未纳入"
        )
        bundles = bundles[: spec.max_series]

    # ⚠️ 人工标注要在**切窗之前**贴上 —— 切窗时会连同标签一起切，
    #    贴晚了标签就对不上窗口里的点了。
    if spec.truth == "annotation":
        bundles = [attach_annotations(item, data_root) for item in bundles]
        annotated = sum(
            1 for item in bundles if item.label_source == "human" and item.labels is not None
        )
        if not annotated:
            warnings.append(
                "没有找到人工标注 —— 标注文件按序列 id 命名，"
                "放在「annotations/<序列 id>.jsonl」；序列 id 要与这里完全一致"
            )

    prepared: list[PreparedSeries] = []
    n_truth_added = 0
    for series in bundles:
        selected = _select_windows(series, spec, freq)
        selected, n_added = _ensure_truth_windows(series, selected, spec, freq)
        n_truth_added += n_added
        windows: list[PreparedWindow] = []
        for window in selected:
            quality = window_quality(
                series,
                window,
                freq=freq,
                min_valid_ratio=spec.sampling.min_valid_ratio,
            )
            bundle = _window_bundle(series, window, freq)
            classification, reason = _classify_window(bundle, quality.n)
            windows.append(
                PreparedWindow(
                    window=window,
                    quality=quality,
                    bundle=bundle,
                    classification=classification,
                    classification_reason=reason,
                )
            )
        if len(windows) > spec.sampling.max_windows:
            warnings.append(
                f"序列 {series.series_id} 用了 {len(windows)} 个窗口，"
                f"超过 max_windows（{spec.sampling.max_windows}）—— "
                "含真值的窗口必须保留，预算只能往后靠"
            )
        if not windows:
            warnings.append(
                f"序列 {series.series_id} 的时间范围不足一个窗口"
                f"（需要 {spec.sampling.window_points} 点 @{freq}），无法采样"
            )
        else:
            empty = sum(1 for item in windows if item.quality.n == 0)
            # ⚠️ 大半窗口是空的 —— 通常是「时间范围没覆盖到实际数据」，
            #    而不是「数据本身稀疏」。不提示的话，用户会以为指标没数据。
            if empty * 2 > len(windows):
                data_start, data_end = _data_span(series)
                coverage_note = (
                    f"（数据实际覆盖 {_short(data_start)} ~ {_short(data_end)}）"
                    if data_start and data_end
                    else ""
                )
                warnings.append(
                    f"序列 {series.series_id} 的 {len(windows)} 个窗口里有 {empty} 个没有数据 —— "
                    f"时间范围可能没覆盖到实际数据{coverage_note}，请把范围调到数据实际所在区间"
                )
        prepared.append(PreparedSeries(series=series, windows=windows))

    if n_truth_added:
        warnings.append(
            f"额外纳入 {n_truth_added} 个含真值的窗口 —— "
            "均匀采样会漏掉稀疏的异常点，不补上的话漏报不会被统计进去"
        )

    return Prepared(spec, metric, freq, capability, prepared, warnings)


def _window_report(item: PreparedWindow) -> dict[str, Any]:
    quality = item.quality
    return {
        "index": quality.index,
        "start": to_iso(quality.start),
        "end": to_iso(quality.end),
        "n": quality.n,
        "expected": quality.expected,
        "n_missing": quality.n_missing,
        "missing_ratio": round(quality.missing_ratio, 4),
        "zero_ratio": round(quality.zero_ratio, 4),
        "duplicate_timestamps": quality.duplicate_timestamps,
        "on_grid_ratio": round(quality.on_grid_ratio, 4),
        "median_interval_s": quality.median_interval_s,
        "min": quality.min,
        "max": quality.max,
        "mean": quality.mean,
        "std": quality.std,
        "sufficient": quality.sufficient,
        "insufficient_reason": quality.insufficient_reason,
        "classification": item.classification,
        "classification_reason": item.classification_reason,
    }


def spec_dict(spec: DataSpec) -> dict[str, Any]:
    """DataSpec 的可序列化视图（时间统一成 ISO）。

    ⚠️ **含 sampling** —— 前端拿到这份 spec 就能原样再发一次请求
       （比如拉单个窗口的曲线），不必自己拼。
    """
    return {
        "kind": spec.kind,
        "metric_id": spec.metric_id,
        "source_id": spec.source_id,
        "sql": spec.sql,
        "time_column": spec.time_column,
        "value_column": spec.value_column,
        "group_column": spec.group_column,
        "time_format": spec.time_format,
        "source_timezone": spec.source_timezone,
        "freq": spec.freq,
        "missing_policy": spec.missing_policy,
        "max_series": spec.max_series,
        "start": to_iso(spec.start),
        "end": to_iso(spec.end),
        "sampling": asdict(spec.sampling),
        "truth": spec.truth,
        "synthetic": asdict(spec.synthetic),
        "public": asdict(spec.public),
    }


def inspect(store: PlatformStore, data_root: Path, spec: DataSpec) -> dict[str, Any]:
    """跑一次预检，返回纯 JSON 可序列化的结果。"""
    prepared = prepare(store, data_root, spec)

    series_reports: list[dict[str, Any]] = []
    for item in prepared.series:
        reports = [_window_report(window) for window in item.windows]
        start, end = _data_span(item.series)
        labels = item.series.labels
        series_reports.append(
            {
                "series_id": item.series.series_id,
                "group": item.series.meta.get("group"),
                "n": item.series.n,
                "data_start": start,
                "data_end": end,
                # ⚠️ 真值情况要**在预检就报出来** —— 否则用户跑到评估那步
                #    才发现「这条序列根本没有标注」，白折腾一轮。
                "n_truth": int(labels.sum()) if labels is not None else 0,
                "label_source": item.series.label_source,
                "windows": reports,
                "shape": _shape_summary(reports),
            }
        )

    return {
        "spec": spec_dict(prepared.spec),
        "freq": prepared.freq,
        "window_points": prepared.spec.sampling.window_points,
        "sampling": asdict(prepared.spec.sampling),
        "period_capability": asdict(prepared.capability),
        "series": series_reports,
        "warnings": prepared.warnings,
    }
