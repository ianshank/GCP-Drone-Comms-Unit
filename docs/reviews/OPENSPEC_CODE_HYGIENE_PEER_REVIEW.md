# Peer Review — `code-hygiene-modularity` bundle (draft → accepted)

Date: 2026-07-30. Reviewer: agent-driven, findings verified against the tree (source reads
of `bind_guard.py`, `transports/__init__.py`, `CHARTER.md`, `governance.yaml`, and the
scout/fpv modules the audits flagged). The corrected bundle is materialized under
`openspec/changes/code-hygiene-modularity/` and implemented in the same PR that adds this
record.

**Verdict:** the underlying five-agent audit (meshsa core; jetson/flightctl/tools;
repo/workspace; `fpv`; `llm`/`command`/`scout`) was thorough and its findings held up under
verification — every bug cited in the proposal's "Why" section was independently confirmed
against source before being included. The first draft of the *implementation plan* built from
those findings introduced its own defects, five of which (R-9 through R-13 below) were caught
in this review before any code was written. One is a blocker: the draft would have violated
CHARTER Invariant 1.

## Findings (severity-ordered)

- **R-1 [Certain] — BLOCKER, would-be charter violation.** The `fpv` audit's dead-code list
  named `ArmGuard`, `crsf/rc.py`, `CrsfLink.send_rc`, `RCLink`, and `FlightLogger.record_rc`
  as unreferenced and safe to delete. Verified against `CHARTER.md` §3: these implement the
  **ratified 2026-06-12 pre-flight arm-gating carve-out** verbatim (*"the `meshsa.fpv`
  ground-side subsystem may transmit RC frames for the single purpose of a pre-flight safety
  interlock"*). The audit's "unreferenced" claim was correct — nothing wires it to a
  production entry point yet — but unreferenced is not the same as unwanted; deleting
  ratified capability through a hygiene commit is exactly what §6 reserves for a deliberate
  human decision. Fixed: task T-5.1 splits into 5.1a (genuinely dead surface — deleted) and
  5.1b (ratified surface — kept, marked, and raised as a `NEXTSTEPS.md` decision item for a
  maintainer to wire or formally retire).
- **R-2 [Certain] — MAJOR, charter amendment wording.** The user ratified a CHARTER §3
  amendment letting `jetson_yolo_gcs` depend on the new `meshsa-core` package, but the
  original carve-out's rationale — *"carries no runtime dependency on `meshsa`... so it
  remains usable as a standalone library"* — needed to survive the amendment, not just be
  overridden. Fixed: the amendment text (design D-2) explicitly preserves the rationale by
  noting `meshsa-core` itself has no `meshsa` framework dependency, so the standalone-library
  property still holds transitively.
- **R-3 [Certain] — MAJOR, sequencing.** The draft deferred all `docs/AUDIT_M2_AUTH.md`
  updates to a single docs-cleanup phase at the end. That leaves the audit inventory
  factually wrong for the entire duration of the program (e.g. describing a port the code no
  longer uses, or a canonical module that moved). Fixed: audit-row updates now land inside
  the same commit as the surface change they describe (T-1.4 port row, T-4.2 multicast path,
  T-7.2 canonical module).
- **R-4 [Certain] — MAJOR, verified against `bind_guard.py:186-205`.** The draft's plan for
  moving `netauth` said "add a re-export shim" without specifying the shim's exact shape.
  Read closely, the bind-guard single-primitive rule fires on any `def validate_bind` outside
  the canonical module unless it delegates — so a shim that re-declared the function (even
  trivially) rather than purely re-exporting it would trip the linter it's supposed to keep
  passing. Fixed: design D-4 specifies the shim as pure `from ... import ... as ...`
  statements with no `def` of its own, and the `canonical_module` config flip lands in the
  same commit, verified by actually running `bind_guard.py`.
- **R-5 [Certain] — MAJOR, security.** The draft's `ConfirmedCommand` type-narrowing idea was
  underspecified: a type alias with no gate-issued marker can be constructed directly,
  making the "narrowing" cosmetic rather than enforced. Fixed: design D-7 specifies
  `ConfirmedCommand` as gate-issued (carries a token stamped by the gate) and pins
  `confirmation_ttl_s=60.0`/`pending_cap=8` as named config fields rather than leaving the
  defaults unstated.
- **R-6 [Certain] — MAJOR, test integrity.** The unmerged sdnotify patch's own bundled tests
  were flagged by the audit as testing an inlined copy of the implementation rather than the
  package. The draft's task for applying the patch didn't call this out, risking the same
  mistake on re-application. Fixed: T-10.1 explicitly requires the new tests to exercise real
  `meshsa.ui` code.
- **R-7 [Minor] — soak coverage.** The draft's per-commit verification list didn't call out
  which commits touch backoff/heartbeat/transport-init/publish-policy code that the dedicated
  link-loss soak suite (`tests/test_link_loss_soak.py`) pins. Fixed: those specific tasks
  (T-3.5, T-4.2, T-4.5, T-5.2, T-7.2, T-7.3) now explicitly run the soak suite in addition to
  the default gate.
- **R-8 [Certain] — format.** The plan existed only as an internal planning document, not in
  the house OpenSpec bundle format the repo's `docs/specs/README.md` requires ("a feature
  without a spec does not merge") and the `gcp-drone-m2-agent-hardening` precedent
  established. Fixed: restructured into this bundle (proposal / design D-numbers / tasks
  T-numbers / ADDED-MODIFIED spec deltas).

### Defects found in the plan itself, not inherited from the source audits

- **R-9 [Certain] — BLOCKER, self-inflicted invariant violation.** The draft proposed making
  `packages/meshsa/src/meshsa/transports/__init__.py` import lazily, to close an `fpv`
  package-init import cycle the audit had flagged. That file's own first line documents its
  contract: *"Built-in transports (importing registers them)."* Import-time registration is
  what populates `transport_registry`; CHARTER Invariant 1 (open/closed registry
  extensibility) and `build_node()`'s skip-unknown-transport-type behavior (Invariant 2) both
  depend on that registry being populated before any code queries it. Making the import lazy
  would have silently emptied the registry for any caller that doesn't happen to trigger the
  lazy path first — a correctness regression the coverage suite might not even catch, since
  registration would still eventually happen, just not necessarily before first use. Caught
  before implementation: removed entirely. The cycle in question closes through two changes
  that don't touch transport registration — a dependency-free `meshsa/_logging.py` leaf (so
  `fpv/tools/*` stops importing the `meshsa` package root just to call `configure_logging`),
  and moving `HealthReport`/`HealthState` off `fpv.link_health` into a neutral module (which
  independently removes three of the cycle's five inbound edges from `command/*`).
- **R-10 [Certain] — MAJOR, verified by re-reading the scan target.** The draft's bind-guard
  glob-widening task said "add `tools/**/*.py`" without checking what that glob would match.
  Verified: `tools/claude_hooks/bind_guard.py` itself defines the six `LISTENER_TRIGGERS`
  patterns the scanner looks for, and `tools/claude_hooks/tests/test_bind_guard.py` contains
  eleven fixture strings using those same trigger patterns as test data. A naive widen would
  have the linter flag its own trigger definitions and its own test fixtures as violations —
  self-inflicted noise that would either block the gate-widening commit or force someone to
  add spurious exceptions. Fixed: the glob excludes `tools/**/tests/**` and
  `tools/claude_hooks/bind_guard.py` itself, with a pre-scan step to enumerate real findings
  before any fix is applied.
- **R-11 [Certain] — MAJOR, hidden behavior change.** The draft filed "`scout/cli.py` ignores
  22 env vars" under bug fixes without noting that fixing it is operator-visible. Verified:
  `SqliteStore` defaults to `:memory:`; an operator who has already set
  `MESHSA_SCOUT_STORE_PATH` in their deployment environment (reasonably assuming it takes
  effect, since it's documented as a wired variable) silently moves from a volatile in-memory
  store to a persistent file-backed one the moment this fix ships — and
  `MESHSA_SCOUT_STATION_TOKEN` starts being enforced where it previously was not. Fixed: T-1.5
  now requires its own explicit "operator-visible" CHANGELOG entry rather than being folded
  into a generic bug-fix line.
- **R-12 [Minor] — precision.** The draft described the `compact` codec fix as needing a new
  `SchemaGated` mixin. Verified against `compact.py:64`: `CompactCodec.__init__` already
  accepts and applies `supported_schemas` correctly — only the registry factory function
  (`_make_compact`) discarded keyword arguments via `**_: object`. The actual fix is a
  one-line `**kwargs` passthrough plus a registry-path regression test; `SchemaGated` is a
  separate, legitimate dedup (shared with `codec.py`) but is not what makes the bug fix work,
  and conflating them would have made a trivial fix depend on a larger refactor landing first.
- **R-13 [Certain] — MAJOR, reviewability.** The draft sequenced roughly 40 commits across 10
  phases with no stated delivery boundary. A single pull request of that size is not
  reviewably sized regardless of how well each commit is scoped internally. Fixed: the
  program lands as one draft PR against the fixed branch name, with explicit stop points
  after T-2, T-4, T-6, T-7, and T-8 for incremental review, and T-8 (the governance-frozen
  command zone) may be split to its own follow-up PR at the maintainer's request without
  disturbing the earlier phases' history.

## Verified during review and left unchanged

- Port `8088`'s only references outside `packages/meshsa/src/meshsa/config.py` and `cli.py`
  are four lines in `ops/observability/README.md` (including Prometheus scrape targets); no
  systemd unit or `*.env.example` file pins it. The port-move's blast radius is exactly those
  two files plus the audit row, as the draft assumed.
- `scout/replay.py` and `fpv/tools/replay.py` share a name and nothing else (one is a
  synthetic-flight generator with no CLI entry point, the other a complete offline-replay
  CLI) — the draft's rename-for-clarity task (T-6.4) is warranted, not a false-positive
  duplication finding.
- The four per-service `def validate_bind` adapters (`ui/app.py`, `scout/station/app.py`,
  `llm/server.py`, `health.py`) are correctly-shaped delegating adapters today and require no
  code change beyond the canonical-module pointer update — confirmed by reading each
  adapter's body against the linter's `_calls_any`/`_canonical_aliases` logic.

## What survives from the original five-agent audit, unmodified

Every verified bug in the proposal's "Why" §3 (no-store header, port collision, compact codec
kwargs, freshness-gate triplication, SRI/escaping divergence), the command-zone fail-closed
gaps in §4, and the gate-widening findings in §1 were re-confirmed during this review and
required no correction — only the plan for fixing them did.
