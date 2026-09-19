# Tasks — agents-md-directory-guides (rev.2)

> Order binding. Per-task gate: write → `python tools/validate_agents_docs.py` clean →
> `make -f tools/Makefile checkers` clean → commit. **Tasks that add or change Python
> under `tools/` additionally require** `ruff check`, `ruff format --check`,
> `mypy flightctl/ tools/ --exclude archive`, and
> `python -m pytest tools/claude_hooks/tests tools/tests -q` — `make checkers` runs none
> of those, and CHARTER §4 Invariant 6 does not bend for a checker. T-0.x and T-1.1/T-1.2
> predate the checker and are gated on `checkers` alone; the header's first clause applies
> from T-1.3 onward. `tasks.md` is updated in the same commit as the work it tracks
> (`tools/check_task_sync.py` reconciles it; checkbox lines use the plain
> `- [ ] T-x.y` form that its parser requires — rev.1 bolded the id and scored 0/32).
> Split `T-x.ya/b` records honest partial execution after the fact. Review stop points
> after T-1 and T-3.

rev.1 is superseded; see `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md`. Every manifest cell
below was re-verified against the tree after three adversarial review passes; the
corrections are marked **[corrected]**.

## Tier manifest

`✎` = exists, retrofit. `✚` = new. The **trap** column is what earns the guide (D-2):
something an agent gets wrong by default that the parent cannot state. "Interesting code"
does not qualify.

### Tier 0 — root (1 file, ≤170 lines)

| Path | | Trap |
| ---- | - | ---- |
| `.` | ✎ | Repo-wide truth, the delegation table, and the defensive injection directive (D-9). Its Repository Map omits `flightctl`, `lib`, `artifacts`, `deliverables`, `openspec`, `scripts`, `.claude` — verified |

### Tier 1 — domain roots (13 files, ≤80 lines)

