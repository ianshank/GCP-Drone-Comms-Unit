# Summary

<!-- What changed and why. Link the spec (docs/specs/) or OpenSpec change bundle
     (openspec/changes/) that covers this work — "a feature without a spec does not
     merge" (docs/specs/README.md). -->

## Bundle / spec reference

- Spec or bundle:
- Task IDs (T-x.y) executed, with checkboxes updated in the same commits:

## Verification

<!-- Check each gate you ran. From packages/meshsa (full suite only — a single-file run
     breaks the coverage gate): -->

- [ ] `python -m pytest` (meshsa, 97% gate)
- [ ] `python -m pytest` (jetson_yolo_gcs, 96% gate)
- [ ] `mypy src` (both packages) + `mypy flightctl/ tools/ deliverables/ --exclude archive`
- [ ] `ruff check` + `ruff format --check` (repo scope)
- [ ] `python tools/claude_hooks/bind_guard.py`
- [ ] `python tools/claude_hooks/literal_guard.py` (exceptions-only output)
- [ ] `python tools/check_tool_pins.py`
- [ ] `bash scripts/validate-pre-pr.sh`

## Security / governance

- [ ] No new listener binds without `meshsa.netauth.validate_bind` (or a declared
      `.claude/governance.yaml` exception with rationale)
- [ ] `docs/AUDIT_M2_AUTH.md` updated if any audited surface's file was touched
- [ ] No writes to the frozen command path (`packages/meshsa/src/meshsa/command/**`,
      `flightctl/run_commander.py`) while `c_gate_met` is false
- [ ] Any `.claude/governance.yaml` change is called out below for maintainer sign-off

## Operator-visible changes

<!-- Default ports, hosts, env vars, systemd units, CLI flags. "None" is an answer;
     if any, add a CHANGELOG entry. -->
