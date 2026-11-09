"""换检测算法时，告警阈值要跟着换 —— 分数的量纲变了。

⚠️ 这守的是一个**静默失效**：
   统计族的分数是「几个尺度单位」（阈值 2.5），
   Chronos 的分数是 [0,1] 的相对越界程度（阈值 0.5）。
   跨族沿用旧阈值 → 分数永远到不了 2.5 → **告警永远不触发**，
   而界面显示「一切正常」—— 那是假的。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from anomaly_lab.platform.detectors import (
    SCORE_FAMILY_PROB,
    SCORE_FAMILY_SCALE,
    detector_score_family,
)
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
        window_seconds=60 * 300,
        interval_seconds=300,
    )
    return store, job.id


def _make_store_with_defaults(tmp_path: Path) -> tuple[PlatformStore, int]:
    """建一个**阈值全是默认值**的任务（2.5 / 3.75 = iqr 的惯用阈值）。

    ⚠️ 与 `_make_store` 的区别：那里的 critical 是 4.0（≠ 默认 3.75），
    也就是「用户调过」的任务 —— 两者的换算法行为**应该不同**。
    """
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
        critical_threshold=3.75,
        window_seconds=60 * 300,
        interval_seconds=300,
    )
    return store, job.id


# ---------- 量纲族 ----------


def test_score_family_of_chronos_is_prob():
    assert detector_score_family("chronos") == SCORE_FAMILY_PROB


def test_score_family_of_statistical_detectors_is_scale():
    for name in ("iqr", "mad", "zscore", "seasonal", "stl_residual"):
        assert detector_score_family(name) == SCORE_FAMILY_SCALE


def test_auto_is_scale_family():
    """auto 只落到统计算法 —— 形态分类器的候选里没有 Chronos。"""
    assert detector_score_family("auto") == SCORE_FAMILY_SCALE


# ---------- 换算法时阈值跟着换 ----------


def test_switching_to_chronos_resets_thresholds(tmp_path):
    """⚠️ 换成 chronos → 阈值必须变成 0.5 量级，不能留 2.5。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(job_id, detector="chronos")

    assert updated.alert_threshold == 0.5
    assert updated.critical_threshold == 0.75
    # 规则表也要跟着换 —— 否则规则里还是 2.5/4.0
    rules = updated.alert_rules
    assert [rule["multiplier"] for rule in rules] == [0.5, 0.75]


def test_switching_back_from_chronos_resets_thresholds(tmp_path):
    """反向也要换回来 —— 0.5 在统计族里太松了。"""
    store, job_id = _make_store(tmp_path)
    store.update_job_config(job_id, detector="chronos")
    updated = store.update_job_config(job_id, detector="iqr")

    # ⚠️ iqr 的默认阈值是 2.5，严重档按平台的惯例是 ×1.5 = 3.75
    assert updated.alert_threshold == 2.5
    assert updated.critical_threshold == 3.75


