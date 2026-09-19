# Tasks — agents-md-directory-guides (rev.4)

> Order binding. Per-task gate: `make -f tools/Makefile checkers` clean → commit. **Tasks
> adding or changing Python under `tools/` additionally require** `ruff check`,
> `ruff format --check`, `mypy flightctl/ tools/ --exclude archive`, and
> `python -m pytest tools/claude_hooks/tests tools/tests -q` — `make checkers` runs none of
> those, and CHARTER §4 Invariant 6 does not bend for a checker. `tasks.md` is updated in
> the same commit as the work it tracks; checkbox lines use the plain `- [ ] T-x.y` form
> that `check_task_sync.py` requires. Split `T-x.ya/b` records honest partial execution.
> One review stop point, after Step 1.

rev.1–rev.3 are superseded. `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md` records four review
rounds; round 4 cut the change from 64 new files to 6 and is why this file is a third its
former length. The **trap register below is fully reused** — it is the artifact that
survived every round, and three adversarial passes made it accurate. What changed is where
the traps live, not what they say.

## Trap register — 89 facts by destination

Verified against the tree across four rounds. `[corrected]` marks a fact a review pass
fixed; `[verified]` marks one a review pass challenged and verification upheld.

### Root `AGENTS.md` (40 traps)

Covers `flightctl`, `lib`, `artifacts`, `tools`, `docs`, `openspec`, `deliverables`,
`.github`, `.claude`, `scripts`, `archive`. Four are already present today and stay.

| Domain | Traps |
| ------ | ----- |
| `flightctl` | Bring-up order is load-bearing — mavp2p `udpc` outputs are connected sockets, so consumers bind first. `MAVLINK20=1` or the simulator emits v1 and the gateway drops it. `mypy flightctl/ tools/` stays **one** invocation. `run_commander.py` is write-denied by `scope_freeze`. `M2R_BIND` defaults to `127.0.0.1` because mavlink2rest is an unauthenticated MAVLink surface — `0.0.0.0` is a command-injection path. **[corrected: added]** But two lines below that comment, `start_all.sh:165` starts mavp2p on `udps:0.0.0.0:$MAVP2P_IN_PORT` — an all-interfaces unauthenticated MAVLink ingest — and `:130` exports `FTS_UI_EXPOSED_IP=0.0.0.0`. Neither has an audit row. See T-0.3. `sim/mavlink_fake.py` holds a `literal_guard` waiver; substituting the default flips send→listen. Only `*.example` files are tracked |
| `lib` | Composite `dist/` must build before `pnpm -r run typecheck`. `orval.config.ts` sets `clean: true`, wiping the generated directory each codegen. **[corrected]** Two generated trees here, not three |
| `artifacts` | **[corrected: added]** `api-server/src/index.ts` calls `app.listen(port, cb)` with **no host argument** → binds all interfaces; `src/middlewares/` is `.gitkeep` only; `cors()` is unrestricted-origin; no auth. Absent from `docs/AUDIT_M2_AUTH.md`, outside `bind_guard`'s Python-only `SCAN_GLOBS`. See T-0.3. Also `PORT`/`BASE_PATH` throw by design; the esbuild `banner`/`external` list is load-bearing. **[corrected]** `test` exists only in `api-server` |
| `tools` | Coverage is **measured, not gated**, deliberately. `scope_freeze.py` must keep failing open. **[corrected]** `check_tool_pins.py::TOOLS` covers `ruff` and `mypy` only — nothing checks PyYAML |
| `docs` | No spec, no merge. Source cites specs by `§`, so renumbering breaks docstrings. `docs/C4.md` and `docs/architecture/C4.md` are different documents with one filename |
| `openspec` | `check_task_sync.py` parses `- [ ] T-x.y` with the id **immediately** after the bracket; bolding it makes every checkbox invisible (rev.1 scored 0/32) |
| `deliverables` | `xfail(strict=True)` is the contract. Test files inline reference implementations deliberately — do **not** DRY them. **[corrected]** Retirement is `code-hygiene-modularity` T-10.2b, not `NEXTSTEPS.md` |
| `.github` | Actions SHA-pinned; gitleaks version+checksum must match the pre-commit rev; the `governance` step's `shell: bash` is load-bearing (default shell lacks `pipefail`). **[corrected]** mypy runs at four points, not three |
| `.claude` | `governance.yaml` is Pydantic `extra="forbid"`; only a maintainer flips `c_gate_met`; hooks must fail open |
| `scripts` | Step 17 probes the `.agents/*`-vs-`.agents/` `.gitignore` trap. Step 9's subshell is deliberate. **[corrected]** `make validate-pre-pr` is the *root* Makefile's target |
| already present | Single-file pytest still applies `--cov-fail-under=97`; `build_node()` skips unknown transports on purpose; never hand-edit generated or binary artifacts; never commit secrets |

