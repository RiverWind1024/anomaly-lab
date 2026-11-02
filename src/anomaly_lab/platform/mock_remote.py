"""把平台侧配置成「指向假远端」：HTTP 数据源 + 指标 + 检测任务。

⚠️ **为什么要有这个**：光有假远端不够 —— 用户还得在 UI 里手填 url、
写 body、写指标 SQL。演示路径必须是「一条命令」。

⚠️ **职责边界**：造数与查询是假远端的事；**数据源配置属于平台的数据**，
所以这个函数放在 `platform/` 下，由 CLI 调用。
"""

from __future__ import annotations

from pathlib import Path

from anomaly_lab.platform.store import PlatformStore

#: 数据源名（幂等键）。
SOURCE_NAME = "mock-tsdb"
#: 指标名（幂等键）。
METRIC_NAME = "mock-tsdb-traffic"
#: 检测任务名（幂等键）。
JOB_NAME = "mock-tsdb-job"

#: 假远端的默认地址（InfluxDB 3 的默认端口）。
DEFAULT_BASE_URL = "http://127.0.0.1:8181"
#: 请求里的 `db` 字段。
DEFAULT_DB = "mock"

#: 指标 SQL —— 表名/列名必须与假远端的表结构一致。
QUERY = "SELECT ts, series, value FROM metrics WHERE $timefilter ORDER BY ts"

#: 采样频率 —— 假远端 1 分钟一个点。
FREQ = "1min"
#: 检测窗口的点数（60 点 = 1 小时）。
WINDOW_POINTS = 60
#: 任务的执行间隔（秒）。
INTERVAL_SECONDS = 60
ALERT_THRESHOLD = 2.5
CRITICAL_THRESHOLD = 4.0


def source_config(base_url: str = DEFAULT_BASE_URL, db: str = DEFAULT_DB) -> dict:
    """HTTP 数据源的 config。

    ⚠️ **`{sql}` 放 body 不放 url** ——
       body 里的替换是**原样**的，SQL 不会被百分号编码污染；
       url 里的替换会 URL 编码（spec 1 的决定）。

    ⚠️ **body 里写 `format`，config 里也写 `format`** ——
       两者必须一致，否则平台当场报 400
       （「请求的格式与解析的格式必须对齐」）。
    """
    return {
        "url": f"{base_url.rstrip('/')}/api/v3/query_sql",
        "method": "POST",
        "body": {"db": db, "q": "{sql}", "format": "csv"},
        "format": "csv",
        "timeout_seconds": 30,
    }


def seed_mock_remote(
    data_root: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
    db: str = DEFAULT_DB,
) -> dict:
    """幂等地建好源 / 指标 / 任务，返回它们的 ID。

    ⚠️ **幂等** —— 重复跑不会重复建（按名字找）。
    """
    data_root = Path(data_root)
    store = PlatformStore(data_root / "platform.db")

    source = store.find_source_by_name(SOURCE_NAME)
    if source is None:
        source = store.add_source(
            SOURCE_NAME, "", kind="http", config=source_config(base_url, db)
        )

    metric = store.find_metric_by_name(source.id, METRIC_NAME)
    if metric is None:
        metric = store.add_metric(
            source_id=source.id,
            name=METRIC_NAME,
            query=QUERY,
            time_column="ts",
            value_column="value",
            group_column="series",
            time_format="iso_utc",
            freq=FREQ,
            source_timezone="UTC",
            missing_policy="drop",
        )

    job = store.find_job_by_name(JOB_NAME)
    if job is None:
        job = store.add_job(
            metric_id=metric.id,
            name=JOB_NAME,
            detector="iqr",
            alert_threshold=ALERT_THRESHOLD,
            critical_threshold=CRITICAL_THRESHOLD,
            window_points=WINDOW_POINTS,
            interval_seconds=INTERVAL_SECONDS,
        )

    return {
        "source_id": source.id,
        "metric_id": metric.id,
        "job_id": job.id,
        "base_url": base_url,
        "db": db,
    }
