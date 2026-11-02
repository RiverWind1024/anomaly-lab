"""假远端时序数据库：照 InfluxDB 3 的 API 形状，持续造数。

它是一个**独立进程**（`python -m anomaly_lab.mock_tsdb`），
不是平台的一个模块 —— 只有这样，「远端调用」才是真的
（连接、超时、502 都成立）。

⚠️ **它不是 InfluxDB** —— 抄的是接口形状，不是查询引擎。
   内部用 SQLite 存数据并执行 SQL。
"""

from __future__ import annotations

from anomaly_lab.mock_tsdb.generator import (
    KIND_GAP,
    KIND_NULL,
    KIND_VALUE,
    SAMPLE_SECONDS,
    SERIES,
    Generator,
    SeriesSpec,
)
from anomaly_lab.mock_tsdb.server import (
    SUPPORTED_FORMATS,
    MockConfig,
    create_app,
    serve,
    wait_until_ready,
)
from anomaly_lab.mock_tsdb.tsdb import MockTsdb, parse_iso, to_iso

__all__ = [
    "KIND_GAP",
    "KIND_NULL",
    "KIND_VALUE",
    "SAMPLE_SECONDS",
    "SERIES",
    "SUPPORTED_FORMATS",
    "Generator",
    "MockConfig",
    "MockTsdb",
    "SeriesSpec",
    "create_app",
    "parse_iso",
    "serve",
    "to_iso",
    "wait_until_ready",
]
