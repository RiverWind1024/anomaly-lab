"""假远端的 HTTP 服务：照抄 InfluxDB 3 的 `query_sql` 端点。

⚠️ **为什么照抄而不是自创格式** —— 照抄之后，换 url + token 就能接真 InfluxDB 3。
   抄的是**接口形状**（端点路径、请求体字段、format 取值），
   不是它内部的查询引擎。

⚠️ **不实现鉴权** —— 但**接受并忽略** `Authorization` 头。
   真库的鉴权是连接器 `config.headers` 的事，平台侧已经做完了。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from anomaly_lab.mock_tsdb.generator import DEFAULT_RETENTION_HOURS, SAMPLE_SECONDS
from anomaly_lab.mock_tsdb.tsdb import MockTsdb

logger = logging.getLogger(__name__)

#: 支持的响应格式 —— 与平台 `validate_http_config` 的取值一致。
SUPPORTED_FORMATS = ("csv", "json", "jsonl")

#: InfluxDB 3 有但我们不实现的格式 —— 明确报错，不静默降级。
UNSUPPORTED_FORMATS = ("pretty", "parquet")


@dataclass
class MockConfig:
    """假远端的配置。"""

    db_path: Path
    #: 保留窗口（小时）。
    retention_hours: int = DEFAULT_RETENTION_HOURS
    #: 采样间隔（秒）—— 决定数据的密度。
    sample_seconds: int = SAMPLE_SECONDS
    #: 启动时回填多少个**历史**点。
    history_points: int = 360
    #: 后台线程的写入间隔（秒）。
    write_interval_seconds: int = 10
    #: 后台线程是否自动启动。
    autostart: bool = True
    #: 造数用的库名（仅用于日志与响应，不是真的多库）。
    db_name: str = "mock"
    #: 停止信号 —— 后台线程看它退出。
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    #: 后台线程。
    thread: threading.Thread | None = field(default=None, repr=False)
    #: ⚠️ **后台写入失败的原因** —— 记下来而不只是打日志。
    #:    只打日志的话，测试根本发现不了「数据其实一直没在动」。
    write_errors: list[str] = field(default_factory=list, repr=False)

    def stop(self) -> None:
        self.stop_event.set()


def _csv_response(columns: list[str], rows: list[tuple]) -> Response:
    """CSV 响应（**带表头行**）。

    ⚠️ 表头是必须的 —— 平台用 `pd.read_csv` 解析，没有表头会把
       第一行数据当列名。
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        # ⚠️ None → 空字符串 —— CSV 没有 NULL。
        #    平台的 `pd.read_csv` 把空值读成 NaN → 正好是「值缺失」。
        writer.writerow(["" if value is None else value for value in row])
    return Response(buffer.getvalue(), media_type="text/csv")


def _json_response(columns: list[str], rows: list[tuple]) -> Response:
    """JSON 响应（**对象数组**）。

    ⚠️ 不是 InfluxDB 3 的两段式（`results[].series[]`）——
       那个形状平台的 `rows_path` 够不着（spec 1 已定）。
       CSV 才是接 InfluxDB 3 的正路，JSON 是给平台用的便利格式。
    """
    records = [dict(zip(columns, row, strict=False)) for row in rows]
    return JSONResponse(records)


def _jsonl_response(columns: list[str], rows: list[tuple]) -> Response:
    """JSONL 响应（每行一个对象）。"""
    lines = [
        json.dumps(dict(zip(columns, row, strict=False)), ensure_ascii=False)
        for row in rows
    ]
    return Response("\n".join(lines), media_type="application/jsonl")


