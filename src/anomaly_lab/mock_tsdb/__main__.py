"""假远端的启动入口：`python -m anomaly_lab.mock_tsdb`。

用法：
    python -m anomaly_lab.mock_tsdb                      # 默认 127.0.0.1:8181
    python -m anomaly_lab.mock_tsdb --port 9000
    python -m anomaly_lab.mock_tsdb --db-path data/mock_tsdb/tsdb.db
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from anomaly_lab.mock_tsdb.generator import DEFAULT_RETENTION_HOURS
from anomaly_lab.mock_tsdb.server import MockConfig, serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anomaly-lab mock-tsdb", description="假远端时序数据库（InfluxDB 3 形状）"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8181)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/mock_tsdb/tsdb.db"),
        help="SQLite 文件路径（WAL 模式）",
    )
    parser.add_argument(
        "--retention-hours",
        type=int,
        default=DEFAULT_RETENTION_HOURS,
        help="保留窗口（小时）—— 之外的数据会被删掉",
    )
    parser.add_argument(
        "--history-points",
        type=int,
        default=360,
        help="启动时回填多少个历史点（1 分钟一个）",
    )
    parser.add_argument(
        "--write-interval",
        type=int,
        default=10,
        help="后台写入线程的间隔（秒）",
    )
    parser.add_argument(
        "--no-writer", action="store_true", help="不启动后台写入线程（只回放历史）"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    config = MockConfig(
        db_path=args.db_path,
        retention_hours=args.retention_hours,
        history_points=args.history_points,
        write_interval_seconds=args.write_interval,
        autostart=not args.no_writer,
    )
    print(f"假远端 → http://{args.host}:{args.port}/api/v3/query_sql", flush=True)
    print(f"  数据文件：{args.db_path}", flush=True)
    serve(config, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
