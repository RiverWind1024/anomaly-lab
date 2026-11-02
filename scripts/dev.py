#!/usr/bin/env python
"""dev 模式：同时起 vite 与后端，任一挂了就一起收摊。

为什么不用 Makefile 的 shell 编排：那里踩过两个坑，而且信息混乱 ——
端口被占时 uvicorn 只说 `Errno 98`，vite 会**静默换到下一个端口**
（输出里的地址与实际访问的不一致），vite 挂了后端还照常起。

这个脚本把三件事做对：

- **端口预检**（IPv4 + IPv6 都试）—— 被占时说清是谁占的、怎么换
- **cwd 精确** —— vite 在 `frontend/`，后端在仓库根。
  `CONFIG.data_dir = Path("data")` 是相对 cwd 的，弄错会去读 `frontend/data/`
- **一起收摊** —— 任一子进程退出，另一个立刻被收掉；
  Ctrl-C 时杀**整个进程组**（只 kill 直接子进程会留下 node 的孙进程）

用法：
    python scripts/dev.py
    PORT=8001 VITE_PORT=5174 python scripts/dev.py
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

#: 后端解释器 —— 优先用项目 venv，避免用系统 python 跑（依赖可能没装）
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

BACKEND_PORT = int(os.environ.get("PORT", "8000"))
VITE_PORT = int(os.environ.get("VITE_PORT", "5173"))

#: vite 起来后要等多久（秒）
VITE_READY_TIMEOUT = 30

#: 假远端（mock-tsdb）的端口 —— 只在 `MOCK_TSDB=1` 时启用。
MOCK_PORT = int(os.environ.get("MOCK_PORT", "8181"))

#: 要不要一起起假远端。
#:
#: ⚠️ **默认关** —— 8181 是 InfluxDB 3 的默认端口，
#:    万一用户本机跑着真库，不该被我们占掉。
MOCK_ENABLED = os.environ.get("MOCK_TSDB", "").strip() not in {"", "0", "false"}


def port_busy(port: int) -> bool:
    """端口能不能绑定。

    ⚠️ **IPv4 和 IPv6 都要试** —— vite 默认绑 `[::1]`（IPv6 loopback only），
    只试 127.0.0.1 会误判成「空闲」。
    """
    for family, address in (
        (socket.AF_INET, ("127.0.0.1", port)),
        (socket.AF_INET6, ("::1", port)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(address)
            except OSError:
                return True
    return False


def wait_for_port(port: int, timeout: float) -> bool:
    """等端口被监听起来。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_busy(port):
            return True
        time.sleep(0.2)
    return False


def find_pid(port: int) -> int | None:
    """从 /proc 找出占用端口的进程 pid（拿不到就返回 None）。"""
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    inodes: set[str] = set()
    for name in ("tcp", "tcp6"):
        path = proc / "net" / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10 or parts[3] != "0A":  # 0A = LISTEN
                continue
            try:
                local_port = int(parts[1].split(":")[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port:
                inodes.add(parts[9])
    if not inodes:
        return None
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for fd in (entry / "fd").iterdir():
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return int(entry.name)
        except OSError:
            continue
    return None


def preflight() -> bool:
    """端口预检 —— 被占时给出人话提示。"""
    wanted = [(BACKEND_PORT, "后端", "PORT"), (VITE_PORT, "前端", "VITE_PORT")]
    if MOCK_ENABLED:
        wanted.append((MOCK_PORT, "假远端", "MOCK_PORT"))
    busy = [(port, name) for port, name, _ in wanted if port_busy(port)]
    if not busy:
        return True
    print("✗ 端口被占用：\n", file=sys.stderr)
    for port, name in busy:
        pid = find_pid(port)
        owner = f"（占用进程 pid {pid}）" if pid else ""
        print(f"    {port} —— {name} {owner}", file=sys.stderr)
    print("\n  换端口启动：", file=sys.stderr)
    for port, name in busy:
        # 只提示**实际冲突**的那个变量 —— 改无关的端口是噪声
        variable = next(v for p, n, v in wanted if p == port)
        print(f"      {variable}={port + 1} make dev", file=sys.stderr)
    print("\n  或杀掉占用进程后重试：", file=sys.stderr)
    for port, _name in busy:
        pid = find_pid(port)
        if pid:
            print(f"      kill {pid}", file=sys.stderr)
    return False


def main() -> int:
    if not preflight():
        return 1

    env = dict(os.environ)
    env["API_TARGET"] = f"http://127.0.0.1:{BACKEND_PORT}"

    print(f"▶ 前端 vite  → http://127.0.0.1:{VITE_PORT}/", file=sys.stderr)
    print(f"▶ 后端 API   → http://127.0.0.1:{BACKEND_PORT}/", file=sys.stderr)
    if MOCK_ENABLED:
        print(f"▶ 假远端     → http://127.0.0.1:{MOCK_PORT}/api/v3/query_sql", file=sys.stderr)
    print("  Ctrl-C 一起停\n", file=sys.stderr)

    # start_new_session=True → 两个进程各自成组，收摊时能整组杀
    #
    # ⚠️ `--host 127.0.0.1`：vite 默认绑 `[::1]`（IPv6 only），
    #    那样 `127.0.0.1:5173` 连不上 —— 后端的 API 代理也是走 127.0.0.1，
    #    两边统一 IPv4 才不绕。
    vite = subprocess.Popen(
        [
            "npm", "run", "dev", "--",
            "--port", str(VITE_PORT),
            "--strictPort",
            "--host", "127.0.0.1",
        ],
        cwd=FRONTEND,
        env=env,
        start_new_session=True,
    )
    backend_python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    backend = subprocess.Popen(
        [backend_python, "-m", "anomaly_lab.cli", "serve", "--port", str(BACKEND_PORT)],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )

    # 假远端：独立进程 —— 它扮演的是「远端」，跑在平台进程里就不真了。
    mock = None
    if MOCK_ENABLED:
        mock = subprocess.Popen(
            [
                backend_python,
                "-m",
                "anomaly_lab.cli",
                "mock-tsdb",
                "--port",
                str(MOCK_PORT),
                "--db-path",
                str(ROOT / "data" / "mock_tsdb" / "tsdb.db"),
            ],
            cwd=ROOT,
            env=env,
            start_new_session=True,
        )

    def shutdown(_signum=None, _frame=None) -> None:
        for proc in (vite, backend, mock):
            if proc is None:
                continue
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    proc.terminate()
        print("\n已停止", file=sys.stderr)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # vite 就绪前先等一下 —— 它要是起不来（端口被占/依赖缺失），
    # 就别让后端在那儿空转
    if not wait_for_port(VITE_PORT, VITE_READY_TIMEOUT) and vite.poll() is not None:
        print("✗ 前端 vite 启动失败（见上方输出）", file=sys.stderr)
        shutdown()
        return 1

    # 谁先退出就收摊
    while True:
        children = [("前端 vite", vite), ("后端", backend)]
        if mock is not None:
            children.append(("假远端", mock))
        for name, proc in children:
            code = proc.poll()
            if code is not None:
                print(f"\n✗ {name} 已退出（code {code}），一并停止另一个", file=sys.stderr)
                shutdown()
                return code or 1
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
