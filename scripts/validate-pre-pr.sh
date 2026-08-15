#!/usr/bin/env bash
# scripts/validate-pre-pr.sh — full pre-PR validation gate
#
# Runs every check that must pass before a pull request is opened.
# Steps (in order, each must pass before the next runs):
#   1.  TypeScript type checking (all packages)
#   2.  ESLint (all packages, no warnings)
#   3.  Unit + integration tests (TS packages)
#   4.  Production build (api-server)
#   5.  Secret scan (gitleaks)
#   6.  Python linting (ruff) — packages/, flightctl/, tools/, deliverables/
#   7.  Python formatting check (ruff format --check) — same scope as #6
#   8.  Python type checking (mypy) — packages/meshsa, packages/jetson_yolo_gcs
#       (if present), flightctl/+tools/, deliverables/, each against its own
#       pyproject.toml/mypy.ini
#   9.  Python test suite (pytest) — packages/meshsa, and packages/jetson_yolo_gcs
#       if present (each package's own coverage-gated suite)
#   10. Governance hook tests (tools/claude_hooks/tests, tools/tests)
#   11. Bind guard — every listener routes through meshsa.netauth.validate_bind
#   12. Literal guard — service literals sourced from meshsa/defaults.py
#   13. Workforce roster lint (.claude/agents)
#   14. Skills playbook lint — .agents/skills/*/SKILL.md frontmatter, name-vs-dir
#       agreement, and cited repo-path existence (tools/validate_skills.py)
#   15. Tool-pin sync — pre-commit revs == pyproject ruff/mypy pins
#   16. Task-checkbox sync (advisory; warns, never fails the gate)
#   17. Skills trackable — .gitignore must not re-exclude .agents/skills/
#   18. Python syntax check (py_compile) — every *.py under packages/,
#       flightctl/, tools/, deliverables/ (not deliverables/ alone)
#
# Steps 10-17 are the T-2.2b governance gate.
#
# Usage:
#   bash scripts/validate-pre-pr.sh
#   # Or via Makefile:
#   make validate-pre-pr
#   # (root `make validate` only runs the TS steps above — 1-4 — not the Python
#   # or governance steps; use `make validate-pre-pr` for the full gate below.)
#
# Exit codes:
#   0  All checks passed
#   1  One or more checks failed (specific step shown in output)
#
# Python steps added in T-2.2 (code-hygiene-modularity); jetson_yolo_gcs test
# coverage (step 9) added 2026-07-31 — it was lint/type-checked but never
# actually pytest-run by this gate.

set -euo pipefail

# ── Helpers ───────────────────────────────────────────────────────────────────

BOLD=''
GREEN=''
YELLOW=''
RED=''
RESET=''
# Only enable colour when attached to a terminal (guard against non-interactive
# environments like Replit's shell where tput may block waiting for TERM).
if [ -t 1 ] && command -v tput &>/dev/null && tput colors &>/dev/null 2>&1; then
  BOLD="$(tput bold 2>/dev/null || true)"
  GREEN="$(tput setaf 2 2>/dev/null || true)"
  YELLOW="$(tput setaf 3 2>/dev/null || true)"
  RED="$(tput setaf 1 2>/dev/null || true)"
  RESET="$(tput sgr0 2>/dev/null || true)"
fi

step() { echo "${BOLD}${GREEN}==> ${1}${RESET}"; }
warn() { echo "${BOLD}${YELLOW}⚠   ${1}${RESET}"; }
fail() { echo "${BOLD}${RED}✘  FAILED: ${1}${RESET}" >&2; }

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FAILED_STEPS=()

run_step() {
  local name="$1"
  shift
  step "${name}"
  if "$@"; then
    echo "${GREEN}✔  ${name} passed${RESET}"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    fail "${name}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_STEPS+=("${name}")
    # Continue — collect all failures, don't stop at first
  fi
  echo ""
}

skip_step() {
  local name="$1"
  local reason="$2"
  warn "SKIP ${name}: ${reason}"
  ((SKIP_COUNT++))
  echo ""
}

# ── Step functions ────────────────────────────────────────────────────────────

