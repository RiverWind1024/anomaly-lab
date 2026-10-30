PY := .venv/bin/python
PIP := uv pip
PIP_INDEX ?= https://pypi.tuna.tsinghua.edu.cn/simple
NPM ?= npm

.PHONY: setup test lint generate classify detect evaluate compare report validate-auto serve smoke platform-demo platform-smoke compliance-check clean \
	frontend-install frontend-test frontend-build dev

setup:
	uv python install 3.12
	uv venv --python 3.12
	$(PIP) install -e ".[dev]" --index-url $(PIP_INDEX)

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests

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
# ⚠️ 两个坑：
#  1. vite 必须在**子 shell** 里 cd —— 否则外层 shell 的 cwd 停在 frontend/，
#     而 CONFIG.data_dir = Path("data") 是相对 cwd 的，服务器会去读 frontend/data/。
#  2. `&` 起的后台任务要**杀整个进程组** —— 只 kill $! 杀的是 npm 的 wrapper，
#     真正的 node vite 子进程会活下来占着 5173 端口。
#     `set -m` 让后台任务自成一个进程组，然后 `kill -- -$$VPID` 整组收掉。
dev:
	@set -m; \
	(cd frontend && $(NPM) run dev -- --port 5173) & \
	VPID=$$!; \
	trap 'kill -- -$$VPID 2>/dev/null || true' EXIT INT TERM; \
	$(PY) -m anomaly_lab.cli serve --port 8000

serve: frontend-build
	$(PY) -m anomaly_lab.cli serve --port 8000

platform-demo:
	$(PY) -m anomaly_lab.cli platform-demo --data data

smoke:
	./scripts/smoke.sh

platform-smoke:
	./scripts/platform_smoke.sh

compliance-check:
	$(PY) -m anomaly_lab.cli compliance-check

clean:
	rm -rf .pytest_cache .ruff_cache reports data/synthetic data/cache data/platform data/platform.db data/platform_smoke
	find . -name __pycache__ -type d -exec rm -rf {} +
