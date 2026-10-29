"""命令行入口：argparse，返回退出码便于测试。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from anomaly_lab.classification.classifier import classify
from anomaly_lab.compliance import scan_repo
from anomaly_lab.config import CONFIG
from anomaly_lab.data.loader import build_synthetic_dataset, load_dataset
from anomaly_lab.data.synthetic import METRIC_CLASSES
from anomaly_lab.detectors.statistical import (
    ChangePointDetector,
    DeseasonalizedIQRDetector,
    EventCountDetector,
    IQRDetector,
    MADDetector,
    SeasonalDetector,
    STLResidualDetector,
    ZScoreDetector,
)
from anomaly_lab.evaluation.backtest import BacktestRow, _mask_to_intervals
from anomaly_lab.evaluation.compare import CompareRow, compare_detectors
from anomaly_lab.evaluation.metrics import precision_recall_f1, range_based_prf
from anomaly_lab.evaluation.report import build_report
from anomaly_lab.evaluation.thresholds import search_threshold

_UNIMPLEMENTED = {
    "serve": "Chunk 4",
}

_DETECTORS = {
    "iqr": IQRDetector,
    "mad": MADDetector,
    "zscore": ZScoreDetector,
    "seasonal": lambda: SeasonalDetector(period=24),
    "stl_residual": lambda: STLResidualDetector(period=24),
    "deseasonalized_iqr": DeseasonalizedIQRDetector,
    "changepoint": ChangePointDetector,
    "event_count": EventCountDetector,
}


def _detections_root(data_dir: Path) -> Path:
    # 默认 data/synthetic -> data/cache/detections；自定义目录用其父目录
    return Path(data_dir).parent / "cache" / "detections"


def _load_rows(data_dir: Path) -> list[BacktestRow]:
    series_list = load_dataset(data_dir)
    by_id = {s.series_id: s for s in series_list}
    root = _detections_root(data_dir)
    rows: list[BacktestRow] = []
    for detector_dir in sorted(p for p in root.glob("*") if p.is_dir()):
        for path in sorted(detector_dir.glob("*.npz")):
            series = by_id.get(path.stem)
            if series is None:
                continue
            data = np.load(path, allow_pickle=False)
            truth = series.labels.astype(bool)
            scores = data["scores"].astype(float)
            searched = search_threshold(scores, str(data["score_type"]), truth)
            pred = scores > searched.threshold
            precision, recall, f1 = precision_recall_f1(pred, truth)
            _, _, range_f1 = range_based_prf(
                _mask_to_intervals(pred), _mask_to_intervals(truth)
            )
            rows.append(
                BacktestRow(
                    series_id=series.series_id,
                    metric_class=str(series.meta.get("metric_class", "unknown")),
                    detector=str(data["detector"]),
                    score_type=str(data["score_type"]),
                    threshold=searched.threshold,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                    range_f1=range_f1,
                    n_truth=int(truth.sum()),
                    n_pred=int(pred.sum()),
                    elapsed_ms=float(data["elapsed_ms"]),
                )
            )
    return rows


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anomaly-lab")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="生成合成数据集")
    p.add_argument("--n", type=int, default=120, help="总序列数")
    p.add_argument("--seed", type=int, default=CONFIG.seed)
    p.add_argument("--out", type=Path, default=None)

    p = sub.add_parser("classify", help="形态分类")
    p.add_argument("--eval", action="store_true", help="打印混淆矩阵与准确率")
    p.add_argument("--data", type=Path, default=None)

    p = sub.add_parser("detect", help="跑检测器")
    p.add_argument("--detector", default="iqr")
    p.add_argument("--data", type=Path, default=None)

    p = sub.add_parser("evaluate", help="回测并生成报告")
    p.add_argument("--data", type=Path, default=None)
    p.add_argument("--report", type=Path, default=None)

    p = sub.add_parser("compare", help="多检测器对照")
    p.add_argument("--data", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--detectors", default=None, help="逗号分隔，默认全部可用检测器")
    p.add_argument("--epochs", type=int, default=3)

    p = sub.add_parser("report", help="汇总检测结果")
    p.add_argument("--data", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)

    p = sub.add_parser("serve", help="启动 Web")
    p.add_argument("--port", type=int, default=8000)

    sub.add_parser("compliance-check", help="合规自检")

    return parser


def _print_confusion(matrix: np.ndarray, labels: list[str]) -> None:
    width = max(len(name) for name in labels) + 2
    print("混淆矩阵（行=真实，列=预测）")
    print(" " * width + "".join(f"{name:>{width}}" for name in labels))
    for name, row in zip(labels, matrix):
        print(f"{name:>{width}}" + "".join(f"{int(v):>{width}}" for v in row))


def _cmd_generate(args: argparse.Namespace) -> int:
    out_dir = args.out or CONFIG.synthetic_dir
    series = build_synthetic_dataset(seed=args.seed, out_dir=out_dir, n_total=args.n)
    print(f"已生成 {len(series)} 条序列 -> {Path(out_dir)}")
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    data_dir = args.data or CONFIG.synthetic_dir
    series = load_dataset(data_dir)
    if not series:
        print(f"没有可加载的数据：{data_dir}", file=sys.stderr)
        return 1

    if not args.eval:
        for s in series:
            result = classify(s)
            print(
                f"{s.series_id}: {result.metric_class} "
                f"(confidence={result.confidence:.2f})"
            )
            for reason in result.reasons:
                print(f"  - {reason}")
        return 0

    labels = list(METRIC_CLASSES)
    index = {name: i for i, name in enumerate(labels)}
    matrix = np.zeros((len(labels), len(labels)), dtype=int)
    correct = 0
    for s in series:
        truth = s.meta.get("metric_class")
        predicted = classify(s).metric_class
        if truth in index and predicted in index:
            matrix[index[truth], index[predicted]] += 1
        correct += int(truth == predicted)
    _print_confusion(matrix, labels)
    accuracy = correct / len(series)
    print(f"分类准确率: {accuracy:.2%} ({correct}/{len(series)})")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    data_dir = args.data or CONFIG.synthetic_dir
    if args.detector not in _DETECTORS:
        print(f"未知检测器: {args.detector}", file=sys.stderr)
        return 1
    series_list = load_dataset(data_dir)
    if not series_list:
        print(f"没有可加载的数据：{data_dir}", file=sys.stderr)
        return 1
    out_dir = _detections_root(data_dir) / args.detector
    out_dir.mkdir(parents=True, exist_ok=True)
    for series in series_list:
        detector = _DETECTORS[args.detector]().fit(series)
        result = detector.detect(series)
        np.savez(
            out_dir / f"{series.series_id}.npz",
            scores=result.scores,
            is_anomaly=result.is_anomaly,
            threshold=np.array(result.threshold),
            score_type=np.array(result.score_type),
            detector=np.array(result.detector),
            elapsed_ms=np.array(result.elapsed_ms),
        )
    print(f"检测完成：{len(series_list)} 条序列 -> {out_dir}")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    data_dir = args.data or CONFIG.synthetic_dir
    rows = _load_rows(data_dir)
    if not rows:
        print(f"没有检测结果，请先运行 detect：{_detections_root(data_dir)}", file=sys.stderr)
        return 1
    out_dir = args.report or (CONFIG.reports_dir / "latest")
    summary = build_report(rows, out_dir, title="Anomaly Lab 回测")
    overall = summary["overall"]
    print(
        f"F1={overall['f1']:.3f} Precision={overall['precision']:.3f} "
        f"Recall={overall['recall']:.3f} RangeF1={overall['range_f1']:.3f} "
        f"({overall['n_series']} 条序列)"
    )
    print(f"报告已写入：{Path(out_dir)}")
    return 0


def _ensure_deep_models(series_list, epochs: int) -> dict[str, object]:
    import importlib.util

    if importlib.util.find_spec("torch") is None:
        return {}
    from anomaly_lab.detectors.deep import LSTMDetector, TCNDetector, train_lstm, train_tcn

    model_dir = CONFIG.data_dir / "cache" / "models"
    tcn_path = model_dir / "tcn.pt"
    lstm_path = model_dir / "lstm.pt"
    if not tcn_path.exists():
        train_tcn(series_list[:24], epochs=epochs, seed=CONFIG.seed, out_path=tcn_path)
    if not lstm_path.exists():
        train_lstm(series_list[:24], epochs=epochs, seed=CONFIG.seed, out_path=lstm_path)
    return {
        "TCN": lambda: TCNDetector(model_path=tcn_path),
        "LSTM": lambda: LSTMDetector(model_path=lstm_path),
    }


def _compare_markdown(rows: list[CompareRow]) -> str:
    lines = [
        "# 检测器对照",
        "",
        "| 检测器 | 形态 | score_type | Precision | Recall | F1 | Range-F1 | 延迟(ms) | 参数量 | 跳过原因 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.detector} | {row.metric_class} | {row.score_type or '-'} | "
            f"{row.precision:.3f} | {row.recall:.3f} | {row.f1:.3f} | "
            f"{row.range_f1:.3f} | {row.mean_elapsed_ms:.2f} | "
            f"{'-' if row.params is None else row.params} | {row.skipped_reason or '-'} |"
        )
    return "\n".join(lines) + "\n"


def _cmd_compare(args: argparse.Namespace) -> int:
    data_dir = args.data or CONFIG.synthetic_dir
    series_list = load_dataset(data_dir)
    if not series_list:
        print(f"没有可加载的数据：{data_dir}", file=sys.stderr)
        return 1

    specs = [
        ("IQR", "anomaly_lab.detectors.statistical", "IQRDetector"),
        ("MAD", "anomaly_lab.detectors.statistical", "MADDetector"),
        ("ZScore", "anomaly_lab.detectors.statistical", "ZScoreDetector"),
        ("Seasonal", "anomaly_lab.detectors.statistical", "SeasonalDetector"),
        ("STLResidual", "anomaly_lab.detectors.statistical", "STLResidualDetector"),
        (
            "DeseasonalizedIQR",
            "anomaly_lab.detectors.statistical",
            "DeseasonalizedIQRDetector",
        ),
        ("ChangePoint", "anomaly_lab.detectors.statistical", "ChangePointDetector"),
        ("EventCount", "anomaly_lab.detectors.statistical", "EventCountDetector"),
        ("TCN", "anomaly_lab.detectors.deep", "TCNDetector"),
        ("LSTM", "anomaly_lab.detectors.deep", "LSTMDetector"),
        ("Chronos", "anomaly_lab.detectors.chronos", "ChronosDetector"),
    ]
    if args.detectors:
        wanted = {name.strip().lower() for name in args.detectors.split(",") if name.strip()}
        specs = [spec for spec in specs if spec[0].lower() in wanted]
        if not specs:
            print("没有匹配的检测器", file=sys.stderr)
            return 1

    factories: dict[str, object] = {}
    if any(spec[0] in {"TCN", "LSTM"} for spec in specs):
        try:
            factories.update(_ensure_deep_models(series_list, args.epochs))
        except Exception as exc:
            print(f"深度模型训练失败，将记录为跳过：{exc}", file=sys.stderr)

    # 带构造参数的检测器用工厂覆盖默认无参构造
    factories.setdefault("Seasonal", lambda: SeasonalDetector(period=24))
    factories.setdefault("STLResidual", lambda: STLResidualDetector(period=24))

    rows = compare_detectors(series_list, specs, factories=factories)
    out = Path(args.out or (CONFIG.reports_dir / "compare.md"))
    if out.suffix != ".md":
        out = out / "compare.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_compare_markdown(rows), encoding="utf-8")
    print(f"对照表已写入：{out}（{len(rows)} 行）")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    data_dir = args.data or CONFIG.synthetic_dir
    rows = _load_rows(data_dir)
    if not rows:
        print(f"没有检测结果，请先运行 detect：{_detections_root(data_dir)}", file=sys.stderr)
        return 1
    out = args.out or (CONFIG.reports_dir / "summary.md")
    out = Path(out)
    if out.suffix != ".md":
        out = out / "summary.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    by_detector: dict[str, list[BacktestRow]] = {}
    for row in rows:
        by_detector.setdefault(row.detector, []).append(row)
    lines = [
        "# 检测结果汇总",
        "",
        "| 检测器 | 序列数 | Precision | Recall | F1 | Range-F1 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, items in sorted(by_detector.items()):
        count = len(items)
        means = {
            key: sum(getattr(r, key) for r in items) / count
            for key in ("precision", "recall", "f1", "range_f1")
        }
        lines.append(
            f"| {name} | {count} | {means['precision']:.3f} | {means['recall']:.3f} | "
            f"{means['f1']:.3f} | {means['range_f1']:.3f} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"汇总已写入：{out}")
    return 0


def _cmd_compliance(args: argparse.Namespace) -> int:
    hits = scan_repo(Path.cwd())
    if hits:
        for path, term, line_no in hits:
            print(f"{path}:{line_no}: 命中禁词 {term!r}")
        return 1
    print("合规自检通过：未发现内部系统专名")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "generate":
        return _cmd_generate(args)
    if args.command == "classify":
        return _cmd_classify(args)
    if args.command == "detect":
        return _cmd_detect(args)
    if args.command == "evaluate":
        return _cmd_evaluate(args)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "compliance-check":
        return _cmd_compliance(args)
    if args.command in _UNIMPLEMENTED:
        print(
            f"{args.command} 未实现，见 PLAN {_UNIMPLEMENTED[args.command]}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
