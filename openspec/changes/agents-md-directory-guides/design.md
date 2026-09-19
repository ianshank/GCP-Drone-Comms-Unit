# Design — Agent Trap Documentation (rev.4)

rev.1–rev.3 are superseded. `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md` records four review
rounds. Round 4 attacked the premise rather than the details and won: the change goes from
64 new files to 6. This document records what was reversed, and why, rather than quietly
dropping it — the reversals are the most useful thing in the bundle for whoever plans the
next one.

## D-0. Evidence baseline

All external claims cite `docs/AGENTS_MD_EVIDENCE.md` (E-1 … E-8): seven primary papers
read in full, plus the vendor documentation behind the loading claims, each entry tagged
with its significance or its status. Per the standing rule in
`docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md` F-1, no URL outside the register is citable here.

The register's closing section says plainly that **no controlled evidence exists either
way** for nested per-directory context files. rev.1–rev.3 built a 64-file tree on top of
that sentence. rev.4 does not.

## D-1. What was reversed

| # | rev.1–rev.3 held | Reversed because | Round |
| - | ---------------- | ---------------- | ----- |
| 1 | Overviews, maps and file inventories are the core content; Mermaid required | *"Context files do not provide effective overviews"* (E-1 §4.3), helpful only where no other documentation exists — the inverse of this repo | 2 |
| 2 | An LLM agent authors the guides | Developer-written beating LLM-generated is the **only** significant success-rate finding in the literature (E-1, p = 0.038) | 2 |
| 3 | The change is security-neutral | Instruction files are the highest-privilege injection entry point, loaded as trusted system context unchecked; threat model is a PR contributor (E-5) | 2 |
| 4 | Duplicate detection can be made to work | Measured twice. Fuzzy: a verbatim duplicate scores below every genuine non-duplicate. Exact: defeated by line-wrapping and partial copying | 2, 3 |
| 5 | Per-tier line budgets are the anti-accretion mechanism | Measured in-repo: the root grows **+16 lines/month**, monotone. A budget check converts a line count into a merge gate that fires within 60 days | 4 |
| 6 | 35 guides, tiered by trap density | ~7% payload density; 3.91 guides obligated per structural commit; **24%** observed compliance on the 6 files that exist today | 4 |
| 7 | Traps belong in always-loaded guides | ~55–60 of the 89 are procedure, which is Skill Leakage by the bundle's own cited definition (E-7), and `.github/copilot-instructions.md` already requires procedure to go to skills | 4 |
| 8 | Guard files go in the parent of a generated directory | That sacrifices the fire-on-open property the bundle itself called the guard file's entire purpose. `.claude/rules/` with `paths:` delivers it properly | 4 |

## D-2. The shape

Three layers, each doing what it is actually good at.

| Layer | Files | Loads | Holds | Read by |
| ----- | ----- | ----- | ----- | ------- |
| `AGENTS.md` × 5 | existing, modified | root at session start (via the import); scoped on demand | place-bound traps, rules, delegation | every tool |
| `.claude/rules/*.md` × 6 | new | on demand, when a `paths:` glob matches the file being touched | path-scoped ambient traps, incl. fire-on-open guards | Claude Code only |
| `.agents/skills/*` × 12+3 | existing, extended | on trigger | procedure and repeatable workflow | Claude Code only |

**Why not one layer.** Skills need a trigger match, so they cannot fire on incidental
contact with a generated file. Rules are Claude-only, so they cannot be the portable layer.
Guides load ambiently but cannot fire on a specific file without a per-directory tree,
which is what rounds 3 and 4 killed. Each layer covers the others' blind spot; none of them
needs a 33-file stub tree to do it.

## D-3. Content rules

Two survive from rev.3, each backed by a specific finding. Everything else — fixed section
order, per-tier required sets, line budgets, breadcrumbs, paired stubs — is withdrawn along
with the tree it existed to police.

1. **`— why:` on every rule.** Deletion hazard falls with instruction age because the
   rationale decays faster than the rule; 77.3% of instruction deaths are wholesale
   rewrites, because "removing one instruction needs a reason, removing all needs none"
   (E-3). Recording the reason removed 99.3% of excess size, and it is the **only** remedy
   in the literature independent of file count. That last property is why it survives a
   revision that cut file count by 90%.
2. **`— control:` or `— advisory` on every security rule.** Only ~4.4% of security rules in
   public instruction files have a matching built-in control, and nothing marks which
   (E-6): *"a write-only security channel."* This repo has `scope_freeze`, `bind_guard`,
   `literal_guard` and CI, so it can close the loop for the cost of one clause.

`## Traps` remains the headline section. A trap is a fact that costs an agent a wasted turn
or a wrong result — a gate that fires on a partial run, an ordering dependency, a file that
regenerates, a predicate that looks equivalent and is not. E-2 measured this as the only
content type with a surviving effect: the one repository whose file warned about test cost
cut blind full-suite runs 3.67 → 1.67 per task, wall-clock ~24%.

