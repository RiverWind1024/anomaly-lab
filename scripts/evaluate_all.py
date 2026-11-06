#!/usr/bin/env python
"""把所有可用检测器跑一遍回测，写 `reports/latest`。

为什么单独一个脚本：`make detect` 只覆盖 CLI 里注册的统计型检测器，
深度模型要先训练、Chronos 要有本地权重 —— 它们塞不进同一个 `--detector`。
README 的评测表就是这张表，所以需要有一个能一次复现它的入口。

口径与 `anomaly_lab.cli evaluate` 一致：逐条序列搜索阈值，再按序列平均。

用法：
    python scripts/evaluate_all.py                  # 写到 reports/latest
    python scripts/evaluate_all.py --out /tmp/x     # 写到别处
    python scripts/evaluate_all.py --detectors iqr,mad
    python scripts/evaluate_all.py --epochs 3       # 深度模型训练轮数
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from anomaly_lab.config import CONFIG
from anomaly_lab.data.loader import load_dataset
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
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.evaluation.report import build_report


def _deep_factories(series_list, epochs: int) -> dict[str, object]:
    """训练（缺失时）并返回 TCN / LSTM 的工厂；没装 torch 就跳过。"""
    if importlib.util.find_spec("torch") is None:
        print("跳过 TCN / LSTM：未安装 torch", file=sys.stderr)
        return {}
    from anomaly_lab.detectors.deep import (
        LSTMDetector,
        TCNDetector,
        train_lstm,
        train_tcn,
    )

    model_dir = CONFIG.data_dir / "cache" / "models"
    tcn_path = model_dir / "tcn.pt"
    lstm_path = model_dir / "lstm.pt"
    if not tcn_path.exists():
        print("训练 TCN …", file=sys.stderr)
        train_tcn(series_list[:24], epochs=epochs, seed=CONFIG.seed, out_path=tcn_path)
    if not lstm_path.exists():
        print("训练 LSTM …", file=sys.stderr)
        train_lstm(series_list[:24], epochs=epochs, seed=CONFIG.seed, out_path=lstm_path)
    return {
        "TCN": lambda: TCNDetector(model_path=tcn_path),
        "LSTM": lambda: LSTMDetector(model_path=lstm_path),
    }


#: (报告里的名字, 工厂)。顺序不影响结果，只影响进度打印。
def _specs(deep: dict[str, object]) -> list[tuple[str, object]]:
    from anomaly_lab.detectors.chronos import ChronosDetector, chronos_available

    rows: list[tuple[str, object]] = [
        ("IQR", IQRDetector),
        ("MAD", MADDetector),
        ("ZScore", ZScoreDetector),
        ("Seasonal", SeasonalDetector),
        ("STLResidual", STLResidualDetector),
        ("TrendResidualIQR", TrendResidualIQRDetector),
        ("TheilSen", TheilSenTrendDetector),
        ("ChangePoint", ChangePointDetector),
        ("EventCount", EventCountDetector),
    ]
    rows.extend(deep.items())
    if chronos_available():
        rows.append(("Chronos", ChronosDetector))
    else:
        print("跳过 Chronos：未安装或本地无权重缓存", file=sys.stderr)
    return rows


def _markdown(by_detector: dict) -> str:
    lines = [
        "| 检测器 | Precision | Recall | F1 | Range-F1 | 单条延迟 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, agg in sorted(by_detector.items(), key=lambda kv: -kv[1]["f1"]):
        lines.append(
            f"| {name} | {agg['precision']:.3f} | {agg['recall']:.3f} | "
            f"{agg['f1']:.3f} | {agg['range_f1']:.3f} | {agg['elapsed_ms']:.2f} ms |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="全部检测器回测 → reports/latest")
    parser.add_argument("--data", type=Path, default=None, help="数据目录，默认 data/synthetic")
    parser.add_argument("--out", type=Path, default=None, help="报告目录，默认 reports/latest")
    parser.add_argument("--detectors", default=None, help="逗号分隔，默认全部可用检测器")
    parser.add_argument("--epochs", type=int, default=3, help="深度模型训练轮数")
    args = parser.parse_args()

    data_dir = args.data or CONFIG.synthetic_dir
    series_list = load_dataset(data_dir)
    if not series_list:
        print(f"没有可加载的数据：{data_dir}", file=sys.stderr)
        return 1

    specs = _specs(_deep_factories(series_list, args.epochs))
    if args.detectors:
        wanted = {name.strip().lower() for name in args.detectors.split(",") if name.strip()}
        specs = [spec for spec in specs if spec[0].lower() in wanted]
        if not specs:
            print("没有匹配的检测器", file=sys.stderr)
            return 1

    rows = []
    for name, factory in specs:
        print(f"{name} …", file=sys.stderr)
        rows.extend(backtest_detector(series_list, factory))

    out_dir = args.out or (CONFIG.reports_dir / "latest")
    summary = build_report(rows, out_dir, title="Anomaly Lab 回测")
    overall = summary["overall"]
    print(
        f"总体：F1={overall['f1']:.3f} Precision={overall['precision']:.3f} "
        f"Recall={overall['recall']:.3f} Range-F1={overall['range_f1']:.3f} "
        f"（{len(rows)} 行 / {len(series_list)} 条序列）"
    )
    print()
    print(_markdown(summary["by_detector"]))
    print(f"\n报告已写入：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
