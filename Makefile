PYTHON ?= python
BACKEND ?= auto

.PHONY: install test validate lint format determinism

install:
	$(PYTHON) -m pip install -r requirements-dev.lock --require-hashes --no-deps
	$(PYTHON) -m pip install --no-deps -e .

test:
	$(PYTHON) -m pytest

validate:
	orderbench validate-all --backend $(BACKEND)

determinism:
	$(PYTHON) -m pytest harness_tests/test_determinism.py

lint:
	ruff check .
	ruff format --check .
	mypy

format:
	ruff check --fix .
	ruff format .
