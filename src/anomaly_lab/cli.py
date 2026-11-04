"""命令行入口：argparse，返回退出码便于测试。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from anomaly_lab.classification.classifier import classify
from anomaly_lab.compliance import scan_repo
from anomaly_lab.config import CONFIG
from anomaly_lab.data.loader import build_synthetic_dataset, load_dataset
from anomaly_lab.data.synthetic import METRIC_CLASSES
from anomaly_lab.detectors.statistical import (
    ChangePointDetector,
    EventCountDetector,
    IQRDetector,
    MADDetector,
    SeasonalDetector,
    STLResidualDetector,
    TrendResidualIQRDetector,
    ZScoreDetector,
)
from anomaly_lab.detectors.trend import TheilSenTrendDetector
from anomaly_lab.evaluation.backtest import BacktestRow, _mask_to_intervals, series_span
from anomaly_lab.evaluation.compare import CompareRow, compare_detectors
from anomaly_lab.evaluation.metrics import precision_recall_f1, range_based_prf
from anomaly_lab.evaluation.report import build_report
from anomaly_lab.evaluation.thresholds import search_threshold

_UNIMPLEMENTED: dict[str, str] = {}

_DETECTORS = {
    "iqr": IQRDetector,
    "mad": MADDetector,
    "zscore": ZScoreDetector,
    "seasonal": SeasonalDetector,
    # period 传 None = 按序列自动估计周期
    "stl_residual": STLResidualDetector,
    "trend_residual_iqr": TrendResidualIQRDetector,
    "theil_sen": TheilSenTrendDetector,
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
            start_ts, end_ts = series_span(series)
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
                    start_ts=start_ts,
                    end_ts=end_ts,
                    source=str(series.meta.get("source", "synthetic")),
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

    p = sub.add_parser(
        "validate-auto", help="在带真值的公开数据上验证「自动推荐算法」的质量"
    )
    p.add_argument(
        "--source",
        default="nab",
        choices=["nab", "synthetic"],
        help="验证数据源：nab=公开真实数据，synthetic=项目自带合成数据",
    )
    p.add_argument("--data", type=Path, default=None, help="synthetic 模式下的数据目录")
    p.add_argument("--limit", type=int, default=None, help="最多验证多少条序列")
    p.add_argument("--baseline", default="iqr", help="作为对照的固定算法")
    p.add_argument("--out", type=Path, default=None, help="报告输出路径（.md）")
    p.add_argument(
        "--offline", action="store_true", help="不联网（要求数据已在缓存里）"
    )

    p = sub.add_parser("serve", help="启动 Web")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--no-scheduler",
        action="store_true",
        help="不启动内置定时调度（只跑 Web）",
    )

    p = sub.add_parser("platform-demo", help="生成平台 demo（SQLite 源 + 指标 + 任务）")
    p.add_argument("--data", type=Path, default=None, help="数据根目录，默认 data")

    p = sub.add_parser(
        "mock-tsdb", help="启动假远端时序数据库（InfluxDB 3 形状，持续造数）"
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8181)
    p.add_argument(
        "--db-path", type=Path, default=Path("data/mock_tsdb/tsdb.db"), help="SQLite 文件路径"
    )
    p.add_argument("--retention-hours", type=int, default=6, help="保留窗口（小时）")
    p.add_argument("--history-points", type=int, default=360, help="启动时回填多少个历史点")
    p.add_argument("--write-interval", type=int, default=10, help="后台写入间隔（秒）")
    p.add_argument("--no-writer", action="store_true", help="不启动后台写入线程")

    p = sub.add_parser("mock-demo", help="把平台侧配成指向假远端（源 + 指标 + 任务）")
    p.add_argument("--data", type=Path, default=None, help="数据根目录，默认 data")
    p.add_argument(
        "--base-url", default="http://127.0.0.1:8181", help="假远端地址"
    )
    p.add_argument("--db", default="mock", help="请求里的 db 字段")

    p = sub.add_parser("prune", help="清理超出保留期的运行记录与检测结果文件")
    p.add_argument("--data", type=Path, default=None, help="数据根目录，默认 data")
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="保留多少天 —— 默认读环境变量，再默认 180",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="只报告要删什么，不真删"
    )

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
        # 基线三件套：检测器不支持基线时存**空数组**（不是 None）——
        # 前端按长度判断有没有带，空数组 ≠ null，不会误判成「有带」。
        expected = (
            np.asarray([], dtype=float)
            if result.expected is None
            else np.asarray(result.expected, dtype=float)
        )
        lower = (
            np.asarray([], dtype=float)
            if result.lower is None
            else np.asarray(result.lower, dtype=float)
        )
        upper = (
            np.asarray([], dtype=float)
            if result.upper is None
            else np.asarray(result.upper, dtype=float)
        )
        np.savez(
            out_dir / f"{series.series_id}.npz",
            scores=result.scores,
            is_anomaly=result.is_anomaly,
            threshold=np.array(result.threshold),
            score_type=np.array(result.score_type),
            detector=np.array(result.detector),
            elapsed_ms=np.array(result.elapsed_ms),
            expected=expected,
            lower=lower,
            upper=upper,
            # 带的语义（alert_boundary / prediction_interval）；没有带就是空串
            band_kind=np.array(result.band_kind or ""),
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
            "TrendResidualIQR",
            "anomaly_lab.detectors.statistical",
            "TrendResidualIQRDetector",
        ),
        ("TheilSen", "anomaly_lab.detectors.trend", "TheilSenTrendDetector"),
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
    factories.setdefault("Seasonal", SeasonalDetector)
    factories.setdefault("STLResidual", lambda: STLResidualDetector(period=24))

    rows = compare_detectors(series_list, specs, factories=factories)
    out = Path(args.out or (CONFIG.reports_dir / "compare.md"))
    if out.suffix != ".md":
        out = out / "compare.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_compare_markdown(rows), encoding="utf-8")
    print(f"对照表已写入：{out}（{len(rows)} 行）")
    return 0


def _cmd_validate_auto(args: argparse.Namespace) -> int:
    """在带真值的序列上验证 auto 推荐的质量。"""
    from anomaly_lab.evaluation.auto_validation import validate_auto

    source_label = "NAB（公开真实数据）"
    if args.source == "nab":
        from anomaly_lab.data.nab import NabUnavailable, load_nab_series

        try:
            series_list = load_nab_series(
                limit=args.limit, auto_download=not args.offline
            )
        except NabUnavailable as exc:
            print(f"NAB 数据不可用：{exc}", file=sys.stderr)
            print(
                "提示：可用 ANOMALY_LAB_NAB_URL 指定下载源，或先手动放入 "
                "data/cache/nab/",
                file=sys.stderr,
            )
            return 1
    else:
        source_label = "合成数据"
        data_dir = args.data or CONFIG.synthetic_dir
        series_list = load_dataset(data_dir)
        if args.limit:
            series_list = series_list[: args.limit]
        if not series_list:
            print(f"没有可加载的数据：{data_dir}", file=sys.stderr)
            return 1

    try:
        report = validate_auto(series_list, baseline_detector=args.baseline)
    except ValueError as exc:
        print(f"无法验证：{exc}", file=sys.stderr)
        return 1

    print(f"自动推荐算法验证（数据源：{source_label}，{len(report.rows)} 条序列）")
    print()
    print("各算法平均 F1（各自固定默认阈值）：")
    print(f"  {'算法':<22}{'点级':>8}{'窗口级':>10}")
    for name in sorted(
        report.detector_mean_f1, key=lambda n: -report.detector_mean_adjusted_f1[n]
    ):
        mark = " ← auto 平均选中" if name == report.best_fixed_detector else ""
        print(
            f"  {name:<22}{report.detector_mean_f1[name]:>8.3f}"
            f"{report.detector_mean_adjusted_f1[name]:>10.3f}{mark}"
        )
    print()
    print(
        f"auto 选中算法：平均 F1 {report.auto_mean_f1:.3f} / "
        f"窗口级 {report.auto_mean_adjusted_f1:.3f} / "
        f"平均排名 {report.auto_mean_rank:.2f} / 夺冠率 {report.auto_top1_rate:.1%} / "
        f"回退率 {report.fallback_rate:.1%}"
    )
    gap = report.auto_mean_f1 - report.best_fixed_mean_f1
    print(
        f"对比最好的固定算法（{report.best_fixed_detector} {report.best_fixed_mean_f1:.3f}）："
        f"{gap:+.3f}"
    )
    print(
        f"对比基线固定算法（{report.baseline_detector} {report.baseline_mean_f1:.3f}）："
        f"{report.auto_mean_f1 - report.baseline_mean_f1:+.3f}"
    )

    out = Path(args.out or (CONFIG.reports_dir / "auto_validation.md"))
    if out.suffix != ".md":
        out = out / "auto_validation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_auto_validation_markdown(report, source_label), encoding="utf-8")
    print(f"报告已写入：{out}")
    return 0


def _auto_validation_markdown(report, source_label: str) -> str:
    lines = [
        "# 自动推荐算法验证",
        "",
        f"- 数据源：{source_label}",
        f"- 序列数：{len(report.rows)}",
        (
            "- 判定口径：各检测器在**各自固定默认阈值**下评估"
            "（不是逐序列搜阈值的诊断上限）"
        ),
        (
            "- 两种 F1：**点级** = 逐点对；**窗口级** = point-adjusted"
            "（真值窗口内命中一次即算检出）。稀疏点级标注的公开集适用后者。"
        ),
        "",
        "## 各算法平均 F1",
        "",
        "| 算法 | 点级 F1 | 窗口级 F1 |",
        "|---|---:|---:|",
    ]
    for name in sorted(
        report.detector_mean_f1, key=lambda n: -report.detector_mean_adjusted_f1[n]
    ):
        lines.append(
            f"| {name} | {report.detector_mean_f1[name]:.3f} | "
            f"{report.detector_mean_adjusted_f1[name]:.3f} |"
        )
    lines += [
        "",
        "## auto 的表现",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| 平均 F1（点级） | {report.auto_mean_f1:.3f} |",
        f"| 平均 F1（窗口级） | {report.auto_mean_adjusted_f1:.3f} |",
        f"| 平均排名（1 最好） | {report.auto_mean_rank:.2f} |",
        f"| 夺冠率 | {report.auto_top1_rate:.1%} |",
        f"| 回退率 | {report.fallback_rate:.1%} |",
        (
            f"| 相对最好的固定算法（{report.best_fixed_detector}） | "
            f"{report.auto_mean_f1 - report.best_fixed_mean_f1:+.3f} |"
        ),
        (
            f"| 相对基线（{report.baseline_detector}） | "
            f"{report.auto_mean_f1 - report.baseline_mean_f1:+.3f} |"
        ),
        "",
        "## 逐序列明细",
        "",
        "| 序列 | 形态 | auto 选中 | 回退 | 点级 F1 | 窗口级 F1 | 排名 | 最好算法 |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for row in report.rows:
        best = max(row.adjusted_f1, key=lambda name: row.adjusted_f1[name]) if row.f1 else "-"
        lines.append(
            f"| {row.series_id} | {row.metric_class} | {row.auto_detector} | "
            f"{'是' if row.fallback else ''} | "
            f"{row.f1.get(row.auto_detector, 0.0):.3f} | "
            f"{row.adjusted_f1.get(row.auto_detector, 0.0):.3f} | "
            f"{row.ranks.get(row.auto_detector, 0)} | {best} |"
        )
    return "\n".join(lines) + "\n"


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


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from anomaly_lab.web.app import create_app

    uvicorn.run(
        create_app(start_scheduler=not args.no_scheduler),
        host=args.host,
        port=args.port,
    )
    return 0


def _cmd_platform_demo(args: argparse.Namespace) -> int:
    from anomaly_lab.platform.demo import seed_demo

    data_root = Path(args.data) if args.data else CONFIG.data_dir
    info = seed_demo(data_root)
    print(
        "platform demo 已就绪："
        f"source={info['source_id']} metric={info['metric_id']} job={info['job_id']} "
        f"({info['n_points']} 个点, {info['source_path']})"
    )
    print("执行：make serve  # 打开 http://127.0.0.1:8000/jobs")
    return 0


def _cmd_mock_tsdb(args: argparse.Namespace) -> int:
    from anomaly_lab.mock_tsdb.__main__ import main as mock_main

    return mock_main(
        [
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--db-path",
            str(args.db_path),
            "--retention-hours",
            str(args.retention_hours),
            "--history-points",
            str(args.history_points),
            "--write-interval",
            str(args.write_interval),
        ]
        + (["--no-writer"] if args.no_writer else [])
    )


def _cmd_mock_demo(args: argparse.Namespace) -> int:
    from anomaly_lab.platform.mock_remote import seed_mock_remote

    data_root = Path(args.data) if args.data else CONFIG.data_dir
    info = seed_mock_remote(data_root, base_url=args.base_url, db=args.db)
    print(
        "假远端演示已就绪："
        f"source={info['source_id']} metric={info['metric_id']} job={info['job_id']} "
        f"({info['base_url']})"
    )
    print("执行：make mock-tsdb &   # 起假远端")
    print("      make serve         # 打开 http://127.0.0.1:8000/sources")
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    """手动清理超出保留窗口的数据。

    ⚠️ 调度器也会自动清（每小时一次）—— 这个命令是给
       「想现在就清」和「想先看看会删什么」（`--dry-run`）用的。
    """
    from anomaly_lab.platform.retention import RetentionPolicy, prune
    from anomaly_lab.platform.store import PlatformStore

    data_root = Path(args.data) if args.data else CONFIG.data_dir
    policy = RetentionPolicy.from_env()
    if args.days is not None:
        policy = replace(policy, retention_days=max(0, args.days))
    store = PlatformStore(data_root / "platform.db")
    result = prune(store, data_root, policy, dry_run=args.dry_run)
    prefix = "将要清理" if args.dry_run else "清理完成"
    print(
        f"{prefix}：删了 {result.deleted_runs} 次运行、"
        f"{result.orphan_dirs} 个孤儿目录，"
        f"释放 {result.freed_bytes / 1024 / 1024:.1f} MB；"
        f"保留 {result.kept_runs} 次运行（保留期 {policy.retention_days} 天）"
    )
    if result.disk_capped_jobs:
        print(
            f"  ⚠️ 任务 {result.disk_capped_jobs} 触发了磁盘上限兜底，"
            "实际保留期比配置短"
        )
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
    if args.command == "validate-auto":
        return _cmd_validate_auto(args)
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "platform-demo":
        return _cmd_platform_demo(args)
    if args.command == "mock-tsdb":
        return _cmd_mock_tsdb(args)
    if args.command == "mock-demo":
        return _cmd_mock_demo(args)
    if args.command == "prune":
        return _cmd_prune(args)
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
