PY := .venv/bin/python
PIP := uv pip

.PHONY: setup test lint generate classify detect evaluate compare report serve compliance-check clean

setup:
	uv python install 3.12
	uv venv --python 3.12
	$(PIP) install -e ".[dev]"

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

serve:
	$(PY) -m anomaly_lab.cli serve --port 8000

compliance-check:
	$(PY) -m anomaly_lab.cli compliance-check

clean:
	rm -rf .pytest_cache .ruff_cache reports data/synthetic data/cache
	find . -name __pycache__ -type d -exec rm -rf {} +
