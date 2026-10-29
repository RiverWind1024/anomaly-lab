#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY -m anomaly_lab.cli generate --n 6 --seed 42 --out data/smoke
$PY -m anomaly_lab.cli classify --eval --data data/smoke
$PY -m anomaly_lab.cli detect --detector iqr --data data/smoke
$PY -m anomaly_lab.cli evaluate --data data/smoke --report reports/smoke
$PY -m anomaly_lab.cli report --out reports/smoke/summary.md
$PY -m anomaly_lab.cli compliance-check
echo "SMOKE OK"
