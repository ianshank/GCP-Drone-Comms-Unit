---
paths:
  - "tools/**/*.py"
  - ".claude/**"
  - ".github/workflows/**"
  - ".pre-commit-config.yaml"
  - "scripts/**/*.sh"
  - "openspec/**/*.md"
---

# Governance machinery

Fires on the checkers, the hook config, CI, and the pre-PR script — the files whose
failure mode is *silence* rather than a red build.

## Rules

- Keep `tools/claude_hooks/scope_freeze.py` failing open — why: a malformed payload, a
  missing field, or an unreadable config must all return allow, because the config
  lives under `.claude/` and has to stay editable to be fixed; a hook that fails closed
  can brick the session that would repair it — control: the hook always exits 0 and
  expresses a deny only via stdout JSON. Do not "harden" this into a non-zero exit.
- Do not flip `c_gate_met` in `.claude/governance.yaml`, and do not add documentation
  data to that file — why: only a maintainer flips the M2 charter gate, and the loader
  is Pydantic `extra="forbid"`, so an unrecognised key makes the config unloadable —
  at which point the fail-open rule above silently stops the Initiative-C freeze from
  denying — control: the **charter-gate-keeper** subagent reviews any such diff.
- Keep `shell: bash` on the piped governance step in `.github/workflows/ci.yml` — why:
  the default runner shell lacks `pipefail`, so `pytest | tee` exits with `tee`'s
  status and a fully failing suite reports the job green.
- Keep GitHub Actions SHA-pinned — why: a tag is mutable, so a tag-pinned action is an
  unreviewed third party with write access to CI — control: all 21 `uses:` across the
  four workflows are currently full 40-char SHAs (the `ts` job's `pnpm/action-setup`
  and `actions/setup-node` included); nothing enforces it mechanically, so this is the
  check — advisory.
- When changing a pinned tool version, change it in every place it appears — why:
  `check_tool_pins.py::TOOLS` covers `ruff`, `mypy` (two pyprojects + pre-commit) and
  `gitleaks` (pre-commit rev + `ci.yml` `GITLEAKS_VERSION`) only, so PyYAML, pydantic
  and pytest drift between CI and pre-commit undetected, and the gitleaks CI
  **checksum** has no counterpart to compare against — a gitleaks bump means
  downloading the release tarball and re-deriving `GITLEAKS_SHA256` by hand —
  control: `tools/check_tool_pins.py`, for those three tools only.
- Add an `archive/` exclusion to any new lint or type invocation you introduce — why:
  `ruff.toml` does **not** exclude `archive/`; every exclusion lives at the call site
  (CI args, pre-commit `exclude:`, `scripts/validate-pre-pr.sh`), so a new invocation
  silently picks the archive up.
- Cite a step in `scripts/validate-pre-pr.sh` by name, never by number — why: the
  header comment collapses the two pytest runs into one entry, so it always lists one
  fewer step than the script issues `run_step` calls (19 vs 20 today), *and* inserting
  a step renumbers every one after it — the `.agents` `.gitignore` probe moved from
  header-#17/runtime-#18 to header-#18/runtime-#19 when the instruction-file lint was
  added ahead of it, which falsified this very bullet's previous wording. If you add a
  step, update the header list in the same commit. Note that probe writes a file into
  the working tree.
- Keep the subshell in `step_py_test` — why: the older `cd … && cd -` form left the
  script's cwd inside `packages/meshsa` after a failure, which made the next step's
  directory guard skip the jetson suite and count it as passing.
- Write task checkboxes as `- [ ] T-x.y` with the id immediately after `] ` — why:
  `tools/check_task_sync.py` matches `^[-*] \[([ xX])\] (T-\d+\.\d+[a-z]?)\b`, so
  bolding the id makes **every** checkbox in the file invisible to it, with no error
  — control: `tools/check_task_sync.py`, which is advisory (exit 0) and so will not
  fail a build on your behalf.
- The `tools/` suite's `--cov-fail-under=90` lives on the pytest command line in the
  CI governance step, not in a config file — why: `tools/` has no pyproject, so a local
  run without the flag measures and does not gate; the floor was set after two months
  of report-only measurement at 95–96 % (P0-5 of `docs/CODE_QUALITY_TECH_DEBT_PLAN.md`)
  and rises to 95 once `scope_freeze.py` has in-process tests. Do not lower it
  silently; the package floors (97 meshsa, 96 jetson) stay in their pyprojects —
  control: the `--cov-fail-under=90` flag on the CI governance step itself; nothing
  enforces the floor locally — advisory.
