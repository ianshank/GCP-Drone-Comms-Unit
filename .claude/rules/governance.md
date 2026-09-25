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
  unreviewed third party with write access to CI — control: all 18 `uses:` across the
  four workflows are currently full 40-char SHAs; nothing enforces it mechanically, so
  this is the check — advisory.
- When changing a pinned tool version, change it in every place it appears — why:
  `check_tool_pins.py::TOOLS` covers `ruff` and `mypy` only, so PyYAML, pydantic and
  pytest drift between CI and pre-commit undetected; the gitleaks **version** matches
  the pre-commit rev today but its CI **checksum** has no counterpart to compare
  against — control: `tools/check_tool_pins.py`, for ruff and mypy only.
- Add an `archive/` exclusion to any new lint or type invocation you introduce — why:
  `ruff.toml` does **not** exclude `archive/`; every exclusion lives at the call site
  (CI args, pre-commit `exclude:`, `scripts/validate-pre-pr.sh`), so a new invocation
  silently picks the archive up.
- Cite a step in `scripts/validate-pre-pr.sh` by name, never by number — why: the
  header comment collapses the two pytest runs into one entry, so it lists 18 steps
  while the script issues 19 `run_step` calls; the `.agents` `.gitignore` probe is
  header-#17 and runtime-#18. Note that probe writes a file into the working tree.
- Keep the subshell in `step_py_test` — why: the older `cd … && cd -` form left the
  script's cwd inside `packages/meshsa` after a failure, which made the next step's
  directory guard skip the jetson suite and count it as passing.
- Write task checkboxes as `- [ ] T-x.y` with the id immediately after `] ` — why:
  `tools/check_task_sync.py` matches `^[-*] \[([ xX])\] (T-\d+\.\d+[a-z]?)\b`, so
  bolding the id makes **every** checkbox in the file invisible to it, with no error
  — control: `tools/check_task_sync.py`, which is advisory (exit 0) and so will not
  fail a build on your behalf.
- Do not add a `--cov-fail-under` to the `tools/` suite without saying so — why:
  coverage there is measured, not gated, deliberately and by a written measure-first
  decision in CI; the package floors (97 meshsa, 96 jetson) are the gated ones.
