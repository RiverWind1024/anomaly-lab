"""稳健清洗：估计之前的离群点处理。

## 关键约定：清洗只用于「估计」，不用于「打分」

打分必须用**原始值**。如果把异常点从输入里洗掉，检测器就看不见它，
反而变成漏报——检测器存在的意义就是发现这些点。

清洗只用来让**估计量**（周期、基线、分解、趋势）不被离群点带偏。
判断一个环节要不要清洗，问的是「这一步是估计还是打分」。

## 不是所有检测器都需要清洗

IQR / MAD / ZScore 用的是中位数与分位数，对离群点**本身就不敏感**，
预过滤是多余的；更糟的是，预过滤会低估尺度，反而造成误报。

真正需要清洗的是那些**最小二乘 / 频域**环节：

- 周期估计（FFT / ACF）：单个离群点能主导自相关（实测 0.824 → 0.08）
- STL 分解：拟合曲线会被尖峰拉偏
- 线性趋势拟合：斜率被尖峰带偏

## 截尾而不是剔除

相位分组靠下标取模定位，**删点会让相位整体错位**。所以默认用
截尾（winsorize）——保持点数与时间轴不变，只把极端值的幅度拉回来。
真要剔除（`outlier_mask`）只用在不依赖时间轴的估计上。
"""

from __future__ import annotations

import numpy as np

#: 离群点判定倍数（相对稳健尺度 `median ± k·1.4826·MAD`）
DEFAULT_OUTLIER_K = 5.0


def robust_scale(values: np.ndarray) -> float:
    """稳健尺度：1.4826·MAD，退化时用标准差。"""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return 0.0
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = mad * 1.4826
    if scale > 0:
        return scale
    return float(np.std(values))


def outlier_mask(
    values: np.ndarray, k: float = DEFAULT_OUTLIER_K
) -> np.ndarray:
    """标出离群点（布尔掩码）。

    只用于**不依赖时间轴**的估计——删点会破坏相位结构。
    """
    values = np.asarray(values, dtype=float)
    scale = robust_scale(values)
    if scale <= 0:
        return np.zeros(values.shape, dtype=bool)
    median = float(np.median(values))
    return np.abs(values - median) > k * scale


def winsorize(
    values: np.ndarray, k: float = DEFAULT_OUTLIER_K
) -> np.ndarray:
    """把离群值截到「中位数 ± k·稳健尺度」的边界。

    保持点数与时间轴不变——这点很关键：相位分组靠下标取模定位，
    删点会让相位整体错位。
    """
    values = np.asarray(values, dtype=float)
    if values.size < 8:
        return values
    scale = robust_scale(values)
    if scale <= 0:
        return values
    median = float(np.median(values))
    low = median - k * scale
    high = median + k * scale
    if high <= low:
        return values
    return np.clip(values, low, high)
