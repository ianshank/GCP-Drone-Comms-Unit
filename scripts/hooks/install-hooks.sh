#!/usr/bin/env bash
# scripts/hooks/install-hooks.sh — install managed git hooks
#
# Run once after cloning:  bash scripts/hooks/install-hooks.sh
# Run via Makefile:         make hooks-install

set -euo pipefail

HOOKS_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DST="${GIT_ROOT}/.git/hooks"

BOLD="$(tput bold 2>/dev/null || echo '')"
GREEN="$(tput setaf 2 2>/dev/null || echo '')"
RESET="$(tput sgr0 2>/dev/null || echo '')"

hooks=("pre-commit")

for hook in "${hooks[@]}"; do
  src="${HOOKS_SRC}/${hook}"
  dst="${HOOKS_DST}/${hook}"

  if [[ ! -f "${src}" ]]; then
    echo "  skip ${hook} (source not found: ${src})"
    continue
  fi

  # Backup existing hook if it is not our symlink
  if [[ -f "${dst}" ]] && [[ ! -L "${dst}" ]]; then
    mv "${dst}" "${dst}.bak"
    echo "  backed up existing ${hook} → ${hook}.bak"
  fi

  ln -sf "${src}" "${dst}"
  chmod +x "${src}"
  echo "${GREEN}  ✔ ${hook}${RESET} → ${dst}"
done

echo "${BOLD}${GREEN}  ✔ Git hooks installed${RESET}"
