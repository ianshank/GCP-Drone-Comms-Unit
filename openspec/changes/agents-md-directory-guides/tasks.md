# Tasks — agents-md-directory-guides

> Order binding. Each task: write → `python tools/validate_agents_docs.py` clean →
> `make -f tools/Makefile checkers` clean → commit. `tasks.md` is updated in the same
> commit as the work it tracks (`tools/check_task_sync.py` reconciles it against git
> history as an advisory check). Explicit review stop points after **T-1** and **T-3**.
> No task in this bundle touches source, a transport, a bind, or the command path.

## Tier manifest

`✎` = exists, retrofit to the D-3 contract. `✚` = new.
"Why it qualifies" is the D-2 test: **C** = own command, **I** = own invariant,
**B** = hidden boundary. A directory needs at least one.

### Tier 0 — root (1 file, ≤150 lines, Mermaid required)

| Path | | Why it qualifies |
| ---- | - | ---------------- |
| `.` | ✎ | Repo-wide truth; gains the repo-map diagram and the delegation table |

### Tier 1 — domain roots (13 files, ≤80 lines, Mermaid required)

| Path | | Why it qualifies |
| ---- | - | ---------------- |
| `packages/meshsa` | ✎ | **C** `cd packages/meshsa && python -m pytest` · **I** `src` layout, coverage floor 97, `mypy --strict`, ruff/mypy pins enforced by `check_tool_pins.py` |
| `packages/jetson_yolo_gcs` | ✎ | **C** gates run from the package dir · **I** coverage floor 96, **no runtime dependency on `meshsa`**, `norfair` pins `numpy<2` |
| `flightctl` | ✚ | **C** `shellcheck`/`bash -n`, `mypy flightctl/ tools/` as one invocation · **I** bring-up order is load-bearing (mavp2p `udpc` consumers must bind first) · **B** `run_commander.py` is write-denied by the scope-freeze hook |
| `lib` | ✚ | **C** `pnpm --filter @workspace/api-spec run codegen` · **I** composite `dist/` must be built before `pnpm -r run typecheck` · **B** three `generated/` trees |
| `artifacts` | ✚ | **C** per-package `dev`/`build`/`test` · **I** `PORT` (and `BASE_PATH`) throw by design; esbuild `banner`/`external` are load-bearing · **B** `.replit-artifact/artifact.toml` is a deployment manifest |
| `ops` | ✎ | **C** shell-lint only · **I** idempotent scripts, `SIGINT` graceful shutdown, no real credentials in tracked env files |
| `hardware` | ✎ | **I** never hand-edit binary STL/PNG; regenerate · **B** `pi5_node_*` assets are duplicated with `ops/pi5-node/` |
| `tools` | ✚ | **C** `python -m pytest tools/claude_hooks/tests tools/tests` · **I** coverage measured-not-gated, PyYAML pins must match CI exactly · **B** policy-as-code: this is where the gates live |
| `docs` | ✚ | **I** a feature without a committed spec does not merge; code cites specs by `§` so renumbering breaks references · **B** `docs/C4.md` and `docs/architecture/C4.md` are different documents with the same filename |
| `openspec` | ✚ | **C** `python tools/check_task_sync.py` · **I** strict house delta format; no bundle may flip `c_gate_met` |
| `deliverables` | ✚ | **C** its own `mypy deliverables/` pass · **I** `xfail(strict=True)` is the contract; inlined reference implementations must **not** be DRY'd · **B** retirement in progress — do not build on it |
| `.github` | ✚ | **I** all third-party actions SHA-pinned; the three mypy passes must stay separate; gitleaks version+checksum must match pre-commit · **B** `fts-e2e.yml` targets a runner that does not exist yet |
| `.claude` | ✚ | **I** `governance.yaml` rejects unknown keys; only a maintainer flips `c_gate_met`; hooks must fail open · **B** roster frontmatter contract enforced by `validate_workforce.py` |

### Tier 2 — subsystems (16 files, ≤60 lines, Mermaid only where a flow is non-obvious)

