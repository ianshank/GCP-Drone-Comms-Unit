---
paths:
  - "packages/meshsa/tests/**/*.py"
---

# meshsa test suite

Fires when a framework test is opened. Procedure for writing tests lives in
[.agents/skills/meshsa-test-conventions/SKILL.md](.agents/skills/meshsa-test-conventions/SKILL.md);
this file is only the things that surprise people.

## Rules

- Use the fakes (`LoopbackBus`, injected connectors, `FakeClock`, `SeqIdFactory`)
  rather than live hardware, sockets, or a real TAK server — why: the suite has to run
  with no radio and no network, which is also what makes it deterministic
  — advisory: nothing mechanical enforces the seam; the coverage floor and review do.
- Expect the coverage floor to apply to *any* invocation, including a single-file run
  — why: `--cov-fail-under=97` lives in `addopts` in
  `packages/meshsa/pyproject.toml`, so it is not something a targeted run opts into.
  A file whose own tests all pass can still fail the gate. Run the full suite for the
  real signal; `.github/workflows/fts-e2e.yml` is the one documented `--no-cov` escape.
- Do not assume a Hypothesis pass means the property holds — why: the `ci` profile is
  the default here (`derandomize=True`, `database=None`), so every run uses the same
  seeds and a counterexample found on another machine is not replayed from a database.
- Do not delete a regenerated snapshot to make a diff go away — why: a snapshot diff
  means the wire format changed, which is the signal the snapshot exists to raise.
  Regenerate deliberately with `MESHSA_UPDATE_SNAPSHOTS=1` and treat the diff as a
  schema-version decision.
