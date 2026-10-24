PY ?= python3

.PHONY: install demo demo-bay demo-live test lint typecheck check format sql smoke redis kernel-sql smt-bench smt-invariants

install:
	$(PY) -m pip install -r requirements-dev.txt

demo:
	RESILIMES_MODE=mock RESILIMES_FAB=smt2020 $(PY) -m resilimes serve --host 0.0.0.0 --port 8000

demo-bay:
	RESILIMES_MODE=mock RESILIMES_FAB=sample $(PY) -m resilimes serve --host 0.0.0.0 --port 8000

demo-live:
	RESILIMES_MODE=auto RESILIMES_FAB=smt2020 $(PY) -m resilimes serve --host 0.0.0.0 --port 8000

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

typecheck:
	$(PY) -m mypy

check: lint typecheck test

format:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

sql:
	$(PY) scripts/export_zetaris_sql.py

smoke:
	RESILIMES_MODE=mock $(PY) smoke_test.py --mock

redis:
	docker compose up -d redis

kernel-sql:
	$(PY) -m resilimes.data.smt2020_kernel

smt-bench:
	$(PY) -m resilimes.smt.benchmark

smt-invariants:
	$(PY) -m resilimes.smt.invariant_sweep