## D-4. Budgets are advisory, not gated

rev.3 enforced 12/60/90/170 lines. The measurement that killed it: the root `AGENTS.md`
grew 96 → 135 lines (+41%) in 73 days, monotone, **+16 lines/month**, and Step 1 lands it
at ~170. A gated budget therefore goes red in month 1–2, and a red `governance` job blocks
every PR until someone deletes prose unrelated to their change.

E-1 Appendix B is an explicit null on length, so the budget never had a performance
justification — only a forcing-function one. But E-3's own finding is that incremental
deletion does not happen; 77.3% of deletions arrive as wholesale rewrites, after which
growth *accelerates*. A budget therefore does not prevent the ratchet, it schedules the
rewrite that accelerates it.

rev.4 keeps the numbers as **authoring guidance** in the skill and drops the check. The
rationale requirement (D-3.1) is the mechanism that actually addresses the root cause.

## D-5. Making Claude Code load anything at all

Unchanged and still the highest-value item. Claude Code's default
`claude-md-or-agents-md` mode reads `AGENTS.md` *only* when no `CLAUDE.md`,
`.claude/CLAUDE.md` or `CLAUDE.local.md` exists at or above the working directory. This
repo has a root `CLAUDE.md` whose pointer is a markdown link, so **no `AGENTS.md` here is
loaded today**. `CLAUDE.md` gets an `@AGENTS.md` import (T-0.1).

**The 33-stub tree is withdrawn.** It existed to make nested guides load on demand; with no
nested guides, `.claude/rules/` provides the same lazy loading natively, in one directory,
with no pairing invariant to check. The root `CLAUDE.md` keeps its six Claude-specific
notes below the import.

**Rejected, still:** symlinking `CLAUDE.md` → `AGENTS.md` (Windows contributors are
supported; Git symlinks need Developer Mode and degrade under `core.symlinks=false`), and
`instructionFiles: claude-md-and-agents-md` (ignored in project and local settings, so it
cannot be committed for the team — worth one line in `CONTRIBUTING.md` as a per-developer
option).

**Reversed:** rev.2 rejected `.claude/rules/` in one clause, on the grounds that it splits
content from the tree other tools read. That rejection was inadequate. The plan had already
accepted a Claude-only channel — 33 stubs and an import — and `.claude/` already holds the
roster, `governance.yaml`, `settings.json` and a SessionStart hook without causing the
drift the clause feared. rev.4 uses rules for exactly the cases where lazy, path-scoped
loading is the point, and keeps `AGENTS.md` as the portable layer.

## D-6. The frozen path still cannot hold an instruction file

`.claude/governance.yaml` freezes `packages/meshsa/src/meshsa/command/**`, and
`governance.py::match_globs` uses `fnmatch.fnmatchcase`, whose `*` crosses `/`. Verified
against the real matcher:

```
packages/meshsa/src/meshsa/command/AGENTS.md  -> packages/meshsa/src/meshsa/command/**
packages/meshsa/src/meshsa/CLAUDE.md          -> None
```

The hook denies a write to a *documentation* file in the frozen directory exactly as it
denies one to `lifecycle.py`. That is correct — the freeze is path-shaped by design, and an
`*.md` carve-out is a hole someone eventually drives a module through. The frozen path's
traps live in `.claude/rules/meshsa-core.md`, which matches
`packages/meshsa/src/meshsa/**` and lives outside the frozen tree.
`MESHSA_GOVERNANCE_OVERRIDE` is not spent on Markdown.

## D-7. The checker

Four checks, ~120 LOC, third stdlib-only sibling of `validate_workforce.py` and
`validate_skills.py`:

1. **Instruction files on disk match the module-constant list**, enumerated with
   `git ls-files` rather than `rglob` — exact, no `node_modules` exclusion list, and it
   doubles as a trackability probe.
2. **Every cited path resolves.** Not a copy of the sibling: measured over the five
   existing guides, the sibling's logic emits **9 false positives**. Five corrections take
   it to 1: strip a trailing `[extras]`, reject bare-extension tokens (`.pt`, `.onnx`),
   reject absolute paths (`/metrics` is a route), add the nearest `src/<pkg>/` as a third
   resolution base, and allow declared counter-example citations.
3. **Control-character hygiene** — no bidirectional-override (U+202A-E, U+2066-9) or
   zero-width (U+200B-D) code points, checked by exact code point. This is the disclosed
   hidden-Unicode rules-file variant, in four lines. rev.3 also said "ASCII-dominant",
   which is undefined and self-defeating: the contract mandates U+2014 in every `— why:`
   clause and U+00B7 in every breadcrumb, and measured non-ASCII density across this
   bundle's own files spans 0.04–0.48%, so any threshold is a coin flip on whether the
   checker fires on its own required format. Dropped.
