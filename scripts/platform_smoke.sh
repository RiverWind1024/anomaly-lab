#!/usr/bin/env bash
# 平台垂直切片冒烟：SQLite 源 → 指标 → 任务 → 执行 → 预览数据
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
DATA_ROOT=${1:-data/platform_smoke}
rm -rf "$DATA_ROOT"

$PY -m anomaly_lab.cli platform-demo --data "$DATA_ROOT"

$PY - "$DATA_ROOT" <<'PY'
import sys
from pathlib import Path

from anomaly_lab.platform.runner import execute_job
from anomaly_lab.platform.store import PlatformStore

root = Path(sys.argv[1])
store = PlatformStore(root / "platform.db")
job = store.list_jobs()[0]
run_id = execute_job(store, job.id, data_root=root)
run = store.get_run(run_id)
assert run.status == "success", run
assert run.n_series == 2, run
assert run.n_alerts > 0, run
print(f"PLATFORM SMOKE OK: run={run_id} series={run.n_series} alerts={run.n_alerts}")
PY