def _error(status: int, code: str, message: str) -> JSONResponse:
    """错误响应 —— 形状照抄 InfluxDB 3 的 `ErrorMessage`。"""
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def create_app(config: MockConfig) -> FastAPI:
    """假远端的 FastAPI 应用。"""
    store = MockTsdb(config.db_path, sample_seconds=config.sample_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.open(history_points=config.history_points)
        # ⚠️ 一次把「锚点 → 现在」的点全写出来 ——
        #    锚点在过去，所以回填的数据落在过去（而不是未来）。
        written = store.produce_until(datetime.now(UTC))
        logger.info(
            "假远端已启动：库=%s 回填=%d 行 锚点=%s",
            config.db_path,
            written,
            store.anchor.isoformat(),
        )
        if config.autostart:
            thread = threading.Thread(
                target=_writer_loop, args=(store, config), daemon=True, name="mock-writer"
            )
            thread.start()
            config.thread = thread
        yield
        config.stop()
        store.close()

    app = FastAPI(title="mock-tsdb", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store = store
    app.state.config = config

    @app.post("/api/v3/query_sql")
    async def query_sql(request: Request) -> Response:
        """执行 SQL 并返回结果集。

        ⚠️ **入参形状照抄 InfluxDB 3**：体 `{db, q, format}`。
           `db` 与 `q` 都必填。
        """
        return await _handle_query(request, store)

    @app.get("/api/v3/query_sql")
    async def query_sql_get(request: Request) -> Response:
        """GET 版本 —— InfluxDB 3 也支持（参数在 query string）。"""
        return await _handle_query(request, store)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "db": str(config.db_path)}

    return app


async def _handle_query(request: Request, store: MockTsdb) -> Response:
    """`query_sql` 的共同处理（GET 与 POST）。"""
    if request.method == "POST":
        try:
            payload = json.loads(await request.body())
        except (ValueError, UnicodeDecodeError):
            return _error(400, "invalid", "请求体不是合法 JSON")
        if not isinstance(payload, dict):
            return _error(400, "invalid", "请求体必须是 JSON 对象")
        query = payload.get("q")
        db_name = payload.get("db")
        fmt = payload.get("format", "json")
    else:
        params = request.query_params
        query = params.get("q")
        db_name = params.get("db")
        fmt = params.get("format", "json")

    if not query or not str(query).strip():
        return _error(400, "invalid", "缺少查询语句 q")
    if not db_name or not str(db_name).strip():
        return _error(400, "invalid", "缺少数据库名 db")

    fmt = str(fmt).lower()
    if fmt in UNSUPPORTED_FORMATS:
        return _error(
            400,
            "invalid",
            f"不支持的 format={fmt!r}（本服务实现 {', '.join(SUPPORTED_FORMATS)}）",
        )
    if fmt not in SUPPORTED_FORMATS:
        return _error(
            400, "invalid", f"不支持的 format={fmt!r}（可选 {', '.join(SUPPORTED_FORMATS)}）"
        )

    try:
        columns, rows = store.query(str(query))
    except ValueError as exc:
        # ⚠️ 只读校验拦下的（写操作 / 多语句 / 非 SELECT）
        return _error(400, "invalid", str(exc))
    except Exception as exc:
        logger.exception("查询失败")
        return _error(500, "internal error", f"{type(exc).__name__}: {exc}")

    if fmt == "csv":
        return _csv_response(columns, rows)
    if fmt == "jsonl":
        return _jsonl_response(columns, rows)
    return _json_response(columns, rows)


def _writer_loop(store: MockTsdb, config: MockConfig) -> None:
    """后台线程：持续写入新点 + 滚动删旧。"""
    while not config.stop_event.is_set():
        try:
            written = store.produce_until(datetime.now(UTC))
            if written:
                logger.info("写入 %d 个新点", written)
            store.prune(config.retention_hours)
        except Exception as exc:
            # ⚠️ **记下来** —— 只打日志的话，「数据一直没在动」
            #    这类故障会静悄悄地溜过去。
            config.write_errors.append(f"{type(exc).__name__}: {exc}")
            logger.exception("后台写入失败")
        config.stop_event.wait(config.write_interval_seconds)


def serve(config: MockConfig, host: str = "127.0.0.1", port: int = 8181) -> None:
    """启动服务（阻塞）。"""
    import uvicorn

    uvicorn.run(create_app(config), host=host, port=port, log_level="info")


def wait_until_ready(host: str, port: int, timeout: float = 10.0) -> bool:
    """等端口起来（给测试与脚本用）。"""
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False
