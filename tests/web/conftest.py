"""Web 层测试的共享 fixture。"""

from pathlib import Path

import pytest

from anomaly_lab.platform.store import PlatformStore


@pytest.fixture
def store_with_job(tmp_path: Path) -> PlatformStore:
    """一个含数据源 / 指标 / 任务的 store（任务**没有运行记录**）。

    ⚠️ store 的方法名是 `add_source` / `add_metric` / `add_job`（不是 create_*），
    且 `add_metric` / `add_job` 的参数**全是关键字参数**。
    """
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("s", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="m",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    store.add_job(
        metric_id=metric.id,
        name="j",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_seconds=60 * 300,
        interval_seconds=60,
    )
    return store


@pytest.fixture
def make_dist(tmp_path: Path):
    """造一个假的 frontend/dist，供 SPA 路由测试用。"""

    def _make() -> Path:
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text(
            "<!doctype html><html><body>根</body></html>", encoding="utf-8"
        )
        (dist / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
        return dist

    return _make
