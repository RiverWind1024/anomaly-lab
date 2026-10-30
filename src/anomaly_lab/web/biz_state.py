"""业务态响应头。

「业务态」指**不是错误**的状态：还没有运行记录、还没有检测结果、
数据不足、窗口内没取到数据、没有可对比的算法。

后端在这些分支上返回 404，但额外带一个 `X-Anomaly-Biz-State` 响应头，
前端据此显示空态 / 警告，而不是红色错误框。

⚠️ JSON 结构一字未改 —— 老前端只看 `detail` 文案，完全不受影响。
"""

from __future__ import annotations

# 响应头名。前端 `src/api/client.ts` 里同名常量要同步。
BIZ_STATE_HEADER = "X-Anomaly-Biz-State"


def biz_headers(state: str) -> dict[str, str]:
    """构造带业务态标记的响应头。"""
    return {BIZ_STATE_HEADER: state}
