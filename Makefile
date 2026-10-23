PY ?= python3

.PHONY: install demo demo-live test lint typecheck check format sql smoke

install:
	$(PY) -m pip install -r requirements-dev.txt

demo:
	RESILIMES_MODE=mock $(PY) -m resilimes serve --host 0.0.0.0 --port 8000

demo-live:
	RESILIMES_MODE=auto $(PY) -m resilimes serve --host 0.0.0.0 --port 8000

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
