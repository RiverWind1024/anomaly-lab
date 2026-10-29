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

_UNIMPLEMENTED = {
    "detect": "Chunk 2",
    "evaluate": "Chunk 2",
    "compare": "Chunk 3",
    "report": "Chunk 2",
    "serve": "Chunk 4",
}


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

    p = sub.add_parser("report", help="汇总检测结果")
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