### `packages/meshsa/AGENTS.md` + rules `meshsa-core.md`, `meshsa-tests.md` (36 + 4)

| Scope | Traps |
| ----- | ----- |
| package root (guide) | The coverage floor and the exact `ruff`/`mypy` pins |
| `src/meshsa` (rule) | `build_node()` skips unknown transports deliberately. `defaults.py` is the sole literal home. `netauth.validate_bind` guards on `not token`, **not** `token is None`. `Router` splits `schema_mismatch` from `dropped_undecodable`. `UNKNOWN_ERROR_M` is shared. `command/` is frozen: ACK policy fail-closed, audit `fsync` off the loop thread, the `literal_guard` `"*"` waiver deliberate |
| `transports` (rule) | Import-time registration; a module never imported has no key. `tak_multicast.py` is a declared `bind_guard` exception = `AUDIT_M2_AUTH.md` #2, flagged not waived. **[verified]** Receive-only sources no-op `send()` via `PollingSourceTransport`/`DetectionIngestTransport`; `AbstractTransport.send` raises, so a source skipping both bases inherits the raise. A review claim that these sources do not override `send` was checked and **rejected** |
| `fpv`, `fpv/crsf` (rule) | `import meshsa.fpv` must never need the `[fpv]` extra. `DATASET_SCHEMA` is a separate namespace from `SCHEMA_VERSION`. `ArmGuard` is a ratified §3 carve-out. CRC8/DVB-S2 over `[type]+payload` only. Telemetry big-endian; RC LSB-first 11-bit. Both echo-suppression rules required |
| `scout`, `scout/station` (rule) | §3 offline-survey carve-out — inert files only, never uploads or commands. Unprojectable detections dropped-and-counted, never fabricated. Seeded RNG for replay. Fail-closed bind inside `build_app` before routes — why `scout/cli.py` carries its exception. SRI-pinned tags; `_webpage.js_literal`, never bare `json.dumps` |
| `ui`, `inference`, `llm` (rule) | I-2 read-only route contract asserted by a route-table test. Single-threaded on the pump loop — no locks, no threads. Absent source ⇒ route not registered. No `innerHTML` sink. Inference must work with no `aiohttp` when a transport is injected; `_is_ai_insight` is the loop guard. Every LLM tool is read-only |
| `tests` (rule) | Fakes only. Hypothesis `ci` is `derandomize=True, database=None`. The 97% floor applies to *any* invocation |

### `packages/jetson_yolo_gcs/AGENTS.md` + rule `perception.md` (8)

Floor 96; **no runtime dependency on `meshsa`** is an architectural gate; `norfair` pins
`numpy<2`. The per-path failure policy must not be collapsed: detection drop-and-count,
stream best-effort, tracking advisory, and `LANDING_TARGET` **tolerate-then-escalate**
against `publish_failure_tolerance` (default 3). **[corrected — the live defect is already
fixed, see T-0.2]**. The MAVLink path is advisory, off by default, fail-closed heartbeat
gate, monotonic freshness vs wall-clock `time_usec`, mirrors `meshsa.command.health`
without importing meshsa. `tests/unit/test_imports_clean.py` is a hard architectural gate.

### `ops/AGENTS.md` (3) and `hardware/AGENTS.md` (2)

Idempotent scripts; `SIGINT` for clean asyncio shutdown; only `*.example` env files
tracked. Binary STL/PNG regenerated never hand-edited; `pi5_node_*` duplicated with
`ops/pi5-node/` and must move together.

### Rule `generated-code.md` (7)

The case five files cannot serve — these fire when the generated file is opened.
`lib/api-zod/src/generated/**` and `lib/api-client-react/src/generated/**` are orval output
wiped by `clean: true`; edit `lib/api-spec/openapi.yaml`. `custom-fetch.ts` is hand-written,
load-bearing, and **outside** the clean scope. `artifacts/mockup-sandbox/src/.generated/**`
is rewritten each dev/build. **[corrected]** `components/ui` holds **55** vendored shadcn
files, not ~70 — regenerate via the CLI. `packages/meshsa/tests/snapshots/**` regenerates
with `MESHSA_UPDATE_SNAPSHOTS=1`; a diff means the wire format changed. **[corrected]**
`archive/**` is excluded from `ruff`, `ruff-format` and `mypy` only, and the exclusion lives
in the invocations, not in `ruff.toml`. `gitleaks` and `check-added-large-files` still see
it; the `types: [text]` hooks do not, because the tree is five `.zip` files.

