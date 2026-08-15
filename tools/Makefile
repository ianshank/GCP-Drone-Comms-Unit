# GCP-Drone-Comms-Unit developer shortcuts.
# Run from the repo root: `make -f tools/Makefile <target>`.

MESHSA := packages/meshsa
JETSON := packages/jetson_yolo_gcs
PY     ?= python

.PHONY: help install dev test lint format type build docker clean \
        test-jetson lint-jetson format-jetson type-jetson build-jetson \
        test-all lint-all type-all checkers

help:
	@echo "Targets (default package: meshsa):"
	@echo "  install      - editable install of meshsa"
	@echo "  dev          - editable install with [dev,meshtastic,ui] extras + pre-commit"
	@echo "  test         - run pytest in $(MESHSA)"
	@echo "  lint         - ruff check ($(MESHSA))"
	@echo "  format       - ruff format, write ($(MESHSA))"
	@echo "  type         - mypy on the package source ($(MESHSA))"
	@echo "  build        - build sdist + wheel ($(MESHSA))"
	@echo "  docker       - build the runtime container"
	@echo "  clean        - remove build, dist, caches (both packages)"
	@echo "  test-jetson  - run pytest in $(JETSON)"
	@echo "  lint-jetson  - ruff check ($(JETSON))"
	@echo "  format-jetson- ruff format, write ($(JETSON))"
	@echo "  type-jetson  - mypy on the package source ($(JETSON))"
	@echo "  build-jetson - build sdist + wheel ($(JETSON))"
	@echo "  test-all     - test + test-jetson"
	@echo "  lint-all     - lint + lint-jetson"
	@echo "  type-all     - type + type-jetson"
	@echo "  checkers     - run all deterministic governance checkers (bind_guard,"
	@echo "                 literal_guard, check_tool_pins, check_task_sync,"
	@echo "                 validate_workforce, validate_skills)"

install:
	$(PY) -m pip install -e $(MESHSA)

dev:
	$(PY) -m pip install -e "$(MESHSA)[dev,meshtastic,ui]"
	pre-commit install

test:
	cd $(MESHSA) && $(PY) -m pytest

lint:
	ruff check $(MESHSA)

format:
	ruff format $(MESHSA)

type:
	cd $(MESHSA) && mypy src

build:
	cd $(MESHSA) && $(PY) -m build

docker:
	docker build -f tools/Dockerfile -t meshsa-base:latest .

test-jetson:
	cd $(JETSON) && $(PY) -m pytest

lint-jetson:
	ruff check $(JETSON)

format-jetson:
	ruff format $(JETSON)

type-jetson:
	cd $(JETSON) && mypy src

build-jetson:
	cd $(JETSON) && $(PY) -m build

test-all: test test-jetson

lint-all: lint lint-jetson

type-all: type type-jetson

checkers:
	$(PY) tools/claude_hooks/bind_guard.py
	$(PY) tools/claude_hooks/literal_guard.py
	$(PY) tools/check_tool_pins.py
	$(PY) tools/check_task_sync.py
	$(PY) tools/validate_workforce.py
	$(PY) tools/validate_skills.py

clean:
	rm -rf $(MESHSA)/build $(MESHSA)/dist $(MESHSA)/*.egg-info
	rm -rf $(JETSON)/build $(JETSON)/dist $(JETSON)/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