| Path | | Why it qualifies |
| ---- | - | ---------------- |
| `packages/meshsa/src/meshsa` | ✚ | **I** `build_node()` deliberately skips unknown transports; `Router` splits `schema_mismatch` from `dropped_undecodable`; `defaults.py` is the sole literal table; `netauth.validate_bind` is the sole bind check |
| `.../src/meshsa/transports` | ✚ | **I** register via `@transport_registry.register` at import time, never by editing router/node; receive-only sources keep `send()` a no-op · **B** `tak_multicast.py` is a declared `bind_guard` exception, not a waiver (Mermaid: registration path) |
| `.../src/meshsa/fpv` | ✚ | **I** `import meshsa.fpv` must never require the `[fpv]` extra; `DATASET_SCHEMA` is a **separate** version namespace from `SCHEMA_VERSION`; `ArmGuard` is a ratified §3 carve-out — retiring it is a §6 decision |
| `.../src/meshsa/fpv/crsf` | ✚ | **I** CRC8/DVB-S2 over `[type]+payload` only; telemetry big-endian vs RC LSB-first 11-bit; both echo-suppression rules required; `telemetry.py` held at 100% coverage |
| `.../src/meshsa/scout` | ✚ | **B** CHARTER §3 offline-survey carve-out: inert files only, never uploads/arms/commands · **I** unprojectable detections are dropped-and-counted, never fabricated; seeded RNG for replay determinism |
| `.../src/meshsa/scout/station` | ✚ | **I** fail-closed bind inside `build_app` before routes are wired (this is what lets `scout/cli.py` carry its exception); SRI-pinned CDN tags; `_webpage.js_literal`, never bare `json.dumps` |
| `.../src/meshsa/ui` | ✚ | **I** I-2 read-only route contract asserted by a route-table test; single-threaded on the pump loop — **no locks, no threads**; absent source ⇒ route not registered; no `innerHTML` sink |
| `.../src/meshsa/inference` | ✚ | **I** works with no `aiohttp` when a transport is injected; `as_dict()` drop-counter contract feeds `meshsa_inference_*`; `_is_ai_insight` loop guard |
| `.../src/meshsa/llm` | ✚ | **I** every tool is read-only — the model can never arm, set a mode, or publish a track; generic `_UPSTREAM_ERROR` to the browser, detail server-side only |
| `.../src/meshsa/cv` | ✚ | **I** pure stdlib `math`, no third-party deps (it is imported by a heavy detector process); returns `None` at/above the horizon — callers degrade, never fabricate |
| `packages/meshsa/tests` | ✚ | **C** `cd packages/meshsa && python -m pytest` · **I** fakes only; Hypothesis `ci` profile is derandomized with `database=None`; the 97% floor applies to *any* invocation |
| `packages/jetson_yolo_gcs/src/jetson_yolo_gcs` | ✚ | **I** the per-path failure policy in `Pipeline.step()` must not be collapsed: detection drop-and-count, stream best-effort, tracking advisory, **`LANDING_TARGET` fails loud** |
| `.../src/jetson_yolo_gcs/mavlink` | ✚ | **I** the safety write path: advisory only, off by default, fail-closed heartbeat gate; monotonic freshness vs wall-clock `time_usec` are deliberately distinct; mirrors `meshsa.command.health` **without importing meshsa** |
| `packages/jetson_yolo_gcs/tests` | ✚ | **I** `test_imports_clean.py` is a hard architectural gate — any top-level heavy import anywhere in `src/` fails here |
| `tools/claude_hooks` | ✚ | **I** `scope_freeze.py` must keep failing open; policy comes from `governance.yaml`, never from code; `bind_guard.py` scans `tools/**` including itself-adjacent files |
| `scripts` | ✚ | **C** `make validate-pre-pr` · **B** step-17 probes the `.agents/*`-vs-`.agents/` `.gitignore` trap; step-9's subshell is deliberate (the old `cd … && cd -` silently skipped the jetson suite) |

### Tier 3 — guard files (6 files, ≤12 lines, no Mermaid)

