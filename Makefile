##
## GCP-Drone-Comms-Unit — root Makefile (TypeScript workspace side)
##
## `scripts/validate-pre-pr.sh` is the one truth for the pre-PR gate; this file is a thin
## set of aliases for its TypeScript steps (1-4) plus setup and cleanup. The Python side
## is `tools/Makefile` (`make -f tools/Makefile <target>`), and `make validate-pre-pr`
## runs both sides through the script. Plan P3-4 (docs/CODE_QUALITY_TECH_DEBT_PLAN.md)
## pruned the Replit-era targets (dev servers, db-push, py-check, outdated, ci).
##

PNPM := pnpm
API_FILTER := --filter @workspace/api-server

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*##"}; {printf "  %-18s %s\n", $$1, $$2}' \
	  | sort

# ── Setup ─────────────────────────────────────────────────────────────────────
.PHONY: install
install: ## Install workspace dependencies (pnpm, frozen lockfile)
	$(PNPM) install --frozen-lockfile

.PHONY: hooks-install
hooks-install: ## Install git hooks (run once after cloning)
	@if [ -f scripts/hooks/install-hooks.sh ]; then \
	  bash scripts/hooks/install-hooks.sh; \
	else \
	  echo "scripts/hooks/install-hooks.sh not found — skipping"; \
	fi

.PHONY: setup
setup: install hooks-install ## First-time setup (install + hooks)

# ── The TypeScript gate: steps 1-4 of scripts/validate-pre-pr.sh ──────────────
.PHONY: typecheck
typecheck: ## Step 1: build the composite libs, then type-check every workspace
	@# lib/api-zod and lib/db are TS composite projects (emitDeclarationOnly); their
	@# gitignored dist/ .d.ts output must exist before dependents resolve `references`.
	$(PNPM) --filter './lib/*' run build
	$(PNPM) -r run typecheck

.PHONY: lint
lint: ## Step 2: ESLint, warnings are errors
	$(PNPM) -r run lint

.PHONY: test
test: ## Step 3: vitest (api-server is the only workspace with a test script)
	$(PNPM) -r run test

.PHONY: build
build: ## Step 4: production bundle of api-server (esbuild)
	$(PNPM) $(API_FILTER) run build

.PHONY: validate
validate: typecheck lint test build ## TypeScript steps 1-4 only; `make validate-pre-pr` is the full gate

.PHONY: validate-pre-pr
validate-pre-pr: ## The full pre-PR gate: TS + Python + governance (scripts/validate-pre-pr.sh)
	bash scripts/validate-pre-pr.sh

# ── api-server conveniences ───────────────────────────────────────────────────
.PHONY: dev-api
dev-api: ## Run the API server locally (build + start)
	$(PNPM) $(API_FILTER) run dev

.PHONY: test-watch
test-watch: ## vitest in watch mode (api-server)
	$(PNPM) $(API_FILTER) run test:watch

.PHONY: coverage
coverage: ## vitest with coverage (api-server; report under artifacts/api-server/coverage/)
	$(PNPM) $(API_FILTER) run test:coverage

# ── Cleaning ──────────────────────────────────────────────────────────────────
.PHONY: clean
clean: ## Remove dist/, .tsbuildinfo, coverage/ and the vitest cache (both, or neither: see AGENTS.md)
	find . -name dist -type d -not -path "*/node_modules/*" -not -path "*/.git/*" -not -path "./archive/*" -exec rm -rf {} + 2>/dev/null || true
	find . \( -name ".tsbuildinfo" -o -name "tsconfig.tsbuildinfo" \) -not -path "*/node_modules/*" -delete 2>/dev/null || true
	find . -name coverage -type d -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null || true
	find . -name .vitest-cache -type d -not -path "*/node_modules/*" -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean-all
clean-all: clean ## Also remove every node_modules (run `make install` afterwards)
	find . -name node_modules -type d -not -path "*/.git/*" -prune -exec rm -rf {} + 2>/dev/null || true