step_typecheck() {
  # lib/api-zod and lib/db are TS composite project references
  # (emitDeclarationOnly); their gitignored dist/ .d.ts output must exist
  # before dependents (e.g. api-server) can typecheck against them via
  # "references" -- build them first, since a fresh clone never has it.
  pnpm --filter './lib/*' run build && pnpm -r run typecheck
}

step_lint() {
  # Use --max-warnings 0 to treat warnings as errors
  pnpm -r run lint 2>&1
}

step_test() {
  pnpm -r run test 2>&1
}

step_build() {
  pnpm --filter @workspace/api-server run build 2>&1
}

step_secrets() {
  if command -v gitleaks &>/dev/null; then
    gitleaks detect --config .gitleaks.toml --source . --no-banner 2>&1
  else
    warn "gitleaks not installed — skipping secret scan"
    warn "Install with:  brew install gitleaks  OR  apt-get install gitleaks"
    return 0
  fi
}

step_py_lint() {
  python -m ruff check packages/ flightctl/ tools/ deliverables/ --exclude archive 2>&1
}

step_py_format() {
  python -m ruff format --check packages/ flightctl/ tools/ deliverables/ --exclude archive 2>&1
}

step_py_typecheck() {
  # mypy resolves module identity from directory structure, and pytest's flat
  # (no-__init__.py) test-collection convention means every package's tests/
  # and conftest.py collide under one bare module name ("tests"/"conftest") if
  # scanned together. Each src-layout package therefore gets its own
  # `mypy src` pass (reading that package's own pyproject.toml config, per
  # AGENTS.md); flightctl/+tools/ (a single coherent namespace) and
  # deliverables/ (standalone, not part of any package's src/) are checked
  # separately against the root mypy.ini.
  local failed=0
  echo "-- packages/meshsa --"
  (cd packages/meshsa && python -m mypy src) 2>&1 | head -100 || failed=1
  if [[ -d packages/jetson_yolo_gcs ]]; then
    echo "-- packages/jetson_yolo_gcs --"
    (cd packages/jetson_yolo_gcs && python -m mypy src) 2>&1 | head -100 || failed=1
  fi
  echo "-- flightctl/ + tools/ --"
  python -m mypy flightctl/ tools/ --exclude archive 2>&1 | head -100 || failed=1
  echo "-- deliverables/ --"
  python -m mypy deliverables/ --exclude archive 2>&1 | head -100 || failed=1
  return "${failed}"
}

step_py_test() {
  # Subshell, not `cd … && cd -`: with the old form a pytest failure skipped the
  # `cd -`, leaving the whole script's cwd inside packages/meshsa — which made the
  # next step's `[[ ! -d packages/jetson_yolo_gcs ]]` guard silently skip the jetson
  # suite and count it as passing.
  (cd packages/meshsa && python -m pytest --tb=short -q 2>&1)
}

step_py_test_jetson() {
  if [[ ! -d packages/jetson_yolo_gcs ]]; then
    warn "packages/jetson_yolo_gcs not present — skipping"
    return 0
  fi
  (cd packages/jetson_yolo_gcs && python -m pytest --tb=short -q 2>&1)
}

# tools/claude_hooks/governance.py and tools/check_tool_pins.py both import PyYAML,
# which isn't stdlib and isn't pulled in by a bare `pip install -e packages/meshsa`
# (it rides in via pre-commit's mypy hook or CI's explicit pin). Without this check
# a missing install surfaces as a raw ImportError traceback from deep inside the
# checker instead of a clear, actionable message.
_require_pyyaml() {
  if ! python -c "import yaml" &>/dev/null; then
    echo "PyYAML is required for this step but is not installed." >&2
    echo "Install it with:  python -m pip install pyyaml" >&2
    return 1
  fi
}

step_governance_tests() {
  _require_pyyaml || return 1
  python -m pytest tools/claude_hooks/tests tools/tests -q 2>&1
}

step_bind_guard() {
  _require_pyyaml || return 1
  python tools/claude_hooks/bind_guard.py 2>&1
}

