"""人工反馈 → 阈值建议：闭环的「优化」环节。"""

import numpy as np
import pytest

from anomaly_lab.platform.feedback import (
    Annotation,
    SeriesOutcome,
    candidate_multipliers,
    suggest_setting,
    to_naive_ns,
)
from anomaly_lab.platform.store import PlatformStore


def _outcome(scores: list[float], start: str = "2026-01-01T00:00:00") -> SeriesOutcome:
    base = to_naive_ns(start)
    stamps = base + np.arange(len(scores)).astype("timedelta64[5m]")
    return SeriesOutcome(
        series_id="demo",
        timestamps=stamps,
        scores=np.asarray(scores, dtype=float),
    )


def test_no_feedback_means_no_suggestion():
    """没有反馈就不猜，倍数保持原样并说明原因。"""
    suggestion = suggest_setting({"iqr": [_outcome([1.0, 2.0])]}, [], "iqr", 2.5)
    assert suggestion.suggested_multiplier == 2.5
    assert suggestion.best is None
    assert "反馈" in suggestion.reason


def test_only_correct_feedback_means_no_suggestion():
    """correct/other 不指示调参方向，不参与评估。"""
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T02:00:00", "correct")]
    suggestion = suggest_setting({"iqr": [_outcome([1.0, 2.0])]}, notes, "iqr", 2.5)
    assert suggestion.suggested_multiplier == 2.5
    assert suggestion.best is None


def test_false_alarms_only_pushes_multiplier_up():
    """只有误报反馈 → 应该调保守（倍数变大、告警变少）。"""
    scores = [3.0] * 100
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T12:00:00", "false_alarm")]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 2.5)
    assert suggestion.suggested_multiplier > 2.5
    assert suggestion.best is not None
    assert suggestion.best.fp == 0
    assert "误报" in suggestion.reason


def test_false_alarms_only_keeps_the_change_minimal():
    """只有误报时也要取**最小干预**：能消掉误报的最小倍数即可。"""
    # 分数 1.5 的点被标成误报；倍数抬到 2.0 就不报了，不该一路推到 20
    scores = [1.5] * 100
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T12:00:00", "false_alarm")]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 1.0)
    assert suggestion.suggested_multiplier == 2.0


def test_missing_side_is_reported_as_none_not_one():
    """没有正例就没有 recall——不能拿 1.0 冒充「完美召回」。"""
    scores = [3.0] * 10
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "false_alarm")]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 2.5)
    best = suggestion.best
    assert best is not None
    assert best.recall is None
    assert best.f1 is None
    # 评估区间里一个告警都没有 → 没有 precision 可谈，同样如实留空
    assert best.precision is None


def test_precision_is_reported_when_there_are_alerts():
    scores = [3.0] * 10
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "false_alarm")]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 1.0)
    # 当前倍数下：报了但全是误报 → precision = 0
    current = suggestion.current
    assert current is not None
    assert current.precision == 0.0
    assert current.fp == 10
    assert current.recall is None  # 没有正例区间，召回无从谈起


def test_few_feedback_warns_about_small_sample():
    """反馈太少时要在建议里说明样本偏少。"""
    scores = [3.0] * 10
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "false_alarm")]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 2.5)
    assert "样本偏少" in suggestion.reason


def test_missed_only_pushes_multiplier_down():
    """只有漏报反馈 → 应该调灵敏（倍数变小、告警变多）。"""
    scores = [0.1] * 100
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T12:00:00", "missed")]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 2.5)
    assert suggestion.suggested_multiplier < 2.5
    assert suggestion.best is not None
    assert suggestion.best.recall == 1.0
    assert "漏报" in suggestion.reason


def test_mixed_feedback_maximises_f1():
    """正反例都有时按 F1 选：既能召回真异常，又少误报。"""
    # 前 50 个是高分但其实正常（误报），后 50 个是低分但真异常（漏报）
    scores = [3.0] * 50 + [0.2] * 50
    notes = [
        Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T04:00:00", "false_alarm"),
        Annotation("demo", "2026-01-01T04:05:00", "2026-01-01T08:00:00", "missed"),
    ]
    suggestion = suggest_setting({"iqr": [_outcome(scores)]}, notes, "iqr", 2.5)
    assert suggestion.best is not None
    assert suggestion.best.f1 > 0
    # 最优解是「全都报」：召回 1，代价是误报，但比一个都不报好
    assert suggestion.best.recall == 1.0
    assert suggestion.suggested_multiplier < 2.5


def test_candidate_grid_contains_current_multiplier():
    values = candidate_multipliers(2.5)
    assert 2.5 in values
    assert values == sorted(values)
    assert all(value > 0 for value in values)


def test_annotations_are_scoped_to_their_series():
    """不同序列的反馈不能串味。"""
    first = SeriesOutcome(
        series_id="a",
        timestamps=_outcome([1.0, 2.0]).timestamps,
        scores=np.array([1.0, 2.0]),
    )
    second = SeriesOutcome(
        series_id="b",
        timestamps=_outcome([1.0, 2.0]).timestamps,
        scores=np.array([9.0, 9.0]),
    )
    notes = [Annotation("a", "2026-01-01T00:00:00", "2026-01-01T00:10:00", "missed")]
    suggestion = suggest_setting({"iqr": [first, second]}, notes, "iqr", 2.5)
    assert suggestion.best is not None
    # 只有序列 a 的两个点参与评估
    assert suggestion.best.fn + suggestion.best.tp == 2


