##
## GCP-Drone-Comms-Unit Workspace — Developer Makefile
##
## Usage:
##   make <target>
##
## All targets are PHONY. Configuration via environment variables (no hardcoded paths).
##

# ── Configuration variables ──────────────────────────────────────────────────
PNPM            := pnpm
NODE            := node
API_FILTER      := --filter @workspace/api-server
SANDBOX_FILTER  := --filter @workspace/mockup-sandbox
COVERAGE_DIR    := coverage
DIST_DIR        := dist

# Colour helpers (degrade gracefully if tput is unavailable)
_BOLD   := $(shell tput bold 2>/dev/null || echo '')
_GREEN  := $(shell tput setaf 2 2>/dev/null || echo '')
_YELLOW := $(shell tput setaf 3 2>/dev/null || echo '')
_RED    := $(shell tput setaf 1 2>/dev/null || echo '')
_RESET  := $(shell tput sgr0 2>/dev/null || echo '')

define log_step
	@echo "$(_BOLD)$(_GREEN)==> $(1)$(_RESET)"
endef

define log_warn
	@echo "$(_BOLD)$(_YELLOW)⚠  $(1)$(_RESET)"
endef

# ── Default target ────────────────────────────────────────────────────────────
.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*##"}; {printf "  $(_BOLD)%-18s$(_RESET) %s\n", $$1, $$2}' \
	  | sort

# ── Development ───────────────────────────────────────────────────────────────
.PHONY: dev
dev: ## Start all services in parallel (API + sandbox)
	$(call log_step,Starting development servers)
	$(PNPM) $(API_FILTER) run dev & $(PNPM) $(SANDBOX_FILTER) run dev

.PHONY: dev-api
dev-api: ## Start API server only
	$(PNPM) $(API_FILTER) run dev

.PHONY: dev-sandbox
dev-sandbox: ## Start mockup sandbox only
	$(PNPM) $(SANDBOX_FILTER) run dev

# ── Build ─────────────────────────────────────────────────────────────────────
.PHONY: build
build: ## Build all packages for production
	$(call log_step,Building all packages)
	$(PNPM) -r run build

.PHONY: build-api
build-api: ## Build API server only
	$(PNPM) $(API_FILTER) run build

# ── Type checking ─────────────────────────────────────────────────────────────
.PHONY: typecheck
typecheck: ## Run TypeScript strict type checking across all packages
	$(call log_step,TypeScript type checking)
	@# lib/api-zod and lib/db are TS composite project references (emitDeclarationOnly);
	@# their gitignored dist/ .d.ts output must exist before dependents can typecheck
	@# against them via "references" -- build them first, on every fresh clone.
	$(PNPM) --filter './lib/*' run build
	$(PNPM) -r run typecheck
	@echo "$(_GREEN)✔  Type checking passed$(_RESET)"

# ── Linting ───────────────────────────────────────────────────────────────────
.PHONY: lint
lint: ## Run ESLint (warnings treated as errors)
	$(call log_step,ESLint)
	$(PNPM) -r run lint 2>&1 | tee /tmp/eslint-output.txt; \
	  STATUS=$${PIPESTATUS[0]}; \
	  if [ $$STATUS -ne 0 ]; then \
	    echo "$(_RED)✘  Lint failed$(_RESET)"; exit $$STATUS; \
	  fi
	@echo "$(_GREEN)✔  Lint passed$(_RESET)"

.PHONY: lint-fix
lint-fix: ## Run ESLint and auto-fix fixable issues
	$(PNPM) -r run lint:fix

.PHONY: format
format: ## Run Prettier formatter
	$(PNPM) -r run format 2>/dev/null || $(call log_warn,No format script found — skipping)

# ── Testing ───────────────────────────────────────────────────────────────────
.PHONY: test
test: ## Run full test suite (unit + integration)
	$(call log_step,Running tests)
	$(PNPM) -r run test
	@echo "$(_GREEN)✔  All tests passed$(_RESET)"

.PHONY: test-watch
test-watch: ## Run tests in watch mode (API server)
	$(PNPM) $(API_FILTER) run test:watch

.PHONY: coverage
coverage: ## Run tests with coverage report
	$(call log_step,Coverage report)
	$(PNPM) $(API_FILTER) run test:coverage
	@echo "Coverage report written to artifacts/api-server/$(COVERAGE_DIR)/"

