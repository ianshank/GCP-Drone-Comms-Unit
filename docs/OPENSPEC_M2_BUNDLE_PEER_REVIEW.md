# Peer Review — `gcp-drone-m2-agent-hardening` bundle (rev.1 → rev.2)

Date: 2026-07-24. Reviewer: agent-driven, every claim verified against the
tree (two independent verification passes: docs claims, code claims). Method
and format follow the bundle's own security-reviewer rules — confidence tags,
severity order, negative claims verified by search, what-survives listed.
The corrected bundle (rev.2) is materialized under
`openspec/changes/gcp-drone-m2-agent-hardening/` and implemented in the same
PR that adds this record.

**Verdict:** rev.1's architecture (guardrails before agents, additive
bootstrap, scope freeze, per-gap deltas) was sound and its core security facts
verified. It failed its own review standard in five places — including a
`[Certain]` tag on a wrong number — cited enforcement machinery that did not
exist, built a phase on a citation that appears nowhere in the repo, and
missed one genuine weakness its audit-driven framing should have caught.

## Findings (severity-ordered)

- **F-1 [Certain] — false premise: the arXiv "re-filing".** rev.1 proposed
  "re-filing" a finding about arXiv 2607.20280 (and deferred "SkyEV"
  2607.18747). Exhaustive search: **no arXiv citation of any kind exists in
  this repository** — there was nothing to re-file, and `2607.xxxxx` is not a
  plausible arXiv identifier. The underlying soak idea was legitimate and
  already queued (`docs/specs/README.md`: `m2-soak-fuzz.md`; ROADMAP M2
  "soak/fuzz on real radios"). rev.2 anchors the phase there and drops the
  citation. Standing rule added to the deferred list: external research is
  adopted only with a verifiable citation checked into `docs/` first.
- **F-2 [Certain] — missed gap: duplicated, weaker commander bind guard.**
  `flightctl/run_commander.py` defined a local `validate_bind` with predicate
  `token is None` (an empty token passed when the function was called as an
  API; `main()` normalized `""`→`None`, so the CLI path was safe) and imported
  auth helpers from `meshsa.llm.server` instead of `meshsa.netauth` —
  contradicting the audit's single-primitive claim. Fixed: delegating adapter
  over `meshsa.netauth.validate_bind` + empty-token regression test + a
  bind-guard CI rule that flags non-delegating re-definitions.
- **F-3 [Certain] — misattributed invariant.** The "no unauthenticated
  surface by default" invariant lives in `ROADMAP.md` (M2 security
  invariant), not CHARTER; CHARTER's related clause is the commanding
  carve-out. CHARTER §6 is "How agents use this document" (the "does not flip
  a switch" language is §3) — rev.1 described §6 as a gate-decision section.
  rev.2 sources both correctly.
- **F-4 [Certain] — wrong numbers under a `[Certain]` tag.** rev.1 claimed
  committers "Reorg Agent (62), Claude (55)". Actual `git shortlog -sn`:
  Reorg Agent 68, Claude 67, Ian Cruickshank 49 — a one-commit plurality.
  The agent-heavy-repo argument survives; the false-precision does not.
- **F-5 [Certain] — cited controls that did not exist.** (a) Ruff `PLR2004`
  is not enabled (all configs select `E,F,I,UP,B,SIM`); (b)
  `validate_workforce.py` did not exist; (c) the "netauth/pacing 100%-cov
  standard" was half-true — pacing's 100% is documented, `netauth` had **no
  direct test file**, and the enforced gates are package-wide 97%/96%. rev.2
  recast all three as deliverables: the workforce validator now exists and is
  CI-run; `test_netauth.py` now exists; `PL` enablement is explicitly a
  deferred maintainer decision.
- **F-6 [Likely] — roster ignored existing agent infrastructure.**
  `.github/agents/` (five custom agents) and `.agents/skills/` (playbooks)
  already exist. rev.2 requires every roster entry to declare a
  `Relationship:` to them (validator-enforced), preventing a parallel
  hierarchy.
- **F-7 — precision errors.** "16 surfaces" is 16 audit rows (four are
  serial/non-network/nonexistent); the audit table has no separate file:line
  column; surface #14's defaults live in `core/config.py` (`StreamSettings`),
  not `gstreamer.py`, and are *outbound to loopback* — a real gap, lower
  severity than "on by default" implied; the `openspec` CLI is not installed,
  so `validate --strict` is a deliverable, not a precondition.
- **F-8 — drift found during verification** (fed into this PR):
  `NEXTSTEPS.md` still claimed no autopilot-heartbeat gate existed (the gate
  shipped; fixed), and the generated `egg-info/PKG-INFO` advertises a stale
  coverage number (build artifact; regenerates).

## What survived review unchanged

Surface #10's characterization and remedy; the transport-wide auth gap and
its recommendation; the four fail-closed `netauth` HTTP surfaces; the
NEXTSTEPS "do not ship a command surface before TLS + auth land" quote (line
number exact); the TAK inherent-multicast exception (kept flagged, not
waived); the LANDING_TARGET fail-closed pattern as the generalization
template; the Initiative-C gate posture (implemented, unit-tested, no entry
point, no unit file; clearance is a maintainer decision); guardrails-before-
agents ordering; the entire scope-exclusion list.