| Path | | Why it qualifies |
| ---- | - | ---------------- |
| `lib/api-zod/src/generated` | ✚ | **B** orval output; `clean: true` wipes the directory each run. Edit `lib/api-spec/openapi.yaml` and regenerate |
| `lib/api-client-react/src/generated` | ✚ | **B** orval output — but the sibling `src/custom-fetch.ts` is hand-written, load-bearing, and must not be regenerated away |
| `artifacts/mockup-sandbox/src/.generated` | ✚ | **B** written by `mockupPreviewPlugin.ts` on every dev/build; currently empty because `src/components/mockups/` does not exist |
| `artifacts/mockup-sandbox/src/components/ui` | ✚ | **B** ~70 vendored shadcn/ui files that read as hand-written — regenerate via the shadcn CLI, do not refactor |
| `packages/meshsa/tests/snapshots` | ✚ | **B** golden wire-format fixtures; regenerate with `MESHSA_UPDATE_SNAPSHOTS=1`. A diff here means the wire format changed |
| `archive` | ✚ | **B** read-only ZIP snapshots, excluded from every ruff/mypy/pre-commit gate |

**Totals**: 36 `AGENTS.md` (5 exist → 31 new), 36 paired `CLAUDE.md` (1 exists → 35 new).

### Deliberately uncovered

Recorded so "absent" is distinguishable from "forgotten":

| Path | Why not |
| ---- | ------- |
| `packages/meshsa/src/meshsa/command` | **Cannot hold a guide.** It is inside `command_emission_globs`, and `match_globs` uses `fnmatch`, so the scope-freeze hook denies a write to `command/AGENTS.md` exactly as it denies one to `command/lifecycle.py` (design §D-10, verified). Its guidance — the frozen status, the fail-closed ACK policy, the off-loop `fsync`, the deliberate `literal_guard` `"*"` exception — lives in `packages/meshsa/src/meshsa/AGENTS.md` under `### command/ (frozen)` |
| `packages/meshsa/src/meshsa/examples` | A one-file re-export shim kept for backward compatibility; the parent guide covers it |
| `packages/meshsa/src/meshsa/fpv/tools` | Three console-script entry points with no contract beyond `fpv/`'s |
| `packages/meshsa/tests/e2e` | One module; its `e2e` marker and gating are stated in `packages/meshsa/tests` |
| `.../src/jetson_yolo_gcs/{core,detection,geometry,streaming,tracking,utils}` | Each has real invariants, but `packages/jetson_yolo_gcs/AGENTS.md` (67 lines) already states them and the package is small. Revisit only if that file outgrows its budget |
| `flightctl/{configs,constraints,scripts,sim,systemd,udev}` | Covered by `flightctl/AGENTS.md`; none has a command or boundary the parent cannot state |
| `lib/{api-spec,api-zod,api-client-react,db}`, `artifacts/{api-server,mockup-sandbox}` | Covered by their Tier 1 parents plus the Tier 3 guard files where the boundary is invisible |
| `ops/{base-service,observability,pi5-node}`, `hardware/{gcs-stls,usernode-stls,vcase}` | Covered by the existing Tier 1 guides |
| `docs/{adr,architecture,specs,superpowers}`, `openspec/changes/*`, `.github/{agents,workflows,ISSUE_TEMPLATE}`, `.claude/{agents,hooks}` | Covered by their Tier 1 parents |
| `artifacts/*/.replit-artifact` | Single `artifact.toml` each; documented in `artifacts/AGENTS.md` |
| `deliverables/meshsa-ui-validation/*` | The whole tree is scheduled for deletion (`NEXTSTEPS.md` T-10.2b) |

---

## Phase 0 — Bundle

- [ ] **T-0.1** This bundle: `proposal.md`, `design.md`, `tasks.md`,
      `specs/agent-governance/spec.md`. No guide files land in this commit.
- [ ] **T-0.2** Confirm the two open calls in `proposal.md` with the maintainer:
      Tier 2 breadth (`cv/`, `llm/`) and the 36-file `CLAUDE.md` stub tree.
      Record the answers in `design.md` §D-2 / §D-6; the manifest above is the
      default if no answer comes.

