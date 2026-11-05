PY := .venv/bin/python
PIP := uv pip
PIP_INDEX ?= https://pypi.tuna.tsinghua.edu.cn/simple
NPM ?= npm

.PHONY: setup test lint generate classify detect evaluate compare report validate-auto serve smoke platform-demo platform-smoke compliance-check clean \
	frontend-install frontend-test frontend-build dev mock-tsdb mock-demo prune \
	sync-detections

setup:
	uv python install 3.12
	uv venv --python 3.12
	$(PIP) install -e ".[dev]" --index-url $(PIP_INDEX)

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check scripts src tests

generate:
	$(PY) -m anomaly_lab.cli generate --n 120 --seed 42

classify:
	$(PY) -m anomaly_lab.cli classify --eval

detect:
	$(PY) -m anomaly_lab.cli detect --detector iqr

evaluate:
	$(PY) -m anomaly_lab.cli evaluate --report reports/latest

compare:
	$(PY) -m anomaly_lab.cli compare

report:
	$(PY) -m anomaly_lab.cli report --out reports/summary.md

validate-auto:
	$(PY) -m anomaly_lab.cli validate-auto --source nab

# ---------- 前端 ----------

frontend-install:
	cd frontend && $(NPM) ci

frontend-test:
	cd frontend && $(NPM) run test

frontend-build:
	cd frontend && $(NPM) run build

# dev：vite 与 uvicorn 两个进程并行。
#
# 编排交给 scripts/dev.py（不是 shell）—— shell 那套踩过三个坑：
#   1. vite 必须在**子 shell** 里 cd —— 否则 cwd 停在 frontend/，
#      而 CONFIG.data_dir = Path("data") 是相对 cwd 的，会去读 frontend/data/。
#   2. `&` 起的后台任务要**杀整个进程组** —— 只 kill $! 杀的是 npm 的 wrapper，
#      真正的 node vite 子进程会活下来占着 5173。
#   3. 端口被占时 uvicorn 只说 `Errno 98`；vite 还会**静默换到下一个端口**，
#      输出里的地址与实际访问的不一致。
#
# 端口可覆盖：`PORT=8001 VITE_PORT=5174 make dev`
PORT ?= 8000
VITE_PORT ?= 5173

dev:
	@PORT=$(PORT) VITE_PORT=$(VITE_PORT) $(PY) scripts/dev.py

serve: frontend-build
	$(PY) -m anomaly_lab.cli serve --port $(PORT)

platform-demo:
	$(PY) -m anomaly_lab.cli platform-demo --data data

# ---------- 假远端（演示用） ----------

# 假远端时序数据库：照 InfluxDB 3 的 API 形状，持续造数。
# 跑它是为了让「HTTP 透传」有一条真的远端可连（换 url + token 也能接真库）。
mock-tsdb:
	$(PY) -m anomaly_lab.cli mock-tsdb

# 把平台侧配成指向假远端（HTTP 数据源 + 指标 + 检测任务）。
mock-demo:
	$(PY) -m anomaly_lab.cli mock-demo --data data

smoke:
	./scripts/smoke.sh

platform-smoke:
	./scripts/platform_smoke.sh

# 清理超出保留窗口的运行记录与检测结果文件。
#
# ⚠️ 调度器本来就会每小时自动清一次 —— 这个是手动入口（先看会删什么用 --dry-run）。
prune:
	$(PY) -m anomaly_lab.cli prune --data data

# 把产物目录里的检测结果补录进数据库（幂等）。
#
# ⚠️ 老库升级后需要跑一次 —— 检测记录现在落库了，
#    之前产生的运行只在磁盘上有产物。
sync-detections:
	$(PY) -m anomaly_lab.cli sync-detections --data data

compliance-check:
	$(PY) -m anomaly_lab.cli compliance-check

clean:
	rm -rf .pytest_cache .ruff_cache reports data/synthetic data/cache data/platform data/platform.db data/platform_smoke
	find . -name __pycache__ -type d -exec rm -rf {} +