def test_switching_within_same_family_keeps_thresholds(tmp_path):
    """⚠️ 同族换算法**不动**阈值 —— 用户调好的 2.5 在 mad 下依然有意义。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(job_id, detector="mad")

    assert updated.alert_threshold == 2.5
    assert updated.critical_threshold == 4.0


# ---------- 「继承来的默认值」与「用户调过的值」要分得清 ----------


def test_switching_to_a_detector_with_another_default_resets_inherited_thresholds(
    tmp_path,
):
    """⚠️ **同族换算法，但阈值从没被调过** → 按新算法的惯用阈值重设。

    这是本文件存在的第二个理由。同族换算法沿用旧阈值有个**盲点**：
    它分不清「用户特意调过的阈值」与「从来没动过的默认值」。

    后果很实在：iqr 的惯用阈值是 2.5，theil_sen 的是 3.5（实测值）。
    用户从没调过阈值，从 iqr 换到 theil_sen 后继续用 2.5 ——
    精确率会从 98% 掉到 73%，而界面**一点提示都没有**。
    """
    store, job_id = _make_store_with_defaults(tmp_path)
    updated = store.update_job_config(job_id, detector="theil_sen")

    assert updated.alert_threshold == 3.5
    assert updated.critical_threshold == pytest.approx(5.25)


def test_user_adjusted_thresholds_survive_a_same_family_switch(tmp_path):
    """⚠️ 用户**调过**阈值 → 换算法时保留他的值。

    这是「同族沿用旧阈值」这条规则的**本意**：
    用户可能特意把阈值调低（要更灵敏），不该被默认值冲掉。
    """
    store, job_id = _make_store(tmp_path)
    # 2.5 / 4.0 —— critical 不是 iqr 的默认 3.75，说明用户动过
    updated = store.update_job_config(job_id, detector="theil_sen")

    assert updated.alert_threshold == 2.5
    assert updated.critical_threshold == 4.0


def test_explicit_threshold_wins_over_family_reset(tmp_path):
    """⚠️ 用户**手填**的阈值是他自己的决定 —— 不该被覆盖。"""
    store, job_id = _make_store(tmp_path)
    updated = store.update_job_config(
        job_id, detector="chronos", alert_threshold=0.7, critical_threshold=0.9
    )

    assert updated.alert_threshold == 0.7
    assert updated.critical_threshold == 0.9


def test_set_job_detector_also_resets_thresholds(tmp_path):
    """⚠️ 多算法对比页选算法走的是另一个入口 —— 那里也要换。"""
    store, job_id = _make_store(tmp_path)
    updated = store.set_job_detector(job_id, "chronos")

    assert updated.detector == "chronos"
    assert updated.alert_threshold == 0.5
    assert [rule["multiplier"] for rule in updated.alert_rules] == [0.5, 0.75]


def test_set_job_detector_within_family_keeps_thresholds(tmp_path):
    store, job_id = _make_store(tmp_path)
    updated = store.set_job_detector(job_id, "mad")
    assert updated.alert_threshold == 2.5
    assert updated.critical_threshold == 4.0


def test_switching_to_chronos_actually_produces_alerts(tmp_path):
    """⚠️ **端到端**：换完算法后，任务得真的能报出告警。

    ⚠️ 这是整件事的意义 ——
       「规则表换成 0.5」只是配置对了；
       「跑起来真有告警」才是真的修好了。

    ⚠️ 序列要**够长**、尖峰要**靠后** ——
       Chronos 从 `min_context=8` 才开始评分，
       前面那些点分数恒为 0（它是预测模型，没有基线可外推）。
    """
    import sqlite3
    from datetime import timedelta

    from anomaly_lab.detectors.chronos import chronos_available
    from anomaly_lab.platform.runner import execute_job

    # ⚠️ 这条要走**真实模型** —— 包没装或权重没缓存时跳过，
    #    否则新克隆的仓库跑 CI 会红（optional extra 不该变成硬依赖）。
    if not chronos_available():
        pytest.skip("chronos 包或本地权重不可用")
    from anomaly_lab.platform.timeutil import to_iso, utcnow

    store, job_id = _make_store(tmp_path)
    path = tmp_path / "platform" / "source.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (ts TEXT, value REAL)")
    # 40 个点，尖峰在下标 20
    values = [10.0 + ((i * 7) % 5) * 0.2 for i in range(40)]
    values[20] = 80.0
    end = utcnow().replace(second=0, microsecond=0)
    n = len(values)
    conn.executemany(
        "INSERT INTO t VALUES (?, ?)",
        [
            (to_iso(end - timedelta(minutes=5 * (n - 1 - i))), float(v))
            for i, v in enumerate(values)
        ],
    )
    conn.commit()
    conn.close()

    store.update_job_config(job_id, detector="chronos")
    run_id = execute_job(store, job_id, data_root=tmp_path)
    run = store.get_run(run_id)

    assert run.status == "success"
    assert run.n_alerts > 0, "换成 chronos 后应该报得出告警（阈值已跟着换）"
