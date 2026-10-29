"""稳健清洗工具：估计前处理离群点。

核心约定：**清洗只用于估计，不用于打分**。
"""

import numpy as np

from anomaly_lab.detectors.robust import outlier_mask, robust_scale, winsorize


def test_winsorize_keeps_length_and_positions():
    """截尾不能改变点数与时间轴——相位分组靠下标取模定位。"""
    values = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 100.0])
    cleaned = winsorize(values)
    assert len(cleaned) == len(values)
    assert np.all(np.isfinite(cleaned))
    assert cleaned.max() < 100.0


def test_winsorize_leaves_normal_values_untouched():
    values = np.array([10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 11.0])
    assert np.allclose(winsorize(values), values)


def test_winsorize_caps_the_outlier():
    values = np.concatenate([np.full(50, 10.0), [1000.0]])
    cleaned = winsorize(values)
    assert cleaned[-1] < 1000.0
    assert cleaned[-1] > 10.0


def test_outlier_mask_flags_only_the_outlier():
    values = np.concatenate([np.full(50, 10.0), [1000.0]])
    mask = outlier_mask(values)
    assert mask.sum() == 1
    assert mask[-1]


def test_robust_scale_falls_back_to_std_for_constant_series():
    assert robust_scale(np.full(20, 5.0)) == 0.0


def test_robust_scale_uses_mad():
    values = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    scale = robust_scale(values)
    # MAD 不受那个 100 影响
    assert scale < 5.0


def test_winsorize_handles_short_series():
    values = np.array([1.0, 2.0, 100.0])
    assert len(winsorize(values)) == 3


def test_winsorize_handles_constant_series():
    values = np.full(20, 3.0)
    assert np.allclose(winsorize(values), values)


def test_outlier_mask_on_constant_series_is_all_false():
    assert not outlier_mask(np.full(20, 3.0)).any()