4. **`## Traps` present** in each of the five guides.

**Dropped, with the tree they policed:** canonical section order, line budgets,
breadcrumb-nearest-ancestor, Mermaid fence mechanics, subagent-name resolution,
dual-Makefile disambiguation, stub pairing, negation detection, action-directive grammar,
reverse coverage. Two of those were also measured unimplementable or unsound as specified
(the colliding-target scenario; duplicate detection).

**Policy lives in module constants.** rev.3 argued at length that the manifest must not
enter `governance.yaml`, because that file is loaded by a Pydantic `extra="forbid"` loader
and `scope_freeze.py` **fails open** on a config it cannot validate — so a documentation
typo could silently stop the Initiative-C freeze from denying. rev.3 then added an
`agents_docs` exception block to `governance.yaml` six tasks later. "Optional-with-default"
protects only the *absent* case; a present-but-malformed block still raises and still fails
open. rev.4 puts **nothing** documentation-shaped in that file (invariant I-2).

## D-8. Mermaid

Kept, narrowed. Structure diagrams belong in `docs/` — this repo already has `docs/C4.md`,
`docs/architecture/C4.md` and a package-local C4, and E-1 §4.3 measures overview content as
ineffective where documentation exists. A guide may carry at most one diagram, and only
where it encodes a constraint the code cannot show: bring-up ordering, codegen direction, a
governance gate.

Mandatory and verified against a renderer: `accTitle:` and `accDescr:` (they emit `<title>`
and `<desc>` with `aria-labelledby`/`aria-describedby`; without them a screen reader gets an
unlabelled graphic), plus a prose summary after the closing fence for readers with images
off. `flowchart` or `sequenceDiagram` only. The "≤15 nodes" rule is authoring guidance in
the skill, not a check — node count is not mechanically determinable without a Mermaid
parser, and rev.2's own canonical example was 4 nodes across 3 lines under a rule that
counted node lines.

## D-9. The tree is still a trusted-context surface

Smaller, not safer per file. E-5 measures instruction files as the highest-ASR injection
entry point: the harness *"treats AGENTS.md (and CLAUDE.md) as trusted system-level
instructions and loads them into the session without checking what they contain,"* with
reachability 1 by construction, under a threat model that names a **pull-request
contributor**. `.claude/rules/` files are the same surface. rev.4's win is arithmetic — 6
new files instead of 64 — not qualitative.

Controls, in order of load:

1. **`CODEOWNERS` review** (T-0.4). This is the load-bearing control. The scan E-5
   recommends belongs to the harness; a repository can only approximate it.
2. **Unicode hygiene** (check 3), against the disclosed hidden-Unicode variant.
3. **A defensive directive in the root guide.** rev.2 sold this as "~60% suppression of
   indirect-prompt-injection success". That **mis-scopes the source**: E-5 attributes the
   25.7% → 10.2% reduction to **EP2**, documentation-borne injection with the payload in an
   unrelated `README.md`. The surface here is **EP1**. The directive stays because it is
   three lines and does help a different entry point; it is not presented as mitigating
   this one.

rev.3's action-directive check (check 11) is dropped with the rest: measured at ~11% false
positives on legitimate trap prose, it is a speed bump E-5 itself says does not survive an
adaptive adversary, and it was buying that at the cost of firing on lines like *"Invoke the
shell linter over every tracked `*.sh`."*

Two honest limits carried forward. A prose rule is not a control (E-6), which is why D-3.2
requires each security rule to name the control that backs it. And E-5 found ASR falls with
codebase modularity — High bucket 26.5% versus Low 44.0%, with the config-driven
sub-dimension the strongest single predictor — and this repo is highly modular and
config-driven. That is the lower-risk regime, not immunity.

## D-10. Keeping it true

Three mechanisms, in order of strength — and note that the strongest is a person:

- **Review at the stop point.** The two defects that mattered most across four rounds — a
  wrong `LANDING_TARGET` policy on the safety write path, and an unaudited unauthenticated
  listener — were both found by reading code, and neither would have been caught by any of
  the 14 checks rev.3 proposed.
- **Rationale** (D-3.1) — the only mechanism that makes a rule deletable, and so the only
  one that addresses the ratchet at its cause.
- **Checker** (D-7) — reference rot and injection hygiene, four checks, on every PR.

`CONTRIBUTING.md` gains one line: *if a PR adds, removes, or moves a module in a folder
covered by an `AGENTS.md` or a `.claude/rules/` path glob, refresh that file's traps in the
same PR.* Measured compliance with the equivalent obligation today is 24%, so this is a
prompt, not a guarantee, and is written as one.