| Path | | Trap |
| ---- | - | ---- |
| `packages/meshsa` | ✎ | A single-file pytest run still applies `--cov-fail-under=97` and fails on its own; only the full suite is the gate. `ruff==0.16.3`/`mypy==2.3.0` are pinned exactly and `check_tool_pins.py` enforces the match |
| `packages/jetson_yolo_gcs` | ✎ | Coverage floor 96; **no runtime dependency on `meshsa`** is an architectural gate, not a preference; `norfair` pins `numpy<2` transitively. **[corrected]** Must shed its pipeline-failure-policy block to `docs/specs/initiative-d-perception.md` to fit the budget (D-4) |
| `flightctl` | ✚ | Bring-up order is load-bearing: mavp2p `udpc` outputs are connected sockets, so consumers must bind first. `mypy flightctl/ tools/` must stay **one** invocation. `run_commander.py` is write-denied by the scope-freeze hook. `M2R_BIND` defaults to `127.0.0.1` because mavlink2rest is an unauthenticated MAVLink surface — a `0.0.0.0` bind is a command-injection vector **[corrected: added]** |
| `lib` | ✚ | Composite `dist/` must be built before `pnpm -r run typecheck`, or dependents fail to resolve. `orval.config.ts` sets `clean: true`, which **wipes the generated directory** on every codegen. **[corrected]** Two generated trees here, not three — the third is under `artifacts/` |
| `artifacts` | ✚ | **[corrected: added]** `api-server/src/index.ts` calls `app.listen(port, cb)` with **no host argument**, so it binds all interfaces; `src/middlewares/` holds only `.gitkeep`, `app.use(cors())` is unrestricted-origin, and there is no auth. This surface is **absent from `docs/AUDIT_M2_AUTH.md`** and outside `bind_guard`'s Python-only `SCAN_GLOBS` — all verified. See T-0.4. Also: `PORT`/`BASE_PATH` throw by design; the esbuild `banner`/`external` list is load-bearing. **[corrected]** `test` exists only in `api-server`, not `mockup-sandbox` |
| `ops` | ✎ | Scripts must stay idempotent; `SIGINT` is load-bearing for clean asyncio shutdown; only `*.example` env files are tracked |
| `hardware` | ✎ | Binary STL/PNG must be regenerated, never hand-edited; `pi5_node_*` assets are duplicated with `ops/pi5-node/` and must move together |
| `tools` | ✚ | Coverage here is **measured, not gated** — deliberately, until `scope_freeze.py` has in-process tests; do not add a floor that freezes today's artifact. `scope_freeze.py` must keep failing open. **[corrected]** `check_tool_pins.py::TOOLS` covers `ruff` and `mypy` only — PyYAML is pinned in `ci.yml` alone and nothing checks it; stating otherwise would have been false on the day it was written |
| `docs` | ✚ | A feature without a committed spec does not merge; source cites specs by `§` number, so renumbering breaks docstring references. `docs/C4.md` and `docs/architecture/C4.md` are different documents with the same filename |
| `openspec` | ✚ | `check_task_sync.py` parses `- [ ] T-x.y` with the id **immediately** after the bracket — bolding it makes every checkbox invisible (rev.1 scored 0/32 against the reference bundles' 71/71 and 20/20). Strict house delta format; no bundle may flip `c_gate_met` |
| `deliverables` | ✚ | `xfail(strict=True)` is the contract; flipping one without landing its patch is a false green. Test files deliberately inline reference implementations — do **not** DRY them. Retirement in progress. **[corrected]** The retirement task is `code-hygiene-modularity` T-10.2b, not `NEXTSTEPS.md` |
| `.github` | ✚ | Every third-party action is SHA-pinned; the gitleaks version and checksum must match the pre-commit rev; the `governance` step's `shell: bash` is load-bearing (the default runner shell lacks `pipefail`, so `pytest \| tee` would report green on a failing suite). **[corrected]** mypy runs at four points across CI, not three |
| `.claude` | ✚ | `governance.yaml` is Pydantic `extra="forbid"`; only a maintainer flips `c_gate_met`; hooks must fail open. **[corrected]** This directory gets **no paired `CLAUDE.md`** — see T-0.5 |

### Tier 2 — subsystems (15 files, ≤60 lines)

| Path | | Trap |
| ---- | - | ---- |
| `packages/meshsa/src/meshsa` | ✚ | `build_node()` deliberately skips unknown transport types — do not convert to a hard failure. `defaults.py` is the sole home for port/host/queue/backoff literals. `netauth.validate_bind` uses `not token`, not `token is None` — different controls. Hosts the `### command/ (frozen)` subsection (D-11) |
| `.../src/meshsa/transports` | ✚ | Registration is import-time via `@transport_registry.register`; a module that is never imported has no key. `tak_multicast.py` is a declared `bind_guard` exception tracked as `AUDIT_M2_AUTH.md` surface #2 — flagged, not waived. Receive-only sources no-op `send()` via `PollingSourceTransport` and `DetectionIngestTransport`; `AbstractTransport.send` raises, so a new source that skips both bases inherits the raise **[verified: a review claim that these sources do not override `send` was checked and rejected — `polling_source.py::send` returns `None`]** |
| `.../src/meshsa/fpv` | ✚ | `import meshsa.fpv` must never require the `[fpv]` extra. `DATASET_SCHEMA` is a **separate** version namespace from `SCHEMA_VERSION` — bumping one must not bump the other. `ArmGuard` is a ratified CHARTER §3 carve-out; retiring it is a §6 decision, not hygiene |
| `.../src/meshsa/fpv/crsf` | ✚ | CRC8/DVB-S2 is computed over `[type] + payload` only — addr and len excluded. Telemetry is big-endian; RC channels are LSB-first 11-bit. Both echo-suppression rules are required. `telemetry.py` is held at 100% coverage |
| `.../src/meshsa/scout` | ✚ | CHARTER §3 offline-survey carve-out: produces inert files a human loads into their own GCS; never uploads, arms, or commands. Unprojectable detections are dropped-and-counted, never given a fabricated position. Replay uses a seeded `random.Random`, never the global RNG |
| `.../src/meshsa/scout/station` | ✚ | The fail-closed bind runs inside `build_app` **before any route is wired** — that is precisely why `scout/cli.py` carries its `bind_guard` exception. MapLibre tags are SRI-pinned; token injection uses `_webpage.js_literal`, never bare `json.dumps` (`</script>` inside a token would terminate the block) |
| `.../src/meshsa/ui` | ✚ | The I-2 read-only route contract is asserted by a route-table test; adding a mutating route breaks it. Handlers run single-threaded on the pump loop — **no locks, no threads**. An absent optional source means the route is not registered. No `innerHTML` sink anywhere |
| `.../src/meshsa/inference` | ✚ | Must keep working with no `aiohttp` installed when a transport is injected. `as_dict()`'s drop counters feed `meshsa_inference_*` only when `node.inference_service` is set. `_is_ai_insight` is the loop guard that stops the service re-ingesting its own output |
| `.../src/meshsa/llm` | ✚ | **Every tool is read-only** — the model can never arm, set a mode, or publish a track; the hand-rolled loop exists so all dispatch goes through `ToolDispatcher`. Upstream failures return a generic `_UPSTREAM_ERROR`, detail server-side only |
| `packages/meshsa/tests` | ✚ | Fakes only — no radios, sockets, or live TAK. The Hypothesis `ci` profile is `derandomize=True, database=None` so the gate is reproducible. The 97% floor applies to *any* pytest invocation |
| `packages/jetson_yolo_gcs/src/jetson_yolo_gcs` | ✚ | **[corrected]** The per-path failure policy in `Pipeline.step()` must not be collapsed: detection is drop-and-count, stream best-effort, tracking advisory, and `LANDING_TARGET` publish is **tolerated then escalated** — consecutive failures are counted and rate-limit-logged until they reach `publish_failure_tolerance`, then the exception re-raises. Fail-loud-on-first is only the `tolerance == 0` case. rev.1 said "fails loud", which would have told an agent to delete the tolerance window on the safety path |
| `.../src/jetson_yolo_gcs/mavlink` | ✚ | The safety write path: advisory only, off by default, fail-closed heartbeat gate requiring a bidirectional endpoint. Freshness uses a monotonic clock; `LANDING_TARGET.time_usec` uses the wall clock — two deliberately distinct timebases. Mirrors `meshsa.command.health` **without importing meshsa** |
| `packages/jetson_yolo_gcs/tests` | ✚ | `tests/unit/test_imports_clean.py` is a hard architectural gate: it pops the heavy modules from `sys.modules`, imports the package, and asserts none reappeared. Any top-level heavy import anywhere in `src/` fails here |
| `tools/claude_hooks` | ✚ | `scope_freeze.py` must keep failing open on malformed payload or unreadable config; CI and review are the backstop. All policy comes from `governance.yaml`, never from code. `bind_guard`'s `SCAN_GLOBS` excludes `tools/**/tests/**` and `bind_guard.py` itself **[corrected: added]** |
| `scripts` | ✚ | Step 17 probes the `.agents/*`-vs-`.agents/` `.gitignore` trap — the directory form silently untracks every new skill. Step 9's subshell is deliberate: the old `cd … && cd -` form left cwd inside `packages/meshsa` on failure and silently skipped the jetson suite. **[corrected]** Its own command is `pnpm --filter @workspace/scripts run typecheck`; `make validate-pre-pr` is the *root* Makefile's target, i.e. the parent's |

### Tier 3 — guard files (6 files, ≤12 lines, no diagram)

Three sit in the **parent** of the directory they warn about, because `clean: true` would
delete a guide placed inside it (D-12).

| Path | | Trap |
| ---- | - | ---- |
| `lib/api-zod/src` | ✚ | Warns about the `generated/` child: orval output, wiped by `clean: true` on every codegen. Edit `lib/api-spec/openapi.yaml` and regenerate |
| `lib/api-client-react/src` | ✚ | Warns about the `generated/` child, and that the sibling `custom-fetch.ts` is hand-written, load-bearing, and **outside** the `clean` scope — its React-Native workarounds must not be "simplified" |
| `artifacts/mockup-sandbox/src` | ✚ | Warns about the `.generated/` child, rewritten by `mockupPreviewPlugin.ts` on every dev and build. **[corrected]** The file is tracked; the module map inside it is empty because `src/components/mockups/` does not exist |
| `artifacts/mockup-sandbox/src/components/ui` | ✚ | **[corrected]** 55 vendored shadcn/ui files (not ~70) that read as hand-written — regenerate via the shadcn CLI, do not refactor |
| `packages/meshsa/tests/snapshots` | ✚ | Golden wire-format fixtures; regenerate with `MESHSA_UPDATE_SNAPSHOTS=1`. A diff here means the wire format changed and needs a `meshsa.version` decision |
| `archive` | ✚ | Read-only ZIP snapshots. **[corrected]** Excluded from `ruff`, `ruff-format` and `mypy` only — `gitleaks`, `trailing-whitespace`, `end-of-file-fixer`, `check-added-large-files` and `detect-private-key` all still see it, and the exclusion lives in the invocations, not in `ruff.toml` |

**Totals**: 35 `AGENTS.md` (5 exist → 30 new). 34 paired `CLAUDE.md` (1 exists → 33 new)
— `.claude/` is exempt per T-0.5.

### Deliberately uncovered

**[corrected — rev.1's list was not exhaustive, which defeated its purpose.]** Every
directory carrying tracked files and holding no guide is below.

| Path | Why not |
| ---- | ------- |
| `packages/meshsa/src/meshsa/command` | **Cannot hold one.** Inside `command_emission_globs`; `match_globs` uses `fnmatch`, so the scope-freeze hook denies a write to `command/AGENTS.md` exactly as to `command/lifecycle.py` (D-11, verified). Guidance lives in the parent |
| `packages/meshsa/src/meshsa/{examples,cv}` | `examples/` is a one-file re-export shim. `cv/` has one real rule (stdlib `math` only, because a heavy detector process imports it) which the parent states |
| `packages/meshsa/src/meshsa/fpv/tools` | Three console scripts; no trap beyond `fpv/`'s |
| `packages/meshsa/tests/e2e` | One module; its `e2e` marker and gating are stated in `packages/meshsa/tests` |
| `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/{core,detection,geometry,streaming,tracking,utils}` | Real invariants, but the package guide already states them and the package is small. Revisit only if that file outgrows its budget |
| `packages/jetson_yolo_gcs/tests/{unit,integration}` | Covered by `packages/jetson_yolo_gcs/tests`; `test_imports_clean.py` lives in `unit/` and is named there |
| `packages/jetson_yolo_gcs/docs/architecture` | Documentation; `docs/` conventions apply |
| `flightctl/{configs,constraints,llm,scripts,sim,systemd,udev}` | Covered by `flightctl/AGENTS.md`. `llm/` is an ops README for `meshsa.llm`, whose trap is stated in that package's guide |
| `lib/{api-spec,api-zod,api-client-react,db}`, `artifacts/{api-server,mockup-sandbox}`, `artifacts/*/.replit-artifact` | Covered by the Tier 1 parents plus the Tier 3 guard files |
| `ops/{base-service,observability,pi5-node}`, `hardware/{gcs-stls,usernode-stls,vcase}` | Covered by the existing Tier 1 guides |
| `docs/{adr,architecture,specs,superpowers/plans}`, `openspec/changes/**`, `.github/{agents,workflows,ISSUE_TEMPLATE}`, `.claude/{agents,hooks}`, `tools/tests`, `tools/claude_hooks/tests`, `scripts/hooks` | Covered by their Tier 1/2 parents |
| `.agents`, `.agents/skills/*` (12) | **Claude Code never reads anything under `.agents/` as project instructions** (D-6), so a guide there could never load, and the directory has no Tier 1 parent to anchor a breadcrumb. Its two traps — the `.gitignore` `.agents/*` form and the SKILL.md frontmatter contract — move to `scripts/AGENTS.md` (which owns the probe) and the root delegation table |

## Phase 0 — Bundle and preconditions

- [ ] T-0.1 This bundle (`proposal.md`, `design.md`, `tasks.md`, `specs/agent-governance/spec.md`),
      plus `docs/AGENTS_MD_EVIDENCE.md` and `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md`.
      Register the change in `docs/specs/README.md`'s table.
- [ ] T-0.2 Confirm the three open calls in `proposal.md` with the maintainer. Recorded
      defaults hold if no answer comes.
- [ ] T-0.3 Verify `.github/CODEOWNERS` covers `**/AGENTS.md` and `**/CLAUDE.md`. It is
      `* @ianshank` today, which does; this task fails the phase if that changes, because
      D-9's threat model is an unreviewed PR contributor.
- [ ] T-0.4 **Security precondition, not documentation.** `artifacts/api-server` binds all
      interfaces with no auth, is absent from `docs/AUDIT_M2_AUTH.md`, and sits outside
      `bind_guard`'s Python-only `SCAN_GLOBS` — all verified. Add the audit row (bind,
      port, auth, encryption, fail-closed) and raise the remediation as its own decision.
      **`artifacts/AGENTS.md` does not land until this row exists**; a Tier 1 guide whose
      trap list omits an unauthenticated listener is worse than no guide.
- [ ] T-0.5 Record `.claude/` as exempt from the paired-stub rule. `.claude/CLAUDE.md` is
      a **repo-root-scope** instruction file by Claude Code's own resolution order (D-6),
      so creating one as a directory stub would add a second root-scope memory file with
      undefined precedence and break the "+0 tokens at session start" property.

## Phase 1 — Contract, checker, gates, and a green tree of five *(review stop point)*

- [ ] T-1.1 `.agents/skills/agents-md-authoring/SKILL.md` — the D-3 contract, the five
      content rules, the D-5 diagram policy, per-tier budgets, and the "≤15 nodes, one
      concept" prose guidance. Frontmatter `name`/`description` (opening `Use when:`)/
      `argument-hint`. Must pass `python tools/validate_skills.py` — so it must **not**
      cite `tools/validate_agents_docs.py` or `.claude/agents/docs-cartographer.md` in
      backticks, since that checker fails on paths that do not exist yet and both land
      later in this phase. Cite them in prose; backtick them in T-1.6.
- [ ] T-1.2 `.claude/agents/docs-cartographer.md` — detector, not author (D-8b). No
      `Write`, no `Edit` in `tools:`. `Relationship:` cites T-1.1's skill. ≤60 lines.
      Must pass `python tools/validate_workforce.py`.
- [ ] T-1.3 `tools/validate_agents_docs.py` — checks 1–14 per design §D-7. Stdlib-only,
      standalone, `TIER_MANIFEST` as a module constant (never `governance.yaml` — D-7).
      Enumerate via `git ls-files`, not `rglob`. Check 5 is **new logic**, not a copy of
      `validate_skills.py`; check 10 is normalised exact-match plus a negation detector,
      not a fuzzy ratio; check 8 disambiguates the two Makefiles by `-f`.
- [ ] T-1.3b Extend `validate_skills.py::CHECKABLE_PATH_PREFIXES` with `lib/`,
      `artifacts/`, `scripts/`. Without this, check 5 is blind on exactly the guides whose
      whole content is "this path is generated, edit that one instead", and the existing
      skills linter shares the gap.
- [ ] T-1.4 `tools/tests/test_validate_agents_docs.py` — one failing case per check plus a
      clean-tree pass. Assert the `OK:` prefix and compare against `len(TIER_MANIFEST)`;
      do **not** hard-code a file count, or all 30 guide-adding commits must edit the
      literal. Import via `import tools.validate_agents_docs` (the convention that
      survives `mypy flightctl/ tools/`).
- [ ] T-1.5 Wire the gate **now, not in Phase 6**: add the checker to `tools/Makefile`'s
      `checkers` target (and its `help` text) and to the CI `governance` job after
      "Skills playbook lint". rev.1 wired these last, leaving ~30 guide-adding commits
      verified only by a human remembering to run a script.
- [ ] T-1.6 Retrofit the five existing guides to the D-3 contract with `TIER_MANIFEST`
      listing only those five; land the root `@AGENTS.md` import and four three-line
      stubs in the same commit. All five files are genuinely rewritten, not reorganised —
      none currently has a single canonical H2. `packages/jetson_yolo_gcs/AGENTS.md`
      sheds its pipeline-failure-policy block to `docs/specs/initiative-d-perception.md`
      and cites it with a reason to read. CI green.

> **Stop for review.** If the contract is wrong, it is wrong on five files with the
> checker already running under CI conditions — which is also when check 5's
> `packages/meshsa[dev,meshtastic]` false positive surfaces, in the commit that can
> cheapest fix it.

## Phase 2 — Root guide

- [ ] T-2.1 Root `AGENTS.md`: fold "Agent Skills" + "Custom Agents" + "Subagent roster"
      into one `## Subagents` delegation table; add `## Traps`; add the repo-map diagram
      (D-5); extend the Repository Map to the seven directories it currently omits.
      Budget 170 (D-4).
- [ ] T-2.2 Add the defensive injection directive to the root guide (D-9.3). Three lines;
      ~60% measured ASR suppression (E-5). State in the file that it is a soft layer.
- [ ] T-2.3 Root `CLAUDE.md` keeps its six Claude-specific notes below the import and is
      exempt from the stub contract (D-6), recorded in the delta rather than left to
      collide with check 9.

## Phase 3 — Tier 1 *(review stop point)*

One commit per domain. Manifest entry, guide, and paired stub land together.

- [ ] T-3.1 `flightctl/AGENTS.md` — diagram: bring-up ordering with the bind-first
      constraint annotated.
- [ ] T-3.2 `lib/AGENTS.md` — diagram: `openapi.yaml` → orval → two generated trees, with
      `clean: true` annotated.
- [ ] T-3.3 `artifacts/AGENTS.md` — **blocked on T-0.4.**
- [ ] T-3.4 `tools/AGENTS.md` — diagram: `governance.yaml` → hooks + checkers → CI.
- [ ] T-3.5 `docs/AGENTS.md` — the reading order, and the two-C4.md trap.
- [ ] T-3.6 `openspec/AGENTS.md` — the delta format and the checkbox-parser trap.
- [ ] T-3.7 `deliverables/AGENTS.md`.
- [ ] T-3.8 `.github/AGENTS.md`.
- [ ] T-3.9 `.claude/AGENTS.md` — no paired stub (T-0.5).

> **Stop for review.** Confirm each diagram encodes a constraint, not a structure.

## Phase 4 — Tier 2

- [ ] T-4.1 `packages/meshsa/src/meshsa/` incl. the `### command/ (frozen)` subsection
      (D-11). `MESHSA_GOVERNANCE_OVERRIDE` is not used.
- [ ] T-4.2 `transports/`.
- [ ] T-4.3 `fpv/`, `fpv/crsf/`.
- [ ] T-4.4 `scout/`, `scout/station/`.
- [ ] T-4.5 `ui/`, `inference/`, `llm/`.
- [ ] T-4.6 `packages/meshsa/tests/`.
- [ ] T-4.7 `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/`, `.../mavlink/`, `.../tests/`.
- [ ] T-4.8 `tools/claude_hooks/`, `scripts/`.

## Phase 5 — Tier 3 guard files

- [ ] T-5.1 The six guard files, three of them in the parent of the generated directory
      they warn about (D-12). Each is written individually with `Write`; **no bulk
      generator script** — `scope_freeze.py` only observes `Write|Edit` with a
      `file_path`, so a `Bash` generator writes through a path the only `PreToolUse`
      control cannot see. rev.1's T-5.2 proposed exactly that.

## Phase 6 — Remaining wiring

- [ ] T-6.1 `scripts/validate-pre-pr.sh`: add `step_agents_docs_lint` after
      `step_skills_lint` (**[corrected]** — rev.1 named a `step_validate_skills` that does
      not exist), and renumber the header comment's step list, including the
      "Steps 10-17 are the T-2.2b governance gate" line that the insertion invalidates.
- [ ] T-6.2 `.pre-commit-config.yaml`: a local hook on `AGENTS.md`/`CLAUDE.md` changes.
- [ ] T-6.3 `.claude/governance.yaml`: add the `agents_docs` declared-exception block
      (`{path, rule, rationale}`), Optional-with-default so an absent section cannot break
      the loader the command freeze depends on.
- [ ] T-6.4 `CONTRIBUTING.md` checklist line (D-13), the per-developer `instructionFiles`
      note (D-6), and a `CHANGELOG.md` entry.

## Explicitly deferred (separate changes)

- Remediating the `artifacts/api-server` bind itself. T-0.4 **documents and audits** it;
  changing the listener is a code change outside this bundle's scope and needs its own
  decision.
- Extending `bind_guard` to TypeScript. The Python-only `SCAN_GLOBS` is why T-0.4's
  surface went unnoticed, but widening a governance linter to a second language is its
  own change with its own false-positive surface.
- Guides for `federation/**` and `storeforward/**`. Both are in `scope_widening_globs`
  and neither directory exists.
- Any `docs/architecture/` structure diagrams displaced from guides by D-5. Authoring
  them is follow-on work; this bundle only stops them landing in always-loaded files.
- Automated smell detection beyond what a stdlib checker can decide. Four of E-7's six
  smells need an LLM; this bundle does not pretend otherwise.

## Verification

Per commit:

```bash
python tools/validate_agents_docs.py
make -f tools/Makefile checkers
```

Tasks touching `tools/` additionally:

```bash
ruff check tools && ruff format --check tools
mypy flightctl/ tools/ --exclude archive
python -m pytest tools/claude_hooks/tests tools/tests -q
```

Before the PR: `make validate-pre-pr`.

## Risks

| Risk | Mitigation |
| ---- | ---------- |
| A guide states an invariant the code contradicts | Exactly what adversarial review caught twice in rev.1 (the `LANDING_TARGET` policy, the PyYAML pin claim). Every cell is re-verified against the tree; `security-reviewer` reviews before the PR; checks 5 and 8 catch reference rot but **not** a plausible-and-wrong sentence — that is why the review stop points exist |
| 69 new trusted-context files widen the injection surface | D-9: checks 11 and 13, the defensive root directive, verified CODEOWNERS |
| Guides go stale | Rationale makes rules deletable (D-3.1); budgets force editing (D-4); `docs-cartographer` detects and proposes (D-8b) |
| The checker's own false positives train contributors to ignore it | Check 10 was measured and rewritten; check 5 given real logic; declared exceptions in `governance.yaml` |
| The tree costs more context than it saves | Only the root loads at launch; scoped guides load on demand, which measurably beat always-on injection (E-2) |
| No evidence supports nested guides at all | Stated plainly in the proposal. The bet is bounded at 35 files and reversible file-by-file |