### Rules `ts-workspace.md` (10) and `governance.md` (13)

The `lib`/`artifacts` and `tools`/`.claude`/`.github`/`scripts` traps above, restated at
path scope so they fire when the matching file is touched rather than only at session
start.

## Step 0 — ship independently

- [ ] T-0.1 `CLAUDE.md`: replace the `[AGENTS.md](AGENTS.md)` link with an `@AGENTS.md`
      import. Verify with `claude --debug` or the `InstructionsLoaded` hook. Single
      highest-value change in the bundle.
- [x] T-0.2 Correct the `LANDING_TARGET` failure policy in
      `packages/jetson_yolo_gcs/AGENTS.md` and
      `.agents/skills/jetson-perception/SKILL.md`. **Landed** — both said "fails loud"; the
      code tolerates then escalates against `publish_failure_tolerance` (default 3).
- [ ] T-0.3 **Widen `docs/AUDIT_M2_AUTH.md`'s scope, then add the missing rows.** Its
      declared scope (line 9) is *"every socket-bound or link-bound surface in
      `packages/meshsa` and `packages/jetson_yolo_gcs`"*, while the ROADMAP M2 invariant is
      repo-wide. That mismatch — not a single omission — is the finding. Widen the scope
      line first, then add rows using the table's real columns (`Direction` included) for
      at least three surfaces review found outside it: `artifacts/api-server`
      (`app.listen(port, cb)`, no host arg, no auth, no TLS, one `GET /api/healthz` route),
      `flightctl/scripts/start_all.sh:165` mavp2p `udps:0.0.0.0:$MAVP2P_IN_PORT`
      (unauthenticated MAVLink ingest), and `:130` `FTS_UI_EXPOSED_IP=0.0.0.0`.
      **Severity, stated honestly:** the api-server surface exposes one unauthenticated
      static health route with no data path, and its `.replit-artifact/artifact.toml`
      deploys it behind a platform proxy where an all-interfaces bind inside the container
      is *required* — so it is not comparable to the audited meshsa surfaces. The mavp2p
      socket is the more serious of the three. Recording a surface is not authenticating
      it; remediation is deferred and named below.
- [ ] T-0.4 Verify `.github/CODEOWNERS` covers `**/AGENTS.md`, `**/CLAUDE.md` and
      `.claude/rules/**`. It is `* @ianshank` today, which does. Human review of the diff
      is the load-bearing control for this entry point.

## Step 1 — traps into the five existing guides *(review stop point)*

- [ ] T-1.1 Root `AGENTS.md`: add `## Traps` with its 40 facts; fold "Agent Skills" +
      "Custom Agents" + "Subagent roster" into one delegation table; extend the Repository
      Map to the **eight** directories it omits — `flightctl`, `lib`, `artifacts`,
      `deliverables`, `openspec`, `scripts`, `.claude`, and `packages/jetson_yolo_gcs`,
      which is a whole second distribution with its own guide and coverage floor; add the defensive injection directive, noting
      in-file that its measured effect is on documentation-borne injection, a different
      entry point from the one this change touches. Lands ~170 lines.
- [ ] T-1.2 `packages/meshsa/AGENTS.md`, `packages/jetson_yolo_gcs/AGENTS.md`,
      `ops/AGENTS.md`, `hardware/AGENTS.md`: add `## Traps`; add `— why:` to every existing
      rule (10 across `ops` and `hardware` currently have none) and `— control:` /
      `— advisory` to every security rule.
- [ ] T-1.3 Optional per-guide Mermaid where a diagram encodes a constraint the code cannot
      show. `accTitle`, `accDescr`, a prose summary, one per file.

> **Stop for review.** Five files, no new instruction files, no new machinery. If the
> content is wrong it is wrong in five places — and thanks to T-0.1 it is actually being
> read.

## Step 2 — six path-scoped rules

- [ ] T-2.1 `.claude/rules/{meshsa-core,meshsa-tests,perception}.md` with `paths:`
      frontmatter.
- [ ] T-2.2 `.claude/rules/{generated-code,ts-workspace,governance}.md`.
      `generated-code.md` is the one that solves the fire-on-open case rev.3 could not.

