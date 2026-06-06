# GCP-Drone-Comms-Unit developer shortcuts.
# Run from the repo root.

PKG := packages/meshsa
PY  ?= python

.PHONY: help install dev test lint format type build docker clean

help:
	@echo "Targets:"
	@echo "  install   - editable install of meshsa"
	@echo "  dev       - editable install with [dev,meshtastic] extras + pre-commit"
	@echo "  test      - run pytest in $(PKG)"
	@echo "  lint      - ruff check"
	@echo "  format    - ruff format (write)"
	@echo "  type      - mypy on the package source"
	@echo "  build     - build sdist + wheel"
	@echo "  docker    - build the runtime container"
	@echo "  clean     - remove build, dist, caches"

install:
	$(PY) -m pip install -e $(PKG)

dev:
	$(PY) -m pip install -e "$(PKG)[dev,meshtastic]"
	pre-commit install

test:
	cd $(PKG) && $(PY) -m pytest

lint:
	ruff check $(PKG)

format:
	ruff format $(PKG)

type:
	cd $(PKG) && mypy src

build:
	cd $(PKG) && $(PY) -m build

docker:
	docker build -f tools/Dockerfile -t meshsa-base:latest .

clean:
	rm -rf $(PKG)/build $(PKG)/dist $(PKG)/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
