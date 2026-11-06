"""指标注册表：标签、分位、按分钟增量。"""

import threading
from datetime import UTC, datetime, timedelta

from anomaly_lab.observability.registry import (
    MetricsRegistry,
    SystemStats,
    flat_key,
    parse_key,
    percentile,
)


def test_标签顺序不影响指标身份():
    registry = MetricsRegistry()
    registry.inc("http.requests", method="GET", route="/jobs/{job_id}")
    registry.inc("http.requests", route="/jobs/{job_id}", method="GET")

    # ⚠️ 路由模板里带花括号，值必须能原样往返 —— 这正是不能用 `{k=v}` 格式的原因。
    assert registry.counter("http.requests", method="GET", route="/jobs/{job_id}") == 2


def test_扁平键能往返解析含特殊字符的标签():
    key = flat_key("http.requests", {"route": "/jobs/{job_id}", "method": "GET"})
    name, labels = parse_key(key)
    assert name == "http.requests"
    assert labels == {"route": "/jobs/{job_id}", "method": "GET"}


def test_没有标签时键就是指标名():
    assert flat_key("scheduler.ticks") == "scheduler.ticks"
    assert parse_key("scheduler.ticks") == ("scheduler.ticks", {})


def test_分位在桶内插值():
    counts = [0] * 16
    counts[3] = 100  # 10ms 落在 [5, 10] 桶
    # 桶内均匀分布假设：50% 位置 = 5 + (10-5)*0.5
    assert percentile(counts, 100, 0.50) == 7.5


def test_没有样本时分位为空():
    assert percentile([0] * 16, 0, 0.95) is None


def test_快照只记增量():
    registry = MetricsRegistry()
    now = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
    registry.inc("http.requests", method="GET", route="/a")
    first = registry.take_snapshot(now, SystemStats())
    assert sum(first.counters.values()) == 1

    registry.inc("http.requests", method="GET", route="/a")
    second = registry.take_snapshot(now + timedelta(minutes=1), SystemStats())
    # 第二次只该看到新增的那一条，不是累计的 2
    assert sum(second.counters.values()) == 1


def test_不在白名单的指标不进每分钟历史():
    registry = MetricsRegistry()
    registry.inc("detector.calls", detector="iqr")
    point = registry.take_snapshot(datetime.now(UTC), SystemStats())
    assert point.counters == {}
    # 但累计值仍然在
    assert registry.counter("detector.calls", detector="iqr") == 1


def test_历史点数超过上限时丢最旧的():
    registry = MetricsRegistry(max_points=2)
    for index in range(5):
        registry.take_snapshot(
            datetime(2026, 11, 6, 10, index, tzinfo=UTC), SystemStats()
        )
    assert len(registry.points()) == 2
    assert registry.points()[-1].at.minute == 4


def test_并发递增不会丢计数():
    registry = MetricsRegistry()
    threads = [
        threading.Thread(target=lambda: [registry.inc("http.requests") for _ in range(500)])
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert registry.counter("http.requests") == 4000


def test_直方图摘要给出平均与分位():
    registry = MetricsRegistry()
    for _ in range(100):
        registry.observe("http.request_ms", 10.0)
    summary = registry.histogram_with_prefix("http.request_ms")
    key = next(iter(summary))
    assert summary[key]["count"] == 100
    assert summary[key]["avg_ms"] == 10.0
    # 所有样本在 [5,10] 桶，95% 位置插值到 9.75
    assert summary[key]["p95_ms"] == 9.75
