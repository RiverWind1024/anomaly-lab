"""连接器层：按数据源类型取数。

⚠️ 这里的注册表是**极简**的 —— 一个 kind → 构造函数的映射，
   不做插件动态加载（没有那个需求）。
"""

from __future__ import annotations

from pathlib import Path

from anomaly_lab.platform.models import Source
from anomaly_lab.platform.validation import validate_kind

__all__ = ["SUPPORTED_KINDS", "get_connector"]

SUPPORTED_KINDS = ("sqlite", "http")


def get_connector(source: Source, data_root: Path):
    """按数据源类型拿连接器。

    ⚠️ `source.config` 必须是**未脱敏**的原始值 —— 调用方拿到的应是
       `store.get_source_raw()` 的结果。
    """
    kind = validate_kind(source.kind)
    if kind == "sqlite":
        from anomaly_lab.platform.sources.sqlite import SqliteConnector

        return SqliteConnector(source, data_root)
    from anomaly_lab.platform.sources.http_sql import HttpSqlConnector

    return HttpSqlConnector(source)