# ── Secret scanning ───────────────────────────────────────────────────────────
.PHONY: secrets-check
secrets-check: ## Scan for leaked secrets with gitleaks
	$(call log_step,Secret scanning (gitleaks))
	@if command -v gitleaks >/dev/null 2>&1; then \
	  gitleaks detect --config .gitleaks.toml --source . --no-banner; \
	  echo "$(_GREEN)✔  No secrets found$(_RESET)"; \
	else \
	  $(call log_warn,gitleaks not installed — skipping. Install: brew install gitleaks); \
	fi

# ── Validation gate (pre-PR) ──────────────────────────────────────────────────
.PHONY: validate
validate: typecheck lint test build secrets-check ## Run full pre-PR validation gate
	@echo ""
	@echo "$(_BOLD)$(_GREEN)════════════════════════════════════════$(_RESET)"
	@echo "$(_BOLD)$(_GREEN)  ✔  All validations passed             $(_RESET)"
	@echo "$(_BOLD)$(_GREEN)════════════════════════════════════════$(_RESET)"

# ── Installation & setup ──────────────────────────────────────────────────────
.PHONY: install
install: ## Install all dependencies
	$(call log_step,Installing dependencies)
	$(PNPM) install

.PHONY: hooks-install
hooks-install: ## Install git hooks (run once after cloning)
	$(call log_step,Installing git hooks)
	@if [ -f scripts/hooks/install-hooks.sh ]; then \
	  bash scripts/hooks/install-hooks.sh; \
	  echo "$(_GREEN)✔  Git hooks installed$(_RESET)"; \
	else \
	  $(call log_warn,scripts/hooks/install-hooks.sh not found — skipping); \
	fi

.PHONY: setup
setup: install hooks-install ## Full first-time setup (install + hooks)
	@echo "$(_GREEN)✔  Workspace setup complete$(_RESET)"

# ── Database ──────────────────────────────────────────────────────────────────
.PHONY: db-push
db-push: ## Push Drizzle schema to database (development)
	$(PNPM) --filter @workspace/db run push

.PHONY: db-migrate
db-migrate: ## Run pending Drizzle migrations
	$(PNPM) --filter @workspace/db run migrate

.PHONY: db-studio
db-studio: ## Open Drizzle Studio (database browser)
	$(PNPM) --filter @workspace/db run studio

# ── Cleaning ──────────────────────────────────────────────────────────────────
.PHONY: clean
clean: ## Remove build artefacts (dist/, .tsbuildinfo, coverage/)
	$(call log_step,Cleaning build artefacts)
	find . -name "$(DIST_DIR)" -type d \
	  -not -path "*/node_modules/*" \
	  -not -path "*/.git/*" \
	  -exec rm -rf {} + 2>/dev/null || true
	find . -name ".tsbuildinfo" \
	  -not -path "*/node_modules/*" \
	  -delete 2>/dev/null || true
	find . -name "$(COVERAGE_DIR)" -type d \
	  -not -path "*/node_modules/*" \
	  -exec rm -rf {} + 2>/dev/null || true
	find . -name ".vitest-cache" -type d \
	  -not -path "*/node_modules/*" \
	  -exec rm -rf {} + 2>/dev/null || true
	@echo "$(_GREEN)✔  Clean complete$(_RESET)"

.PHONY: clean-all
clean-all: clean ## Also remove node_modules (full reset)
	$(call log_warn,Removing node_modules — run 'make install' afterwards)
	rm -rf node_modules
	find . -name "node_modules" -type d \
	  -not -path "*/.git/*" \
	  -exec rm -rf {} + 2>/dev/null || true

# ── Python deliverables ───────────────────────────────────────────────────────
.PHONY: py-check
py-check: ## Syntax-check Python deliverable files (requires Python)
	$(call log_step,Python syntax check)
	@if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then \
	  PY=$$(command -v python3 || command -v python); \
	  find deliverables -name "*.py" -exec $$PY -m py_compile {} \; && \
	  echo "$(_GREEN)✔  Python syntax OK$(_RESET)"; \
	else \
	  $(call log_warn,Python not found — skipping py-check); \
	fi

# ── CI convenience ────────────────────────────────────────────────────────────
.PHONY: ci
ci: install validate ## Full CI run (install + validate)

# ── Introspection ─────────────────────────────────────────────────────────────
.PHONY: list-packages
list-packages: ## List all workspace packages
	$(PNPM) -r list --depth 0

.PHONY: outdated
outdated: ## Check for outdated dependencies
	$(PNPM) outdated -r
