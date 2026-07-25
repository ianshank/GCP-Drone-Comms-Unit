# Design — Agent-Driven M2 Hardening

## D-1. Subagent roster (all M2-scoped, collaborate by default)

Markdown + YAML frontmatter under `.claude/agents/`. Created security-reviewer
first so it reviews the rest into existence.

**Relationship to existing agent infrastructure (binding):** the repo already
has custom agents in `.github/agents/*.agent.md` and playbooks in
`.agents/skills/`, both indexed from `AGENTS.md`. Every `.claude/agents/` entry
MUST carry a `Relationship:` line naming the corresponding existing agent/skill
where one exists (`tools/validate_workforce.py` enforces the marker and that
referenced paths exist). No existing agent or skill file is modified.

| Agent | Mandate | Notes |
|---|---|---|
| `security-reviewer` | Adversarial review of every diff; confidence-tagged; cite by symbol, not line; verifies fail-closed on each touched surface; a guard *predicate* is part of the surface (`token is None` ≠ `not token`) | created first |
| `bind-auditor` | Keeps the `AUDIT_M2_AUTH.md` inventory in sync with code; flags new binds lacking `validate_bind` and any re-implementation of it outside `meshsa.netauth` (delegating adapters acceptable) | owns I-1 |
| `openspec-author` | Scaffolds/validates change bundles; house delta format | owns the bootstrap |
| `test-engineer` | Tests-first; 100% per-module target for new security code (the `pacing` precedent — and wrote the missing `test_netauth.py`); forbids mock/patch on fail-closed assertions | owns I-4 |
| `soak-engineer` | Owns `docs/specs/m2-soak-fuzz.md`; heartbeat/pacing/backoff fail-closed behavior under sudden link drop | owns the resilience gap |
| `config-guardian` | Hunts hardcoded ports/hosts/tokens/intervals; proposes config homes per the repo's Pydantic pattern | owns I-3 |
| `charter-gate-keeper` | Watches the Initiative-C command emission path; asserts the M2 gate is unmet → flags for human decision; never flips the gate | pairs with I-5 hook |

## D-2. Hooks (mechanical governance — extend the existing SessionStart hook)

| Hook | Event | Behavior |
|---|---|---|
| `scope_freeze.py` | PreToolUse (Write/Edit) | Deny edits matching `governance.command_emission_globs` while `c_gate_met=false`, or `governance.scope_widening_globs` always. Override env (`MESHSA_GOVERNANCE_OVERRIDE`) allows with a logged stderr line. Malformed input fails open (the hook governs agents, not humans; CI is the backstop). |
| `bind_guard.py` | CI job + CLI | AST scan of `packages/**/src/**` + `flightctl/`: any file creating a network listener must import **and call** `validate_bind` from `meshsa.netauth` (re-exports accepted) or be a declared exception with rationale in `.claude/governance.yaml`. A `def validate_bind` outside the canonical module is a violation unless it demonstrably delegates (imports the canonical symbol and calls it in its body). |
| `session-start.sh` | SessionStart | Extended additively: prints the current fail-open count from `AUDIT_M2_AUTH.md` so every session opens on the gate state. |

All hooks are Python under `tools/claude_hooks/`, config-driven from
`.claude/governance.yaml` (Pydantic v2, `extra="forbid"`), pytest-covered
(51 tests), run by the new `governance` CI job.

## D-3. The named gaps → closed, with tests

1. **Surface #10 `DetectionIngestTransport` (UDP `127.0.0.1:8099`)** — audit:
   "any local process may inject; no bind guard, fails open on override."
   Closed: `validate_bind` at construction (fail-fast at wiring time); `token`
   accepted via `TransportConfig.options` (the transports' config mechanism);
   non-loopback + token binds with a loud WARNING that datagrams remain
   unauthenticated until the signing seam gains an implementation.
2. **Surface #14 Jetson GStreamer RTP egress** (`StreamSettings` in
   `core/config.py`; *outbound to loopback* by default — lower severity than
   the rev.1 bundle implied, still fail-open). Closed: `enabled=False`
   default; opt-in via `STREAM_ENABLED=true`; exactly one WARNING naming the
   destination at activation; activation routed through a single
   `create_stream_writer` gate so default-off builds nothing.
3. **Commander bind-guard unification (found in review).**
   `run_commander.py::validate_bind` was a local duplicate whose predicate
   (`token is None`) accepted an empty token when called as an API
   (`main()` normalized `""`→`None`, so the CLI path was safe), and it
   imported auth helpers from `meshsa.llm.server`. Closed: the function is now
   a thin delegating adapter over `meshsa.netauth.validate_bind` (ValueError →
   operator-facing SystemExit), imports come from `meshsa.netauth`, and an
   empty-token test pins the fix.
4. **Transport-wide auth gap** — audit: "per-surface, not transport-wide."
   Added the thin `TransportAuthPolicy` protocol + `NetAuthPolicy` default in
   `meshsa.netauth` (the four HTTP surfaces already satisfy it via the module
   primitives). A signing implementation is a separate, gated change; the
   audit still records the framework gap as open.

## D-4. Link-loss resilience soak

Authored `docs/specs/m2-soak-fuzz.md` (Track A.3) and shipped
`packages/meshsa/tests/test_link_loss_soak.py`: 500-cycle heartbeat-interlock
soak (fail closed on silence, arbitrary-length outage never reopens, one beat
recovers), pacer flood/stall/backward-jump soaks (sustained rate never exceeds
`rate_hz`; no storm on reconnect flush), backoff saturation (attempt rate
bounded by `1/max_s`, clean reset), plus a `slow`-marked 5 000-cycle randomized
fuzz for the nightly workflow. All on injected fake clocks — deterministic,
milliseconds per run. On-radio bench validation is the spec's §8 exit to
`Validated`. Availability ≠ auth: the spec forbids accepting an auth control
as mitigation here.

## D-5. MCP + docs

- `.mcp.json`: GitHub MCP only, project scope, secretless (`GITHUB_TOKEN` env
  reference). Others rejected — a field comms unit's tooling surface stays
  minimal.
- `AGENTS.md`: collaboration directive (I-6) + `.claude/agents/` pointer added
  to the existing Custom Agents section; `CLAUDE.md` gains one pointer line.
- `docs/AUDIT_M2_AUTH.md` rows #6/#10/#14, the framework section, gap summary,
  and follow-up backlog updated in place, "this branch"-marked per the row-7
  precedent (bind-auditor mandate: table tracks code).

## D-6. Testing & CI (I-4)

- New `governance` CI job: hook/linter test suite + repo-wide `bind_guard`
  scan (clean at 125 files with two declared exceptions: TAK multicast, scout
  CLI transitively-guarded serve loop).
- meshsa: 988 tests + 5 soak tests, coverage 99.16% (gate 97). jetson: 205
  tests, 99.34% (gate 96). `netauth` now has direct tests including the
  empty-token edge on every guarded caller.
- Fail-closed tests exercise real bind logic (no mocking the assertion).
- `openspec validate --strict` in CI is **deferred**: the `openspec` CLI is
  not installed in this repo/CI; wiring it is a follow-up once the toolchain
  choice is a maintainer decision (tracked in tasks.md T-1.2).