def test_timezone_aware_input_is_normalised_to_utc():
    assert to_naive_ns("2026-01-01T08:00:00+08:00") == to_naive_ns(
        "2026-01-01T00:00:00Z"
    )


def test_empty_series_does_not_crash():
    suggestion = suggest_setting({}, [], "iqr", 2.5)
    assert suggestion.suggested_multiplier == 2.5


def test_suggestion_can_switch_detector():
    """倍数解决不了时才换算法。

    这里 iqr 的分数有一半高达 100——把倍数调到 20 也照样误报；
    另一个算法全程安静。所以换算法是唯一出路。
    """
    outcomes = {
        "iqr": [_outcome([0.1] * 50 + [100.0] * 50)],
        "seasonal": [_outcome([0.1] * 100)],
    }
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T12:00:00", "false_alarm")]
    suggestion = suggest_setting(outcomes, notes, "iqr", 1.0)
    assert suggestion.detector_changed is True
    assert suggestion.suggested_detector == "seasonal"
    assert suggestion.current_detector == "iqr"
    assert "更适合用 seasonal" in suggestion.reason


def test_threshold_change_is_preferred_over_switching_detector():
    """倍数能解决时不动算法——调阈值比换算法便宜得多。"""
    outcomes = {
        "iqr": [_outcome([3.0] * 100)],
        "seasonal": [_outcome([0.1] * 100)],
    }
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T12:00:00", "false_alarm")]
    suggestion = suggest_setting(outcomes, notes, "iqr", 1.0)
    assert suggestion.detector_changed is False
    assert suggestion.suggested_multiplier > 1.0


def test_prefers_keeping_the_current_detector_on_a_tie():
    """两个算法表现一样时，不折腾算法（最小干预）。"""
    outcomes = {
        "iqr": [_outcome([0.1] * 100)],
        "seasonal": [_outcome([0.1] * 100)],
    }
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T12:00:00", "false_alarm")]
    suggestion = suggest_setting(outcomes, notes, "iqr", 1.0)
    assert suggestion.detector_changed is False
    assert suggestion.suggested_detector == "iqr"


def test_candidates_cover_every_detector_and_multiplier():
    outcomes = {
        "iqr": [_outcome([1.0] * 10)],
        "seasonal": [_outcome([1.0] * 10)],
    }
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T01:00:00", "missed")]
    suggestion = suggest_setting(outcomes, notes, "iqr", 1.0)
    detectors = {item["detector"] for item in suggestion.candidates}
    assert detectors == {"iqr", "seasonal"}
    for item in suggestion.candidates:
        assert "multiplier" in item and "f1" in item


@pytest.mark.parametrize("kind", ["correct", "false_alarm", "missed", "other"])
def test_all_feedback_kinds_are_accepted(kind):
    notes = [Annotation("demo", "2026-01-01T00:00:00", "2026-01-01T01:00:00", kind)]
    suggestion = suggest_setting({"iqr": [_outcome([1.0, 2.0])]}, notes, "iqr", 2.5)
    assert suggestion.current_multiplier == 2.5


# ---------- 存储层 ----------


def _job(store):
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="cpu",
        query="SELECT ts, host, value FROM metrics WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
        group_column="host",
        time_format="iso_utc",
    )
    return store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=3.75,
        window_seconds=100 * 300,
        interval_seconds=300,
    )


def test_feedback_is_stored_and_listed(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    item = store.add_feedback(
        job_id=job.id,
        series_id="cpu:a",
        start_ts="2026-01-01T00:00:00",
        end_ts="2026-01-01T01:00:00",
        kind="false_alarm",
        note="其实是正常波动",
    )
    assert item.kind == "false_alarm"
    assert item.note == "其实是正常波动"
    assert [row.id for row in store.list_feedback(job.id)] == [item.id]


def test_feedback_validates_kind_range_and_job(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    with pytest.raises(ValueError, match="反馈类型"):
        store.add_feedback(
            job_id=job.id,
            series_id="cpu:a",
            start_ts="2026-01-01T00:00:00",
            end_ts="2026-01-01T01:00:00",
            kind="unknown",
        )
    with pytest.raises(ValueError, match="结束时间"):
        store.add_feedback(
            job_id=job.id,
            series_id="cpu:a",
            start_ts="2026-01-01T01:00:00",
            end_ts="2026-01-01T00:00:00",
            kind="missed",
        )
    with pytest.raises(ValueError, match="任务不存在"):
        store.add_feedback(
            job_id=999,
            series_id="cpu:a",
            start_ts="2026-01-01T00:00:00",
            end_ts="2026-01-01T01:00:00",
            kind="missed",
        )


def test_update_job_rules_rescales_thresholds(tmp_path):
    store = PlatformStore(tmp_path / "platform.db")
    job = _job(store)
    updated = store.update_job_rules(
        job.id,
        [
            {"multiplier": 1.0, "level": "P2"},
            {"multiplier": 3.0, "level": "P1"},
        ],
    )
    assert updated.alert_threshold == 1.0
    assert updated.critical_threshold == 3.0
    assert updated.alert_rules[0]["multiplier"] == 1.0
