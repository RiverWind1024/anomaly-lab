"""告警规则**可以自由编辑**了 —— 阈值不该只在新建任务时能填。

⚠️ 之前 `JobToggleIn` 里没有 `alert_rules`，规则表是**只读**的：
   任务建好之后，2.5 / 3.75 这些阈值就改不了了 ——
   只能重建一个任务。而「调阈值」恰恰是最常见的调参动作。

⚠️ 这里守的是**两边一致**：
   `alert_threshold` / `critical_threshold` 是规则表的快捷视图
   （最低档 / 最高档倍数）。显式改了规则表，阈值必须跟着走；
   反过来只改阈值，规则表会被重算。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anomaly_lab.platform.store import PlatformStore


def _make_store(tmp_path: Path) -> tuple[PlatformStore, int]:
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("local", "platform/source.db")
    metric = store.add_metric(
        source_id=source.id,
        name="cpu",
        query="SELECT ts, value FROM t WHERE $timefilter ORDER BY ts",
        time_column="ts",
        value_column="value",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="job",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=4.0,
        window_points=60,
        interval_seconds=300,
    )
    return store, job.id


# ---------- 显式改规则表 ----------


def test_explicit_rules_are_stored(tmp_path):
    """⚠️ 规则表能被改 —— 这是本文件的全部意义。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(
        job_id,
        alert_rules=[
            {"multiplier": 3.0, "level": "P1"},
            {"multiplier": 5.0, "level": "P0"},
        ],
    )
    assert [rule["multiplier"] for rule in updated.alert_rules] == [3.0, 5.0]
    assert [rule["level"] for rule in updated.alert_rules] == ["P1", "P0"]


def test_explicit_rules_sync_thresholds(tmp_path):
    """⚠️ 阈值是规则表的**快捷视图** —— 改了规则表，阈值必须跟着走。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(
        job_id,
        alert_rules=[
            {"multiplier": 3.0, "level": "P1"},
            {"multiplier": 5.0, "level": "P0"},
        ],
    )
    assert updated.alert_threshold == 3.0
    assert updated.critical_threshold == 5.0


def test_explicit_rules_are_not_overwritten_by_threshold_resync(tmp_path):
    """⚠️ 显式规则表**优先** —— 不能被「阈值变了就重算规则表」冲掉。

    这正是 `update_job_config` 原本的逻辑：阈值一变就把规则表重算成
    `default_rules(alert, critical)`。有显式规则时不能那样。
    """
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(
        job_id,
        alert_rules=[
            {"multiplier": 3.0, "level": "P1"},
            {"multiplier": 5.0, "level": "P0"},
        ],
    )
    # 再改一次别的字段 —— 规则表不该被冲回默认两档
    updated = store.update_job_config(job_id, name="改名了")
    assert [rule["multiplier"] for rule in updated.alert_rules] == [3.0, 5.0]


def test_explicit_rules_win_over_detector_reset_in_same_call(tmp_path):
    """⚠️ **同一次调用**里既换算法又给规则 → 规则优先。

    用户明知道自己要什么（他同时改了两样），不该被「换算法自动换阈值」
    覆盖掉 —— 那是**跨调用**的保护逻辑。
    """
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(
        job_id,
        detector="chronos",
        alert_rules=[
            {"multiplier": 0.4, "level": "P1"},
            {"multiplier": 0.6, "level": "P0"},
        ],
    )
    assert [rule["multiplier"] for rule in updated.alert_rules] == [0.4, 0.6]
    assert updated.alert_threshold == 0.4
    assert updated.critical_threshold == 0.6


def test_switching_detector_rescales_multipliers_but_keeps_absolute_rules(tmp_path):
    """⚠️ 换算法时**倍数**会重算（量纲变了，不换就是静默失效），
    但用户配的**绝对值条件**不该跟着消失。"""
    store, job_id = _make_store(tmp_path)
    store.update_job_config(
        job_id,
        alert_rules=[
            {"multiplier": 2.5, "level": "P1"},
            {"multiplier": 3.75, "level": "P0"},
            {"op": ">", "value": 50, "level": "P0"},
        ],
    )
    updated = store.update_job_config(job_id, detector="chronos")
    multipliers = [r["multiplier"] for r in updated.alert_rules if "multiplier" in r]
    assert multipliers == [0.5, 0.75]
    # ⚠️ 绝对值条件保留
    assert any(r.get("op") == ">" and r.get("value") == 50 for r in updated.alert_rules)


def test_absolute_conditions_can_be_added(tmp_path):
    """⚠️ 绝对值条件（并行补充）也能一起编。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(
        job_id,
        alert_rules=[
            {"multiplier": 2.5, "level": "P1"},
            {"multiplier": 3.75, "level": "P0"},
            {"op": ">", "value": 50, "level": "P0"},
        ],
    )
    assert len(updated.alert_rules) == 3
    assert updated.alert_rules[2]["op"] == ">"
    assert updated.alert_rules[2]["value"] == 50
    # 阈值取的是**倍数**条件里的最低/最高档
    assert updated.alert_threshold == 2.5
    assert updated.critical_threshold == 3.75


# ---------- 校验 ----------


def test_duplicate_multipliers_are_rejected(tmp_path):
    store, job_id = _make_store(tmp_path)
    with pytest.raises(ValueError, match="不能重复"):
        store.update_job_config(
            job_id,
            alert_rules=[
                {"multiplier": 2.5, "level": "P1"},
                {"multiplier": 2.5, "level": "P0"},
            ],
        )


def test_out_of_order_multipliers_are_rejected(tmp_path):
    """⚠️ 规则表的**顺序即档位顺序**（从低到高严重）—— 乱序会让等级错乱。"""
    store, job_id = _make_store(tmp_path)
    with pytest.raises(ValueError, match="从小到大"):
        store.update_job_config(
            job_id,
            alert_rules=[
                {"multiplier": 5.0, "level": "P1"},
                {"multiplier": 2.5, "level": "P0"},
            ],
        )


def test_single_multiplier_is_rejected(tmp_path):
    """⚠️ 只有一档 → 阈值没法既是最low档又是最高档。"""
    store, job_id = _make_store(tmp_path)
    with pytest.raises(ValueError, match="至少要有两个"):
        store.update_job_config(
            job_id, alert_rules=[{"multiplier": 2.5, "level": "P1"}]
        )


def test_non_positive_multiplier_is_rejected(tmp_path):
    store, job_id = _make_store(tmp_path)
    with pytest.raises(ValueError, match="正数"):
        store.update_job_config(
            job_id,
            alert_rules=[
                {"multiplier": 0, "level": "P1"},
                {"multiplier": 2.5, "level": "P0"},
            ],
        )


def test_empty_rules_are_rejected(tmp_path):
    store, job_id = _make_store(tmp_path)
    with pytest.raises(ValueError, match="至少需要一条"):
        store.update_job_config(job_id, alert_rules=[])


# ---------- 只改阈值时，规则表仍然重算（原有行为不变）----------


def test_threshold_change_still_resyncs_rules(tmp_path):
    """⚠️ 原有行为不能被破坏：只改阈值 → 规则表跟着重算。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(job_id, alert_threshold=3.0, critical_threshold=6.0)
    assert [rule["multiplier"] for rule in updated.alert_rules] == [3.0, 6.0]