## Step 3 — procedure back to skills

- [ ] T-3.1 Move procedure-shaped content into the skills that already own it:
      `pre-pr-validator`, `meshsa-test-conventions`, `meshsa-schema-version-bump`,
      `meshsa-add-transport`, `meshsa-commanding-safety`, `config-literal-sweep`,
      `spec-driven-change`, `ops-deploy-base-node`. Per
      `.github/copilot-instructions.md`, this is the repo's standing policy, not a new one.
- [ ] T-3.2 At most three new skills where none fits (`ts-codegen`, `ci-workflow-edit`,
      `governance-hooks`). Each must pass `python tools/validate_skills.py`.

## Step 4 — a four-check validator

- [ ] T-4.1 `tools/validate_agents_docs.py`, ~120 LOC: (1) instruction files on disk match
      the module-constant list, enumerated via `git ls-files`; (2) every cited path
      resolves, carrying the five round-3 corrections — strip `[extras]`, reject
      bare-extension tokens, reject absolute paths, add the nearest `src/<pkg>/` as a third
      resolution base, allow declared counter-examples; (3) **control-character hygiene** — reject bidirectional-override
      (U+202A-E, U+2066-9) and zero-width (U+200B-D) code points by exact code point. rev.3
      also required "ASCII-dominant", which is undefined and self-defeating: the authoring
      contract mandates U+2014 in every `— why:` clause, U+00B7 in every breadcrumb and
      U+2264 in the budgets, so any threshold in the observed 0.04–0.48% range is a coin
      flip on whether the checker fires on the format it requires. Dropped; (4) `## Traps` present in each of the five guides. Policy as
      module constants — **nothing in `governance.yaml`** (I-2).
- [ ] T-4.2 `tools/tests/test_validate_agents_docs.py`. Assert the `OK:` prefix and compare
      against the constant, never a hard-coded count.
- [ ] T-4.3 Extend `validate_skills.py::CHECKABLE_PATH_PREFIXES` with `lib/`, `artifacts/`,
      `scripts/` — the existing skills linter shares the gap.
- [ ] T-4.4 Wire into `tools/Makefile`'s `checkers` (and its `help` text),
      `scripts/validate-pre-pr.sh` after `step_skills_lint`, the CI `governance` job after
      "Skills playbook lint", and `.pre-commit-config.yaml`.
- [ ] T-4.5 `CONTRIBUTING.md` checklist line; the per-developer `instructionFiles` note;
      `CHANGELOG.md`. **No `docs/specs/README.md` registration** — that file indexes
      initiative specs, neither existing openspec bundle appears in it, and adding a
      governance bundle would cut against this proposal's own "not authoritative over
      `docs/specs/`" scope line.

## Explicitly deferred (separate changes)

- Remediating the `artifacts/api-server` bind. T-0.3 documents and audits it; changing the
  listener needs its own decision.
- Extending `bind_guard` to TypeScript. The Python-only `SCAN_GLOBS` is why T-0.3's surface
  went unnoticed, but widening a governance linter to a second language is its own change.
- Per-directory guides below the five. **Withdrawn, not deferred** — see the peer review.
- A deliberate split of the root guide if it outgrows ~200 lines. rev.4 accepts a long root
  over a budget that blocks merges.

## Verification

```bash
python tools/validate_agents_docs.py
make -f tools/Makefile checkers
```

Tasks touching `tools/` additionally: `ruff check tools && ruff format --check tools`,
`mypy flightctl/ tools/ --exclude archive`,
`python -m pytest tools/claude_hooks/tests tools/tests -q`.
Before the PR: `make validate-pre-pr`.

## Risks

| Risk | Mitigation |
| ---- | ---------- |
| A guide states an invariant the code contradicts | Two such statements were found live during review and are fixed (T-0.2). No checker catches this class; the review stop point and `security-reviewer` are the control |
| The root grows past any budget | Accepted deliberately. Measured at +16 lines/month, a budget check would block merges within 60 days. Open call #2 puts the choice to the maintainer |
| `.claude/rules/` is Claude-only | Open call #1. The five `AGENTS.md` stay the portable layer |
| Six new rules still widen the trusted-context surface | True, and stated. The win is 6 new files instead of 64; `CODEOWNERS` review is the load-bearing control |
| Procedure drifts back into guides | T-3.1 returns it to skills, where `validate_skills.py` already lints it, per standing repo policy |
