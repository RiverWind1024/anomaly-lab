"""检测器**改名**的兼容机制。

⚠️ 这个文件守的是「改名不打断已有数据」：

   检测器名会进**历史数据** —— 评测产物、任务配置、告警记录里都写着算法名。
   改名就等于让那些记录里的算法名变成「不认识的名字」：
   界面显示不出来，重跑也找不到对应算法。

   所以 `deseasonalized_iqr`（旧名，说的是「去季节化」，
   做的却是「去**趋势**」）改名成 `trend_residual_iqr` 之后，
   **旧名必须仍然可用**。
"""

from __future__ import annotations

import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.detectors import (
    DETECTOR_ALIASES,
    DETECTOR_FACTORIES,
    canonical_detector_name,
    create_detector,
    detector_available,
    detector_catalog,
    detector_score_family,
    resolve_detector,
)


def _trending(n=500):
    rng = np.random.default_rng(3)
    values = 0.077 * np.arange(n, dtype=float) + rng.normal(0, 0.74, n)
    return SeriesBundle(
        series_id="trending",
        values=values,
        timestamps=list(range(n)),
        freq="5min",
    )


# ---------- 别名解析 ----------


def test_old_name_still_creates_a_detector():
    """⚠️ 旧名仍能造出检测器 —— 历史数据里的名字不能失效。"""
    detector = create_detector("deseasonalized_iqr")
    assert detector.name == "trend_residual_iqr"


def test_old_name_resolves_to_the_new_name():
    assert canonical_detector_name("deseasonalized_iqr") == "trend_residual_iqr"
    assert canonical_detector_name("iqr") == "iqr"


def test_old_name_is_not_in_the_catalog():
    """⚠️ 下拉清单里**只出现主名** —— 否则用户会看到两个一样的选项。"""
    names = [row["name"] for row in detector_catalog()]
    assert "trend_residual_iqr" in names
    assert "deseasonalized_iqr" not in names


def test_old_name_is_reported_as_available():
    """⚠️ 旧名不能被判成「不支持的检测器」—— 它只是改过名。"""
    available, reason = detector_available("deseasonalized_iqr")
    assert available, reason


def test_old_name_keeps_the_same_score_family():
    assert detector_score_family("deseasonalized_iqr") == detector_score_family(
        "trend_residual_iqr"
    )


def test_unknown_name_is_still_rejected():
    with pytest.raises(ValueError, match="不支持"):
        create_detector("根本没有这个算法")


def test_alias_points_at_an_existing_detector():
    """别名表里的每个名字都必须指向真实存在的检测器 —— 否则是死路。"""
    for alias, target in DETECTOR_ALIASES.items():
        assert target in DETECTOR_FACTORIES, f"{alias} → {target} 不存在"
        assert canonical_detector_name(alias) == target


# ---------- auto 选型 ----------


def test_auto_picks_the_trend_detector_for_a_trending_series():
    """⚠️ **核心**：auto 遇到趋势型序列要选**去趋势**的算法，不能落到 iqr。

    这正是用户问的那个问题 ——
    趋势型序列用 IQR 会大幅漏报（合成集上召回只有 20%）。
    """
    resolution = resolve_detector("auto", _trending())
    assert resolution.metric_class == "trending"
    assert resolution.detector == "theil_sen"
    assert resolution.fallback is False


def test_auto_does_not_fall_back_to_iqr_for_trending():
    """⚠️ auto 的兜底算法是 iqr —— 趋势型序列绝不能走到那里。

    兜底是对的（通用算法），但对趋势型来说是**静默失效**：
    iqr 在趋势上召回只有 20%，界面却显示「一切正常」。
    """
    resolution = resolve_detector("auto", _trending())
    assert resolution.detector != "iqr"
    assert resolution.detector != "trend_residual_iqr" or "theil_sen" in resolution.candidates


def test_auto_candidates_are_canonical_names():
    """候选列表统一成主名 —— 旧名不该出现在推荐结果里。"""
    resolution = resolve_detector("auto", _trending())
    assert all(name not in DETECTOR_ALIASES for name in resolution.candidates)


def test_theil_sen_is_registered():
    assert "theil_sen" in DETECTOR_FACTORIES
    available, reason = detector_available("theil_sen")
    assert available, reason
