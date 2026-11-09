"""生产检测记录的人工标注评估。

⚠️ **与基准评估的本质区别**：
   基准评估（`evaluation/backtest.py`）的真值是**自动注入**的，覆盖全集；
   这里的真值是**人工标的** —— 每一条结论只覆盖「被标注过的那部分」，
   永远不能当成「这个指标的整体效果」。

⚠️ **预测侧直接用线上跑出来的那份**（`cache/platform/runs/<run_id>/*.npz`），
   不重跑 —— 重跑算的是「现在跑会怎样」，不是「当时跑成了怎样」。
   npz 里已有 `timestamps / values / scores / severity`，时间轴与波形都齐。

⚠️ **总体 = 所有检测记录**（检出正常的、检出异常的，都算）：
   - **异常**记录（报出了告警）决定 **Precision** —— 告警里有多少是真的；
   - **正常**记录（什么都没报）决定 **Recall** —— 真异常里有多少被漏掉。

   只标异常记录的话，**漏报永远是 0**，Recall 会被严重高估。
   所以「正常」记录不是可选项，是估 Recall 的唯一来源。

⚠️ **正常层与异常层用不同的采样率** —— 正常记录远多于异常记录，
   同一个采样率要么标不完（正常层），要么异常样本太少（Precision 方差大）。

⚠️ **候选清单来自数据库**（`run_series` 表），不扫产物目录 ——
   扫描 8700 多个目录实测 0.47s，且随运行数线性涨。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from anomaly_lab.evaluation.metrics import precision_recall_f1, range_based_prf
from anomaly_lab.lab.truth import is_reviewed, load_all_annotations
from anomaly_lab.platform.store import PlatformStore

#: 毫秒 → 纳秒（numpy 的时间精度是 ns）。
_MS_TO_NS = 1_000_000

#: 检出结果：这条检测记录**报出了告警**。
OUTCOME_ALERT = "alert"
#: 检出结果：这条检测记录**什么都没报**。
OUTCOME_NORMAL = "normal"

#: 检出结果的中文名。
OUTCOME_LABELS = {OUTCOME_ALERT: "异常", OUTCOME_NORMAL: "正常"}

#: 异常层的默认采样率 —— 异常记录少，抽得狠一点。
DEFAULT_RATE_ALERT = 0.5
#: 正常层的默认采样率 —— 正常记录极多，只能抽一点点。
DEFAULT_RATE_NORMAL = 0.05
#: 每层最多标几条 —— 标注是人工的，每层十几条才现实。
DEFAULT_MAX_PER_LAYER = 10


def run_dir(data_root: Path, run_id: int) -> Path:
    """某次运行的产物目录。"""
    return Path(data_root) / "cache" / "platform" / "runs" / str(run_id)


def _boundary_ns(value: object) -> int | None:
    """标注边界 → 纳秒时间戳。

    ⚠️ 与 `lab/truth.py` 同一套解析（naive ISO / 毫秒时间戳都认）——
       标注页存的是 naive ISO（与 run 的 timestamps 同源）。
    """
    if isinstance(value, (int, float)):
        return int(value) * _MS_TO_NS
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return int(np.datetime64(parsed, "ns").astype(np.int64))
    return None


def _truth_mask(timestamps_ns: np.ndarray, records: list[dict[str, Any]]) -> np.ndarray:
    """标注区间 → 点级真值掩码。

    ⚠️ 区间是**闭区间**；落在检测记录时间轴**之外**的部分直接丢掉 ——
       那一段没有预测可比，算进去只会稀释指标。
    """
    mask = np.zeros(len(timestamps_ns), dtype=bool)
    if len(timestamps_ns) == 0:
        return mask
    for record in records:
        # ⚠️ 「核对过」不是真值 —— 它只说明这段被看过，不代表有异常。
        if is_reviewed(record):
            continue
        start = _boundary_ns(record.get("start"))
        end = _boundary_ns(record.get("end"))
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        lo = int(np.searchsorted(timestamps_ns, start, side="left"))
        hi = int(np.searchsorted(timestamps_ns, end, side="right"))
        if hi > lo:
            mask[lo:hi] = True
    return mask


#: (run_id, series_id) → (起始 ts, 结束 ts)
WindowMap = dict[tuple[int, str], tuple[str, str]]


def _window_map(candidates: list[Candidate]) -> WindowMap:
    """(run_id, series_id) → 这次检测的时间范围。"""
    return {
        (item.run_id, item.series_id): (item.start_ts, item.end_ts)
        for item in candidates
        if item.start_ts and item.end_ts
    }


def _record_span(
    record: dict[str, Any], series_id: str, windows: WindowMap
) -> tuple[int, int] | None:
    """一条标注记录覆盖的时间段（纳秒）。

    ⚠️ `reviewed` 记录没有自己的边界 —— 覆盖范围是**那次运行的整个窗口**，
       窗口从 `run_series` 的时间范围取。
    """
    if is_reviewed(record):
        run_id = record.get("run_id")
        if run_id is None:
            return None
        span = windows.get((int(run_id), series_id))
        if span is None:
            return None
        low, high = _boundary_ns(span[0]), _boundary_ns(span[1])
    else:
        low = _boundary_ns(record.get("start"))
        high = _boundary_ns(record.get("end"))
    if low is None or high is None:
        return None
    return (high, low) if high < low else (low, high)


def _coverage_spans(
    records: list[dict[str, Any]],
    series_id: str,
    windows: WindowMap,
) -> list[tuple[int, int]]:
    """**用户核对过的时间段** —— 只有这些时间段有资格计分。

    ⚠️ 两种来源：

    - `type="reviewed"` → 那次运行的**整个窗口**核对过（用户点「这条记录正常」
      或保存了标注，就说明他看完了那条波形）；
    - 异常区间 → **它自己那一段**（老数据没有 reviewed 记录，退化成保守口径：
      只认用户明确画过的地方，不把没看过的地方当正常）。

    ⚠️ 没有这个，评估只能把「没标的地方」当正常 —— 一条 6 分钟的标注
       会让同一窗口里其余几十个告警点**凭空变成误报**。
    """
    spans: list[tuple[int, int]] = []
    for record in records:
        span = _record_span(record, series_id, windows)
        if span is not None:
            spans.append(span)
    return spans


def _coverage_mask(stamps: np.ndarray, spans: list[tuple[int, int]]) -> np.ndarray:
    """点级「核对过」掩码。"""
    mask = np.zeros(len(stamps), dtype=bool)
    for low, high in spans:
        lo = int(np.searchsorted(stamps, low, side="left"))
        hi = int(np.searchsorted(stamps, high, side="right"))
        if hi > lo:
            mask[lo:hi] = True
    return mask


def _mask_to_intervals(mask: np.ndarray) -> list[tuple[int, int]]:
    mask = np.asarray(mask).astype(bool)
    if not mask.any():
        return []
    padded = np.concatenate([[False], mask, [False]])
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:]) - 1
    return list(zip(starts.tolist(), ends.tolist(), strict=True))


@dataclass
class ProductionSample:
    """一条生产检测记录 —— 评估的最小单位。"""

    run_id: int
    series_id: str
    group: str | None
    job_id: int
    detector: str
    metric_id: int
    metric_name: str
    source_id: int
    source_name: str
    n: int
    n_alerts: int
    start_ts: str
    end_ts: str
    n_annotations: int
    n_truth: int
    #: 这次运行的时间段**用户核对过**吗 —— 没核对过就没法评估。
    reviewed: bool = False
    #: 检出结果 —— 「报出了告警」还是「什么都没报」。
    outcome: str = OUTCOME_NORMAL
    #: 它被抽中时所在层的采样率 —— 标注时存进标注记录，反算时做权重。
    rate: float = 1.0
    #: 它所在层的候选总量（检测记录数）。
    layer_size: int = 1
    #: 形态分类（stationary / periodic / ...）；老产物可能为空。
    metric_class: str = ""


@dataclass
class Candidate:
    """一条候选检测记录 —— 抽样的总体单位。

    ⚠️ **一条 = 一次运行里的一条序列** —— 不是「最新一次」，
       多次运行合起来才看得出「这个指标这段时间表现如何」。
    """

    run_id: int
    series_id: str
    group: str | None
    job_id: int
    detector: str
    metric_id: int
    metric_name: str
    source_id: int
    source_name: str
    n: int
    n_alerts: int
    #: 产物文件名 —— 直接读 npz，不用再翻 index.json。
    file: str = ""
    #: 这次检测覆盖的时间范围（naive ISO）—— 判断「哪条标注落在里面」。
    start_ts: str = ""
    end_ts: str = ""
    #: 检测内容指纹 —— 相同 = 同一次检测（活数据源每次都不同；
    #: 静态数据源 / 手动重跑才会重复）。
    content_hash: str = ""
    #: 该条被抽中时**它所在层的采样率** —— 反算总体量时用它做权重。
    rate: float = 1.0
    #: 该层候选的总量（分层抽样估计的 N_h）。
    layer_size: int = 1
    #: 形态分类（stationary / periodic / ...）；老产物可能为空。
    metric_class: str = ""

    @property
    def outcome(self) -> str:
        """检出结果 —— 报出了告警就是「异常」。"""
        return OUTCOME_ALERT if self.n_alerts > 0 else OUTCOME_NORMAL

    @property
    def weight(self) -> float:
        """这条记录代表总体里的多少条检测记录 —— 权重的倒数是采样率。

        ⚠️ **同一异常被多次报出不改变这个权重** ——
           重复的因子在 TP 与 FP 里同时出现，比值不受影响。
        """
        return 1.0 / self.rate if self.rate > 0 else 1.0


def list_candidates(
    store: PlatformStore,
    data_root: Path | None = None,
    *,
    job_id: int | None = None,
) -> list[Candidate]:
    """全部候选检测记录 —— 抽样的总体。

    ⚠️ **来自数据库**（`run_series` 表），不扫产物目录。
       「有哪些检测记录」是一条 SQL，不是几千次文件读取。

    ⚠️ **每一次运行的每一条序列都是候选** —— 不是只有最新的那次。
    """
    rows = store.detection_records(job_id=job_id)
    return [
        Candidate(
            run_id=int(row["run_id"]),
            series_id=str(row["series_id"]),
            group=row["group_name"],
            job_id=int(row["job_id"]),
            detector=str(row["detector"] or ""),
            metric_id=int(row["metric_id"]),
            metric_name=str(row["metric_name"]),
            source_id=int(row["source_id"]),
            source_name=str(row["source_name"]),
            n=int(row["n"]),
            n_alerts=int(row["n_alerts"]),
            file=str(row["file"] or ""),
            start_ts=str(row["start_ts"] or ""),
            end_ts=str(row["end_ts"] or ""),
            content_hash=str(row["content_hash"] or ""),
            metric_class=str(row["metric_class"] or ""),
        )
        for row in rows
    ]


def _candidate_matches(
    item: Candidate,
    *,
    source_id: int | None,
    metric_id: int | None,
    detector: str | None,
    metric_class: str | None,
    start: str | None,
    end: str | None,
) -> bool:
    """候选是否落在标注页的筛选条件内。

    ⚠️ 时间用**区间重叠**判断，不是「完全包含」——
       用户选 1 小时，而检测记录跨 5 小时时，它仍然包含用户要看的时段。
    ⚠️ 时间列是 naive ISO（`2026-11-09T05:33:00`），字符串直接比较即可；
       两边格式必须一致（前端用 `YYYY-MM-DDTHH:mm:ss`）。
    """
    if source_id is not None and item.source_id != int(source_id):
        return False
    if metric_id is not None and item.metric_id != int(metric_id):
        return False
    if detector and item.detector != detector:
        return False
    if metric_class and item.metric_class != metric_class:
        return False
    if start and (not item.end_ts or item.end_ts < start):
        return False
    starts_after_end = bool(end and (not item.start_ts or item.start_ts > end))
    return not starts_after_end


def _layer_key(item: Candidate) -> tuple[int, int, str]:
    """层 = 数据源 → 指标 → **检出结果**。

    ⚠️ **检出结果必须是一层** —— 正常记录和异常记录的数量差几个量级，
       采样率也不同，混在一层里没法分别控制。
    """
    return (item.source_id, item.metric_id, item.outcome)


def _group_layers(
    candidates: list[Candidate],
) -> dict[tuple[int, int, str], list[Candidate]]:
    layers: dict[tuple[int, int, str], list[Candidate]] = {}
    for item in candidates:
        layers.setdefault(_layer_key(item), []).append(item)
    return layers


def stratified_sample(
    candidates: list[Candidate],
    *,
    rate_alert: float = DEFAULT_RATE_ALERT,
    rate_normal: float = DEFAULT_RATE_NORMAL,
    max_per_layer: int | None = DEFAULT_MAX_PER_LAYER,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """按「数据源 → 指标 → 检出结果」分层，层内等间隔抽样。

    ⚠️ **正常层与异常层用不同的采样率**：
       正常记录极多（大部分检测什么都没报），异常记录少。
       同一个采样率要么正常层标不完，要么异常层样本太少。

    ⚠️ **等间隔而不是随机**：
       - 随机抽样每次结果都可能不同 → 用户标过的记录下次就不在样本里了，
         标注全白费；
       - 等间隔（按 run_id 排序 = 时间顺序）既确定又能覆盖时间跨度。

    ⚠️ **抽样单位就是「一条检测记录」** —— 活数据源每次检测的内容都不同，
       去重没有意义（静态数据源 / 手动重跑才有重复，
       那时 `n_contents` 会把差异显示出来）。

    ⚠️ **每层至少抽 1 条** —— 否则小层一个样本都没有，评估里就缺了这一层。
    """
    for name, rate in (("异常层", rate_alert), ("正常层", rate_normal)):
        if not 0.0 < rate <= 1.0:
            raise ValueError(f"{name}采样率必须在 (0, 1] 内")

    layers = _group_layers(candidates)

    sampled: list[Candidate] = []
    layer_reports: list[dict[str, Any]] = []

    for key, items in sorted(layers.items()):
        source_id, metric_id, outcome = key
        rate = rate_alert if outcome == OUTCOME_ALERT else rate_normal

        ordered = sorted(items, key=lambda x: (x.run_id, x.series_id))
        count = max(1, round(len(ordered) * rate))
        # ⚠️ **每层封顶** —— 采样率是相对比例，总体一大就还是标不完。
        #    标注是人工的，每层十几条才现实。
        if max_per_layer is not None:
            count = min(count, max(1, max_per_layer))
        count = min(count, len(ordered))
        # ⚠️ 等间隔取点（含首尾）—— 覆盖整段时间，不只取到某一段。
        picks = np.linspace(0, len(ordered) - 1, count).round().astype(int).tolist()
        chosen = [ordered[index] for index in sorted(set(picks))]
        # ⚠️ 采样率与层大小**跟着每条记录走** —— 采样率后来变了，
        #    已经标过的记录仍按它当初的权重反算。
        actual_rate = len(chosen) / len(ordered)
        for item in chosen:
            item.rate = actual_rate
            item.layer_size = len(ordered)
        sampled.extend(chosen)
        layer_reports.append(
            {
                "source_id": source_id,
                "source_name": chosen[0].source_name,
                "metric_id": metric_id,
                "metric_name": chosen[0].metric_name,
                "outcome": outcome,
                "outcome_label": OUTCOME_LABELS[outcome],
                # ⚠️ 层内**检测记录数** —— 总体的口径。
                "n_candidates": len(items),
                # ⚠️ 层内**不同检测内容数** —— 诊断用：
                #    活数据源每次检测都不同（两者相等）；
                #    静态数据源或手动重跑会出现重复（两者不等）。
                "n_contents": len({item.content_hash for item in items if item.content_hash}),
                "n_sampled": len(chosen),
                "rate": round(actual_rate, 4),
            }
        )

    return sampled, layer_reports


def _read_run_index(data_root: Path, run_id: int) -> dict[str, Any] | None:
    path = run_dir(data_root, run_id) / "index.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iso(ns: int) -> str:
    """纳秒时间戳 → naive ISO 字符串（秒精度）。"""
    return str(np.datetime64(int(ns), "ns").astype("datetime64[s]"))


def list_samples(
    store: PlatformStore,
    data_root: Path,
    *,
    job_id: int | None = None,
    rate_alert: float = DEFAULT_RATE_ALERT,
    rate_normal: float = DEFAULT_RATE_NORMAL,
    max_per_layer: int | None = DEFAULT_MAX_PER_LAYER,
    limit: int = 50,
    todo_only: bool = False,
    source_id: int | None = None,
    metric_id: int | None = None,
    detector: str | None = None,
    metric_class: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[ProductionSample]:
    """**采样后**待标注 / 已标注的生产检测记录。

    ⚠️ **不是全部候选** —— 候选可能有上万条（每次运行 × 每条序列），
       人工标不完。所以先分层抽一批，这批才是标注对象。

    ⚠️ `todo_only=True` → 只给**还没标**的（标注页的待办队列）。

    ⚠️ 筛选在**抽样之前**做 —— 否则「筛出某个指标的记录」会得到
       一份按全平台分层抽样的残片，比例没有意义。
    """
    candidates = [
        item
        for item in list_candidates(store, data_root, job_id=job_id)
        if _candidate_matches(
            item,
            source_id=source_id,
            metric_id=metric_id,
            detector=detector,
            metric_class=metric_class,
            start=start,
            end=end,
        )
    ]
    sampled, _ = stratified_sample(
        candidates,
        rate_alert=rate_alert,
        rate_normal=rate_normal,
        max_per_layer=max_per_layer,
    )

    # ⚠️ **一次读完所有标注** —— 逐条候选开文件在万级候选下会把页面拖垮。
    annotations = load_all_annotations(data_root)
    windows = _window_map(candidates)

    samples: list[ProductionSample] = []
    for item in sampled:
        stamps = _read_timestamps(data_root, item.run_id, item.series_id)
        if stamps is None or len(stamps) == 0:
            continue
        records = annotations.get(item.series_id, [])
        truth = _truth_mask(stamps, records)
        spans = _coverage_spans(records, item.series_id, windows)
        reviewed = bool(_coverage_mask(stamps, spans).any())
        sample = ProductionSample(
            run_id=item.run_id,
            series_id=item.series_id,
            group=item.group,
            job_id=item.job_id,
            detector=item.detector,
            metric_id=item.metric_id,
            metric_name=item.metric_name,
            source_id=item.source_id,
            source_name=item.source_name,
            n=item.n or len(stamps),
            n_alerts=item.n_alerts,
            start_ts=_iso(stamps[0]),
            end_ts=_iso(stamps[-1]),
            n_annotations=_anomaly_intervals(stamps, records),
            n_truth=int(truth.sum()),
            reviewed=reviewed,
            outcome=item.outcome,
            # ⚠️ 采样率要带到前端 —— 标注时一起存下来，反算时按它加权。
            rate=round(item.rate, 4),
            layer_size=item.layer_size,
            metric_class=item.metric_class,
        )
        # ⚠️ 「待标」= 还没核对过 —— 光看有没有异常区间是不够的：
        #    用户可能核对过一条**正常**记录（没有异常区间）。
        if todo_only and sample.reviewed:
            continue
        samples.append(sample)

    samples.sort(key=lambda item: (item.source_name, item.metric_name, item.run_id))
    return samples[:limit]


def _read_timestamps(
    data_root: Path, run_id: int, series_id: str
) -> np.ndarray | None:
    """某次运行里一条序列的时间戳（纳秒）。"""
    index = _read_run_index(data_root, run_id)
    if not index:
        return None
    file_name = next(
        (
            entry.get("file")
            for entry in index.get("series", [])
            if entry.get("series_id") == series_id
        ),
        None,
    )
    if not file_name:
        return None
    npz_path = run_dir(data_root, run_id) / file_name
    if not npz_path.is_file():
        return None
    try:
        with np.load(npz_path) as data:
            return np.asarray(data["timestamps"], dtype=np.int64)
    except (OSError, ValueError, KeyError):
        return None


def evaluate_production(
    store: PlatformStore,
    data_root: Path,
    *,
    job_id: int | None = None,
    rate_alert: float = DEFAULT_RATE_ALERT,
    rate_normal: float = DEFAULT_RATE_NORMAL,
    max_per_layer: int | None = DEFAULT_MAX_PER_LAYER,
) -> dict[str, Any]:
    """生产检测记录 × 人工标注 → **反算**总体效果的 P / R / F1。

    ⚠️ **不是「只算采到的那几条」** —— 那样得到的只是样本的成绩，
       样本里异常多的层会被高估。

    ⚠️ **反算的依据是每条标注记录自带的采样率**：
       一条记录在 20% 采样率下被抽中，它就代表总体里的 5 条；
       采样率后来变成 50%，它仍按 5 倍算（它是从那个样本框里抽出来的）。
       所以总体混淆矩阵是 **Σ 权重 · 单条计数**，
       P / R / F1 再从这个矩阵算 —— 比率不能直接平均。

    ⚠️ **流程是「先采样、再标注、最后评估」**：
       1. 候选 = 全部运行记录 × 全部序列（来自数据库）；
       2. 按「数据源 → 指标 → 检出结果」分层，异常层与正常层**各自**采样率；
       3. 用户在标注页标这批（标注时把当时的采样率一起记下来）；
       4. 用**所有已标注**的记录反算总体成绩。
    """
    candidates = list_candidates(store, data_root, job_id=job_id)
    sampled, layer_stats = stratified_sample(
        candidates,
        rate_alert=rate_alert,
        rate_normal=rate_normal,
        max_per_layer=max_per_layer,
    )

    # ⚠️ 反算用的样本 = **所有已标注的记录**，不限于当前采样选中的 ——
    #    标注是稀缺资源，标过的都要用上。
    sampled_keys = {(item.run_id, item.series_id) for item in sampled}
    annotations = load_all_annotations(data_root)
    windows = _window_map(candidates)
    annotated = _annotated_candidates(candidates, annotations, windows)

    rows: list[dict[str, Any]] = []
    layer_totals: dict[tuple[int, int, str], dict[str, float]] = {}

    for item in annotated:
        records = annotations.get(item.series_id, [])
        # ⚠️ **采样率取自「落进这次窗口的那几段标注」** ——
        #    标注按序列存，同一序列可能在不同采样率下被标过多次。
        overlapping = [
            record
            for record in records
            if (span := _record_span(record, item.series_id, windows)) is not None
            and _spans_overlap(item.start_ts, item.end_ts, [span])
        ]
        rate = _rate_from_annotations(overlapping)
        if rate is None:
            # ⚠️ 没记采样率的老标注 —— 退化成「当前采样里它算第几个」。
            rate = item.rate if (item.run_id, item.series_id) in sampled_keys else 1.0
        item.rate = rate

        counts = _confusion(data_root, item, records, windows)
        if counts is None:
            continue
        weight = item.weight
        key = _layer_key(item)
        bucket = layer_totals.setdefault(
            key,
            {"tp": 0.0, "fp": 0.0, "fn": 0.0, "n": 0.0, "weight": 0.0, "range_f1": 0.0},
        )
        bucket["tp"] += counts["tp"] * weight
        bucket["fp"] += counts["fp"] * weight
        bucket["fn"] += counts["fn"] * weight
        bucket["range_f1"] += counts["range_f1"] * weight
        bucket["n"] += 1
        bucket["weight"] += weight

        rows.append(
            {
                "run_id": item.run_id,
                "series_id": item.series_id,
                "group": item.group,
                "job_id": item.job_id,
                "detector": item.detector,
                "source_id": item.source_id,
                "source_name": item.source_name,
                "metric_id": item.metric_id,
                "metric_name": item.metric_name,
                "outcome": item.outcome,
                "outcome_label": OUTCOME_LABELS[item.outcome],
                "start_ts": counts["start_ts"],
                "end_ts": counts["end_ts"],
                "n": item.n,
                "n_truth": counts["n_truth"],
                "n_pred": counts["n_pred"],
                "n_annotations": counts["n_annotations"],
                # ⚠️ 用户核对过的点数 —— 计分的分母。
                "n_scored_points": counts["n_scored_points"],
                # ⚠️ 这条记录代表总体里的多少条 —— 反算的权重。
                "rate": round(item.rate, 4),
                "weight": round(weight, 4),
                "tp": counts["tp"],
                "fp": counts["fp"],
                "fn": counts["fn"],
                "precision": round(counts["precision"], 4),
                "recall": round(counts["recall"], 4),
                "f1": round(counts["f1"], 4),
                "range_f1": round(counts["range_f1"], 4),
            }
        )

    # ⚠️ **告警事件数 ≠ 检测记录数** —— 同一个异常区间会被连续多次运行
    #    反复报出（尖峰在滑出窗口前一直被报）。两个量都得报出来，
    #    否则「12657 条记录」会被读成「12657 个异常」。
    events = store.distinct_alert_events()
    layer_series: dict[tuple[int, int, str], set[str]] = {}
    for item in candidates:
        layer_series.setdefault(_layer_key(item), set()).add(item.series_id)

    layer_reports: list[dict[str, Any]] = []
    for stats in layer_stats:
        key = (stats["source_id"], stats["metric_id"], stats["outcome"])
        bucket_totals = layer_totals.get(key)
        metric_id = stats["metric_id"]
        outcome = stats["outcome"]
        n_events = sum(
            events.get((metric_id, series_id, outcome), 0)
            for series_id in layer_series.get(key, set())
        )
        layer_reports.append(
            {
                **stats,
                "n_events": n_events,
                "n_annotated": int(bucket_totals["n"]) if bucket_totals else 0,
                **_prf(bucket_totals),
            }
        )

    overall_bucket = {
        "tp": sum(item["tp"] for item in layer_totals.values()),
        "fp": sum(item["fp"] for item in layer_totals.values()),
        "fn": sum(item["fn"] for item in layer_totals.values()),
        "range_f1": sum(item["range_f1"] for item in layer_totals.values()),
        "weight": sum(item["weight"] for item in layer_totals.values()),
    }
    overall = {
        "n_samples": len(rows),
        "n_layers": len([item for item in layer_reports if item["n_annotated"] > 0]),
        **_prf(overall_bucket),
        "n_truth": int(sum(row["n_truth"] for row in rows)),
        "n_alerts": int(sum(row["n_pred"] for row in rows)),
        "n_estimated": round(
            overall_bucket["tp"] + overall_bucket["fp"] + overall_bucket["fn"]
        ),
        # ⚠️ 加权后的计数 —— 反算出来的总体混淆矩阵。
        "tp": round(overall_bucket["tp"], 4),
        "fp": round(overall_bucket["fp"], 4),
        "fn": round(overall_bucket["fn"], 4),
    }

    sampling = {
        "rate_alert": round(float(rate_alert), 4),
        "rate_normal": round(float(rate_normal), 4),
        "max_per_layer": max_per_layer,
        "n_candidates": len(candidates),
        "n_sampled": len(sampled),
        "n_annotated": len(rows),
        # ⚠️ 去重后的告警事件数 —— 同一区间被反复报出只算一个。
        "n_events": sum(item["n_events"] for item in layer_reports),
        "layers": layer_reports,
    }

    return {
        "rows": rows,
        "layers": layer_reports,
        "overall": overall,
        "sampling": sampling,
        "n_candidates": len(candidates),
        "warnings": _warnings(candidates, sampled, rows, layer_reports),
    }


def _prf(bucket: dict[str, float] | None) -> dict[str, float | None]:
    """从加权后的混淆矩阵算 P / R / F1。

    ⚠️ **比率不能平均** —— 必须先加总计数，再算比率。
       「各样本 F1 的平均」会把小样本的极端值放大。

    ⚠️ **分母为 0 的比率给 None 而不是 0** —— 0 会被读成「效果很差」，
       实际是「这一层没有可比的东西」。
    """
    if not bucket:
        return {"precision": None, "recall": None, "f1": None, "range_f1": None}
    tp, fp, fn = bucket["tp"], bucket["fp"], bucket["fn"]
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall):
        f1 = 2 * precision * recall / (precision + recall)
    # ⚠️ 区间级 F1 **不能**像 TP/FP/FN 那样反算（区间不是可加的计数），
    #    这里给的是按权重的加权平均 —— 供参考，不是总体估计。
    weight = bucket.get("weight", 0.0)
    range_f1 = bucket.get("range_f1", 0.0) / weight if weight else 0.0
    return {
        "precision": round(float(precision), 4) if precision is not None else None,
        "recall": round(float(recall), 4) if recall is not None else None,
        "f1": round(float(f1), 4) if f1 is not None else None,
        "range_f1": round(float(range_f1), 4),
    }


def _annotated_candidates(
    candidates: list[Candidate],
    annotations: dict[str, list[dict[str, Any]]],
    windows: WindowMap,
) -> list[Candidate]:
    """所有**已标注**的候选记录 —— 反算的样本。

    ⚠️ **不限于当前采样选中的** —— 标过就该用上。

    ⚠️ **标注按序列存** —— 一条标注覆盖**所有时间轴包含该时段的检测记录**。
       所以判断「这条候选有没有标注」不能只看文件名，
       要看标注区间是否落在它的时间轴上（`_confusion` 里再裁一次）。

    ⚠️ **采样率从标注记录里读**（标注时记下的），
       不是用当前采样率 —— 采样率变过，老标注仍按老权重算。
    """
    result: list[Candidate] = []
    for item in candidates:
        records = annotations.get(item.series_id, [])
        if not records:
            continue
        # ⚠️ **先按时间范围预筛** —— 整条序列的标注有几十段，
        #    但大多数运行的时间轴跟它根本不重叠，没必要读 npz 去裁。
        spans = _coverage_spans(records, item.series_id, windows)
        if not _spans_overlap(item.start_ts, item.end_ts, spans):
            continue
        result.append(item)
    return result


def _spans_overlap(
    start_ts: str, end_ts: str, spans: list[tuple[int, int]]
) -> bool:
    """这次检测的时间范围跟任意一段「核对过」的时间有交集吗。"""
    low = _boundary_ns(start_ts)
    high = _boundary_ns(end_ts)
    if low is None or high is None:
        # ⚠️ 老数据没有时间范围 —— 放行，后面读 npz 再精确裁。
        return True
    return any(high >= span_low and low <= span_high for span_low, span_high in spans)


def _rate_from_annotations(records: list[dict[str, Any]]) -> float | None:
    """从标注记录里读回当时的采样率。"""
    for record in records:
        value = record.get("rate")
        if value is None:
            continue
        try:
            rate = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 < rate <= 1.0:
            return rate
    return None


def _confusion(
    data_root: Path,
    sample: Candidate,
    records: list[dict[str, Any]],
    windows: WindowMap,
) -> dict[str, Any] | None:
    """一条检测记录 × 它的标注 → 混淆矩阵计数。

    ⚠️ **只在用户核对过的时间段里计分** ——
       标注只覆盖窗口的一小段时，其余时段的告警**不能**算误报
       （用户根本没看过）。`_coverage_spans` 定义了「核对过」的范围。

    ⚠️ `records` 是**整条序列**的标注；落在这次运行时间轴之外的部分
       由 `_truth_mask` / `_coverage_mask` 裁掉 —— 一次标注能被多条检测记录复用。
    """
    if not sample.file:
        return None
    npz_path = run_dir(data_root, sample.run_id) / sample.file
    if not npz_path.is_file():
        return None

    try:
        with np.load(npz_path) as data:
            stamps = np.asarray(data["timestamps"], dtype=np.int64)
            severity = np.asarray(data["severity"], dtype=int)
    except (OSError, ValueError, KeyError):
        return None

    spans = _coverage_spans(records, sample.series_id, windows)
    scored = _coverage_mask(stamps, spans)
    if not scored.any():
        # ⚠️ 这段时间用户没核对过 —— 没有真值，也没有分母。
        return None

    truth = _truth_mask(stamps, records) & scored
    # ⚠️ 线上跑出来的告警判定 —— 直接用 severity，不重跑、不重判。
    pred = severity > 0

    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth & scored))
    fn = int(np.sum(~pred & truth))
    precision, recall, f1 = precision_recall_f1(pred & scored, truth)
    _, _, range_f1 = range_based_prf(
        _mask_to_intervals(pred & scored), _mask_to_intervals(truth)
    )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n_truth": int(truth.sum()),
        "n_pred": int(pred.sum()),
        # ⚠️ 只看**落进这次运行时间轴**的异常区间 ——
        #    整条序列的标注可能几十段，跟这次窗口无关的不算。
        "n_annotations": _anomaly_intervals(stamps, records),
        # 这次运行有多少个点被用户核对过 —— 计分的分母。
        "n_scored_points": int(scored.sum()),
        "start_ts": _iso(stamps[0]) if len(stamps) else "",
        "end_ts": _iso(stamps[-1]) if len(stamps) else "",
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "range_f1": float(range_f1),
    }


def _anomaly_intervals(stamps: np.ndarray, records: list[dict[str, Any]]) -> int:
    """有多少段**异常区间**落在这次运行的时间轴里（「核对过」不算）。"""
    if len(stamps) == 0:
        return 0
    low, high = int(stamps[0]), int(stamps[-1])
    count = 0
    for record in records:
        if is_reviewed(record):
            continue
        start = _boundary_ns(record.get("start"))
        end = _boundary_ns(record.get("end"))
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        if end >= low and start <= high:
            count += 1
    return count


def _warnings(
    candidates: list[Candidate],
    sampled: list[Candidate],
    scored: list[dict[str, Any]],
    layer_reports: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    if not candidates:
        return ["没有可评估的生产检测记录 —— 先让任务跑起来"]
    if not sampled:
        return ["采样后没有待评估的记录"]
    # ⚠️ **采样集与「有真值的集合」不是一个集合** ——
    #    标注按序列存，一条标注能覆盖多条检测记录（包括没被抽中的）。
    #    所以「还没标」要按**采样集**算，不能拿两个集合的大小相减。
    covered = {(row["run_id"], row["series_id"]) for row in scored}
    unannotated = len({(item.run_id, item.series_id) for item in sampled} - covered)
    if unannotated:
        warnings.append(
            f"采样出的 {len(sampled)} 条里还有 {unannotated} 条没标 —— "
            "下面的成绩只覆盖被标注过的那部分，不代表整体效果"
        )
    if not scored:
        warnings.append("还没有任何一条采样记录带真值 —— 先在标注页标一段")
    else:
        # ⚠️ **核对覆盖率** —— 只标了一小段时，数字只代表那一小段。
        #    「25 个告警里 2 个真」和「25 个告警里 2 个被核对过」是两回事。
        scored_points = sum(int(row["n_scored_points"]) for row in scored)
        total_points = sum(int(row["n"]) for row in scored)
        ratio = scored_points / total_points if total_points else 0.0
        if total_points and ratio < 0.5:
            # ⚠️ 0.4% 会被 `:.0%` 格式化成「0%」—— 小比例要留小数位。
            percent = f"{ratio:.1%}" if ratio < 0.1 else f"{ratio:.0%}"
            warnings.append(
                f"这些记录里只有 {scored_points}/{total_points} 个点被核对过"
                f"（{percent}）—— "
                "数字只代表核对过的那部分；想让结论覆盖整窗，"
                "在标注页点「这条记录正常」或标完再保存"
            )
    # ⚠️ **没标正常层 = Recall 不可信** —— 漏报只能从正常记录里发现。
    normal_annotated = [
        item for item in layer_reports if item["outcome"] == OUTCOME_NORMAL
    ]
    if normal_annotated and not any(item["n_annotated"] > 0 for item in normal_annotated):
        warnings.append(
            "正常层（没报出告警的记录）一条都没标 —— "
            "Recall 估不出来：漏报只有在正常记录里才看得见"
        )
    return warnings