step_literal_guard() {
  _require_pyyaml || return 1
  python tools/claude_hooks/literal_guard.py 2>&1
}

step_workforce() {
  python tools/validate_workforce.py 2>&1
}

step_skills_lint() {
  python tools/validate_skills.py 2>&1
}

step_tool_pins() {
  _require_pyyaml || return 1
  python tools/check_tool_pins.py 2>&1
}

step_task_sync() {
  # Advisory: prints warnings, fails only when it cannot run at all.
  python tools/check_task_sync.py 2>&1
}

step_skills_tracked() {
  # .gitignore must exclude .agents/* (contents), never .agents/ (directory):
  # git cannot re-include files under an excluded parent, so the directory form
  # silently untracks NEW files under .agents/skills/ despite the negations.
  local probe=".agents/skills/.gitignore-probe"
  touch "${probe}"
  if git check-ignore -q "${probe}" 2>/dev/null; then
    rm -f "${probe}"
    echo ".gitignore regression: new files under .agents/skills/ are ignored"
    return 1
  fi
  rm -f "${probe}"
  return 0
}

step_py_syntax() {
  local py_bin
  if command -v python3 &>/dev/null; then
    py_bin="python3"
  elif command -v python &>/dev/null; then
    py_bin="python"
  else
    warn "Python not found — skipping Python syntax check"
    return 0
  fi

  local failed=0
  for py_file in $(find . -name "*.py" -path "*/packages/*" -o -name "*.py" -path "*/flightctl/*" -o -name "*.py" -path "*/tools/*" -o -name "*.py" -path "*/deliverables/*" | grep -v "node_modules"); do
    if ! "${py_bin}" -m py_compile "${py_file}" 2>&1; then
      echo "  Syntax error in: ${py_file}"
      failed=1
    fi
  done

  return "${failed}"
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo ""
echo "${BOLD}════════════════════════════════════════════════════════${RESET}"
echo "${BOLD}  Pre-PR Validation Gate                                ${RESET}"
echo "${BOLD}  $(date '+%Y-%m-%d %H:%M:%S')                         ${RESET}"
echo "${BOLD}════════════════════════════════════════════════════════${RESET}"
echo ""

run_step "TypeScript type checking"  step_typecheck
run_step "ESLint"                    step_lint
run_step "Test suite"                step_test
run_step "Production build"          step_build
run_step "Secret scan (gitleaks)"    step_secrets
run_step "Python linting (ruff)"     step_py_lint
run_step "Python formatting (ruff)"  step_py_format
run_step "Python type checking"      step_py_typecheck
run_step "Python test suite (meshsa)"       step_py_test
run_step "Python test suite (jetson_yolo_gcs)" step_py_test_jetson
run_step "Governance hook tests"     step_governance_tests
run_step "Bind guard"                step_bind_guard
run_step "Literal guard"             step_literal_guard
run_step "Workforce roster lint"     step_workforce
run_step "Skills playbook lint"      step_skills_lint
run_step "Tool-pin sync"             step_tool_pins
run_step "Task-checkbox sync (advisory)" step_task_sync
run_step "Skills trackable (.gitignore)" step_skills_tracked
run_step "Python syntax check"       step_py_syntax

# ── Summary ───────────────────────────────────────────────────────────────────

echo "${BOLD}════════════════════════════════════════════════════════${RESET}"
echo "  Passed: ${GREEN}${PASS_COUNT}${RESET}  |  Failed: ${RED}${FAIL_COUNT}${RESET}  |  Skipped: ${YELLOW}${SKIP_COUNT}${RESET}"
echo "${BOLD}════════════════════════════════════════════════════════${RESET}"

if [[ ${FAIL_COUNT} -gt 0 ]]; then
  echo ""
  echo "${RED}Failed steps:${RESET}"
  for s in "${FAILED_STEPS[@]}"; do
    echo "  ${RED}✘${RESET}  ${s}"
  done
  echo ""
  exit 1
fi

echo "${BOLD}${GREEN}  ✔  All validations passed — safe to open a PR  ${RESET}"
echo ""
exit 0
