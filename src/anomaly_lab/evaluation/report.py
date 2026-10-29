"""回归报告：JSON + Markdown + 按形态分组的 P/R/F1 图。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from anomaly_lab.evaluation.backtest import BacktestRow

_METRICS = ("precision", "recall", "f1", "range_f1")


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _aggregate(rows: list[BacktestRow]) -> dict:
    return {
        "n_series": len(rows),
        "n_truth": int(sum(r.n_truth for r in rows)),
        "n_pred": int(sum(r.n_pred for r in rows)),
        **{metric: _mean([getattr(r, metric) for r in rows]) for metric in _METRICS},
        "elapsed_ms": _mean([r.elapsed_ms for r in rows]),
    }


def _group(rows: list[BacktestRow], key: str) -> dict:
    buckets: dict[str, list[BacktestRow]] = defaultdict(list)
    for row in rows:
        buckets[str(getattr(row, key))].append(row)
    return {name: _aggregate(items) for name, items in sorted(buckets.items())}


def _table(grouped: dict[str, dict], title: str) -> str:
    lines = [
        f"## {title}",
        "",
        "| 组 | 序列数 | Precision | Recall | F1 | Range-F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, stats in grouped.items():
        lines.append(
            f"| {name} | {stats['n_series']} | {stats['precision']:.3f} | "
            f"{stats['recall']:.3f} | {stats['f1']:.3f} | {stats['range_f1']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name) or "detector"


def _plot_detector(name: str, rows: list[BacktestRow], out_dir: Path) -> Path:
    by_class = _group(rows, "metric_class")
    classes = list(by_class)
    x = range(len(classes))
    width = 0.25
    fig, ax = plt.subplots(figsize=(max(6, 2 * len(classes)), 4))
    for offset, metric in zip((-width, 0.0, width), ("precision", "recall", "f1"), strict=True):
        ax.bar(
            [i + offset for i in x],
            [by_class[c][metric] for c in classes],
            width=width,
            label=metric,
        )
    ax.set_xticks(list(x))
    ax.set_xticklabels(classes, rotation=20, ha="right")
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("score")
    ax.set_title(f"Detector: {name}")
    ax.legend()
    fig.tight_layout()
    path = out_dir / f"{_safe_name(name)}.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def build_report(
    rows: list[BacktestRow], out_dir: Path, title: str = ""
) -> dict:
    out_dir = Path(out_dir)
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    overall = _aggregate(rows)
    by_detector = _group(rows, "detector")
    by_metric_class = _group(rows, "metric_class")
    summary = {
        "by_detector": by_detector,
        "by_metric_class": by_metric_class,
        "overall": overall,
    }

    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "generated_at": generated_at,
        "title": title,
        "summary": summary,
        "rows": [asdict(row) for row in rows],
    }
    (out_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    for detector in sorted({r.detector for r in rows}):
        detector_rows = [r for r in rows if r.detector == detector]
        _plot_detector(detector, detector_rows, figures_dir)

    worst = sorted(rows, key=lambda r: (r.f1, r.range_f1))[:10]
    badcases = [r for r in rows if r.f1 < 0.5]

    md: list[str] = [f"# {title or 'Anomaly Lab 回归报告'}", ""]
    md.append(f"生成时间：{generated_at}")
    md.append("")
    md.append(
        f"总体：Precision={overall['precision']:.3f}，Recall={overall['recall']:.3f}，"
        f"F1={overall['f1']:.3f}，Range-F1={overall['range_f1']:.3f}，"
        f"共 {overall['n_series']} 条序列。"
    )
    md.append("")
    md.append(_table(by_detector, "按检测器"))
    md.append(_table(by_metric_class, "按形态"))
    md.append("## 最差 10 条序列")
    md.append("")
    md.append("| 序列 | 形态 | 检测器 | F1 | Range-F1 | 真值点 | 预测点 |")
    md.append("|---|---|---|---:|---:|---:|---:|")
    for r in worst:
        md.append(
            f"| {r.series_id} | {r.metric_class} | {r.detector} | {r.f1:.3f} | "
            f"{r.range_f1:.3f} | {r.n_truth} | {r.n_pred} |"
        )
    md.append("")
    md.append("## Bad Case 摘要")
    md.append("")
    if badcases:
        for r in badcases[:10]:
            md.append(
                f"- `{r.series_id}`（{r.metric_class}/{r.detector}）：F1={r.f1:.3f}，"
                f"真值 {r.n_truth} 点，预测 {r.n_pred} 点"
            )
    else:
        md.append("无 F1 < 0.5 的序列。")
    md.append("")
    md.append("图见 `figures/`（每个检测器一张，按形态分组）。")
    (out_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def diff_reports(path_a: Path, path_b: Path) -> str:
    old = json.loads(Path(path_a).read_text(encoding="utf-8"))
    new = json.loads(Path(path_b).read_text(encoding="utf-8"))
    lines = ["# 报告差异", "", "| 分组 | 指标 | 旧值 | 新值 | 变化 |", "|---|---|---:|---:|---:|"]

    old_overall = old["summary"]["overall"]
    new_overall = new["summary"]["overall"]
    for metric in _METRICS:
        before = float(old_overall.get(metric, 0.0))
        after = float(new_overall.get(metric, 0.0))
        lines.append(
            f"| overall | {metric.upper()} | {before:.3f} | {after:.3f} | "
            f"{after - before:+.3f} |"
        )

    detectors = sorted(
        set(old["summary"]["by_detector"]) | set(new["summary"]["by_detector"])
    )
    for detector in detectors:
        before_stats = old["summary"]["by_detector"].get(detector, {})
        after_stats = new["summary"]["by_detector"].get(detector, {})
        for metric in _METRICS:
            before = float(before_stats.get(metric, 0.0))
            after = float(after_stats.get(metric, 0.0))
            lines.append(
                f"| {detector} | {metric.upper()} | {before:.3f} | {after:.3f} | "
                f"{after - before:+.3f} |"
            )
    return "\n".join(lines) + "\n"
