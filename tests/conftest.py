"""测试全局夹具。

⚠️ **只隔离监控库**，不动 `ANOMALY_LAB_DATA_DIR`：
   有些测试依赖仓库里真实的 `data/synthetic`，把整个数据目录重定向到 tmp
   会让它们找不到数据。

监控库是**运行时产物**，测试没有理由往仓库里写；而且 `create_app()` 不传
`platform_data_root` 时默认就是 `data/`，不隔离的话全量测试会污染它。
"""

import pytest

from anomaly_lab.observability import reset_observability


@pytest.fixture(autouse=True)
def _isolate_metrics_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ANOMALY_MONITOR_DB", str(tmp_path / "metrics.db"))
    # 上一个测试可能留下已配置的单例（指向它自己的 tmp 路径）。
    reset_observability()
    yield
    reset_observability()
