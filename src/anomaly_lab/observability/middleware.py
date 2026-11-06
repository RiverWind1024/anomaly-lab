"""HTTP 请求的埋点中间件。

⚠️ 用**纯 ASGI** 中间件，不用 `BaseHTTPMiddleware`：
   后者会多包一层 anyio TaskGroup，改变异常传播与 `scope` 的可见性，
   而我们只需要「进来加一、出去减一、记个耗时」。
"""

from __future__ import annotations

import time
from typing import Any

from anomaly_lab.observability import get_observability


def _route_label(scope: dict[str, Any]) -> str:
    """路由模板（如 `/api/platform/jobs/{job_id}`），不是真实 URL。

    ⚠️ 用真实 URL 会把 `job_id` 当标签维度 —— 几百个任务就是几百条时间序列，
       监控页会被自己的基数拖垮。匹配不到路由（404）时统一记 `<unmatched>`。
    """
    route = scope.get("route")
    path = getattr(route, "path", None) if route is not None else None
    return str(path) if path else "<unmatched>"


class ObservabilityMiddleware:
    """记录请求数、状态码、耗时与进行中请求数。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        obs = get_observability()
        method = str(scope.get("method", ""))
        obs.inflight_add(1.0)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            route = _route_label(scope)
            obs.inflight_add(-1.0)
            obs.inc("http.requests", method=method, route=route, status=str(status))
            obs.observe_ms("http.request_ms", elapsed_ms, method=method, route=route)
            if status >= 500:
                obs.inc("http.errors", method=method, route=route, status=str(status))