## Phase 1 — Contract and enforcement *(review stop point)*

- [ ] **T-1.1** `.agents/skills/agents-md-authoring/SKILL.md` — the D-3 template,
      the four content rules, the D-5 Mermaid policy, and the per-tier budgets.
      Frontmatter `name: agents-md-authoring`, `description:` opening `Use when:`,
      `argument-hint:`. Must pass `python tools/validate_skills.py`.
- [ ] **T-1.2** `.claude/agents/docs-cartographer.md` — frontmatter per D-8b, body
      with the `Relationship:` marker citing T-1.1's skill, ≤60 lines. Must pass
      `python tools/validate_workforce.py`.
- [ ] **T-1.3** `tools/validate_agents_docs.py` — checks 1–10 from design §D-7.
      Stdlib-only, standalone, policy as module constants (the manifest above
      becomes `TIER_MANIFEST`), one finding per line, exit 1 on any finding.
      Reuses `validate_skills.py`'s `_TOKEN_STRIP` / `CHECKABLE_PATH_PREFIXES`
      path-citation approach.
- [ ] **T-1.4** `tools/tests/test_validate_agents_docs.py` — one failing case per
      check, plus a clean-tree pass. Matches the existing checker test style.
- [ ] **T-1.5** Retrofit the five existing files (`AGENTS.md`,
      `packages/meshsa/`, `packages/jetson_yolo_gcs/`, `ops/`, `hardware/`) to
      the D-3 contract, with `TIER_MANIFEST` listing **only those five**. Content
      is reorganised, not rewritten — every existing rule survives or moves to
      the root. CI green before proceeding.

> **Stop for review.** If the contract is wrong, it is wrong on 5 files, not 37.

## Phase 2 — Root and the Claude Code bridge

- [ ] **T-2.1** Root `AGENTS.md`: add the `## Map` repo diagram (≤15 nodes:
      the two Python packages, the TS workspace, flightctl, ops, the governance
      layer) and fold the existing "Agent Skills" + "Custom Agents" + "Subagent
      roster" sections into one `## Subagents` delegation table. Stay ≤150 lines.
- [ ] **T-2.2** Root `CLAUDE.md`: replace the markdown-link pointer with an
      `@AGENTS.md` import (design §D-6). Keep the Claude-specific notes below it.
      Verify with `claude --debug` that the import resolves, or with the
      `InstructionsLoaded` hook.
- [ ] **T-2.3** `CONTRIBUTING.md`: document the guide tree, the tier rule, and the
      optional per-developer `instructionFiles: claude-md-and-agents-md` setting
      (user or managed settings only — Claude Code ignores it in project settings).

## Phase 3 — Tier 1 *(review stop point)*

One commit per domain; extend `TIER_MANIFEST` in the same commit as each file.

- [ ] **T-3.1** `flightctl/AGENTS.md` — Mermaid: serial/UDP in → gateway → CoT out,
      with the bind-first ordering annotated.
- [ ] **T-3.2** `lib/AGENTS.md` — Mermaid: `openapi.yaml` → orval → the two
      `generated/` trees → `artifacts/api-server`.
- [ ] **T-3.3** `artifacts/AGENTS.md` — Mermaid: the two artifact units and their
      ports/manifests.
- [ ] **T-3.4** `tools/AGENTS.md` — Mermaid: `governance.yaml` → hooks + checkers →
      CI `governance` job.
- [ ] **T-3.5** `docs/AGENTS.md` — Mermaid: the reading order
      (CHARTER → ROADMAP → scoped guide → NEXTSTEPS → IMPLEMENTATION_PLAN → spec).
- [ ] **T-3.6** `openspec/AGENTS.md` — Mermaid: bundle shape and its relation to
      `docs/specs/`.
- [ ] **T-3.7** `deliverables/AGENTS.md`, `.github/AGENTS.md`, `.claude/AGENTS.md`.

> **Stop for review.** Confirm the diagrams say something `docs/C4.md` does not.

## Phase 4 — Tier 2

- [ ] **T-4.1** `packages/meshsa/src/meshsa/` + `transports/`, plus the
      `### command/ (frozen)` subsection inside the first of those. Per design
      §D-10, `command_emission_globs` is `.../command/**` and `match_globs` uses
      `fnmatch`, so a write to `command/AGENTS.md` **is denied** by the
      scope-freeze hook — the frozen path's guidance therefore lives in its
      parent, and `MESHSA_GOVERNANCE_OVERRIDE` is **not** used for a
      documentation file. `TIER_MANIFEST` records `command/` as covered-by-parent,
      not as a missing entry.
- [ ] **T-4.2** `fpv/`, `fpv/crsf/`.
- [ ] **T-4.3** `scout/`, `scout/station/`, `ui/`.
- [ ] **T-4.4** `inference/`, `llm/`, `cv/`.
- [ ] **T-4.5** `packages/meshsa/tests/`.
- [ ] **T-4.6** `packages/jetson_yolo_gcs/src/jetson_yolo_gcs/` + `mavlink/` +
      `tests/`.
- [ ] **T-4.7** `tools/claude_hooks/`, `scripts/`, `.agents/skills/`.

## Phase 5 — Tier 3 and the stub tree

- [ ] **T-5.1** The six Tier 3 guard files.
- [ ] **T-5.2** The 36 new paired `CLAUDE.md` stubs (design §D-6). Generated by a
      one-shot script, then committed as plain files — the stub is three lines and
      must not become a generated artifact with its own tooling.
- [ ] **T-5.3** Enable checks 1 and 9 (`TIER_MANIFEST` completeness, stub pairing)
      as errors rather than warnings, now that the tree is complete.

## Phase 6 — Gate wiring

- [ ] **T-6.1** `tools/Makefile`: add `$(PY) tools/validate_agents_docs.py` to the
      `checkers` target.
- [ ] **T-6.2** `scripts/validate-pre-pr.sh`: add a `step_validate_agents_docs`
      after `step_validate_skills`, and extend the header comment's numbered list.
- [ ] **T-6.3** `.github/workflows/ci.yml`: add an "Agent docs lint" step to the
      `governance` job after "Skills playbook lint".
- [ ] **T-6.4** `.pre-commit-config.yaml`: a local hook on `AGENTS.md`/`CLAUDE.md`
      changes.
- [ ] **T-6.5** `CONTRIBUTING.md` PR checklist line (design §D-11) and a
      `CHANGELOG.md` entry.

## Verification

Per commit:

```bash
python tools/validate_agents_docs.py
python -m pytest tools/tests/test_validate_agents_docs.py -q
make -f tools/Makefile checkers
```

Before the PR:

```bash
make validate-pre-pr
```

Documentation-only changes do not require the package test suites, but
`make -f tools/Makefile checkers` must be clean because T-1.3 adds a checker to
it. T-1.3/T-1.4 touch `tools/`, so `python -m pytest tools/claude_hooks/tests
tools/tests -q` and `mypy flightctl/ tools/ --exclude archive` apply to those
tasks specifically.

## Risks

| Risk | Mitigation |
| ---- | ---------- |
| The guides go stale and mislead an agent | Check 5 (cited paths) + check 8 (commands) fail CI; `docs-cartographer` owns refreshes; budgets force editing over appending |
| 37 guides cost more context than they save | Only the root loads at session start; scoped guides load on demand. Budgets are enforced, and check 10 rejects lines duplicated from the root |
| `command/AGENTS.md` is blocked by the scope-freeze hook | Resolved in T-4.1 by documenting the frozen path from its parent. Never override the hook for a docs file |
| The 36 stub files are judged too noisy | Fallback recorded in proposal §2: Tier 0/1 stubs only, accepting prose-only discovery below that |
| A future Claude Code default change makes the stubs redundant | They stay harmless — a three-line import that Claude Code skips if it has already loaded the target |
