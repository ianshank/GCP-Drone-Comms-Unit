# Design — Per-Directory `AGENTS.md` Guides (rev.3)

rev.1 and rev.2 are superseded. `docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md` records 29
findings across four rounds. Three inverted a rev.1 decision and are marked
**[inverted]**; round 3 was empirical — a checker spike plus two guides authored to this
contract — and its corrections are marked **[measured]**.

## D-0. Evidence baseline

All external claims cite `docs/AGENTS_MD_EVIDENCE.md` (E-1 … E-7), which holds seven
primary papers read in full, each claim tagged with its significance. rev.1 cited four
secondary blog summaries, **none of which were retrievable**, and reported a
non-significant result as measured harm. Per the standing rule in
`docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md` F-1, no URL outside the register is citable in
this bundle.

Three findings inverted rev.1:

| Finding | rev.1 believed | Evidence says |
| ------- | -------------- | ------------- |
| **[inverted]** Overviews, maps, file inventories | The core content; Mermaid required at Tier 0/1 | *"Context files do not provide effective overviews"* (E-1 §4.3). Helpful only where no other documentation exists (E-1 App. B) — the inverse of this repo |
| **[inverted]** An agent authors the guides | `docs-cartographer` writes and refreshes all of them | LLM-generated files are the **only** significantly worse condition measured (E-1, p = 0.038); also the Init Fossilization smell (E-7, 24%) |
| **[inverted]** The change is security-neutral | "Low risk — documentation only" | Instruction files are the highest-privilege injection surface, loaded as trusted system context unchecked, threat model = PR contributor (E-5) |

And one finding that rev.1 missed entirely, which now shapes the contract: the surviving
effect in the literature is **cost/ordering/trap warnings** — the one repository whose
file warned about test cost cut blind full-suite runs 3.67 → 1.67 per task and wall-clock
~24% (E-2). That is what a guide is *for*.

## D-1. The filename is `AGENTS.md`

Unchanged from rev.1 and confirmed by every paper in the register. The request said
`Agent.md`; nothing reads that name. `AGENTS.md` is what the four existing scoped guides
use and what the root guide tells agents to look for.

## D-2. Tiered coverage — a risk-managed bet, not an evidence-backed design

**No controlled study has evaluated nested per-directory context files.** E-1, E-2 and
E-4 all restrict to single-root configurations *by design*; E-2 filters on "exactly one
root AGENTS.md with no competing instruction stack"; E-4 says the restriction
"minimizes confounding effects from overlapping or conflicting instruction files."
rev.1's §D-0 cited blog posts about adoption ("Codex ships 88 of them") in an evidence
column. Adoption is not efficacy.

So the tiering is justified by *risk control*, not by measured benefit: 117 directories
carry tracked files; each guide is an always-trusted file in an injection surface (D-9)
and a contribution to the growth ratchet (D-4). A directory earns one only when it holds
a **trap** — something an agent gets wrong by default, that the parent guide cannot
state. Not "has interesting code". Not "would be nice to describe".

| Tier | What | Count | Budget | Diagram |
| ---- | ---- | ----- | ------ | ------- |
| 0 | Repository root | 1 | ≤170 lines | One, required |
| 1 | Domain roots with their own commands and traps | 13 | ≤90 lines | One, optional |
| 2 | Subsystems whose trap the parent cannot state | 15 | ≤60 lines | One, optional |
| 3 | Guard files — generated, vendored, read-only | 6 | ≤12 lines | Forbidden |

Budgets are **measured, not guessed** (R-1): a real `flightctl/AGENTS.md` authored to this
contract passes every check at exactly 80 lines, which is why Tier 1 moved from 80 to 90 —
a mid-density folder consumed the old budget entirely. A Tier 2 probe for
`packages/meshsa/src/meshsa`, carrying the `command/ (frozen)` subsection, came in at 53
against 60.

35 guides. `tasks.md` names the trap that earns each, and lists what was deliberately
left uncovered. Tier is depth of contract, not depth in the tree: `scripts/` is top-level
but Tier 2.

## D-3. The authoring contract

```markdown
# <Name> Agent Guide
> Scope: `<repo-relative path>` · Parent: [<../AGENTS.md>](../AGENTS.md)

## Purpose       1–2 sentences. Tier 0 and Tier 3 only (see below).
## Traps         REQUIRED, and first among the substantive sections.
## Rules         Imperative, verifiable, true ONLY here. Each carries a rationale.
## Commands      Only commands that differ from the parent's. Often absent.
## Subagents     Tier 0–2. Which roster agent / skill / mode owns work here.
## Map           Optional, ≤1 diagram, only where it encodes a constraint (D-5).
```

Tier 3 guard files carry `# <Name>`, the breadcrumb, `## Purpose`, `## Rules` only.
Per-tier required sets are tabulated in the spec delta, not left to prose — rev.1 omitted
them and made the section check unimplementable.

**`## Purpose` is not required at Tier 1 or Tier 2** (changed in rev.3). It is
repository-overview content, which E-1 measures as inert where other documentation
exists, and the measurement in D-2 showed it consuming budget a trap-dense folder needs.
A Tier 1 guide may still carry it, at its canonical position, when the folder's purpose is
genuinely non-obvious; it is optional, not forbidden. Tier 3 keeps it because a guard file
is otherwise two lines of prohibition with no context.

**`## Traps` is the headline section** and the reason the tier exists. A trap is a fact
that costs an agent a wasted turn or a wrong result: a gate that fires on a partial run,
an ordering dependency, a file that regenerates, a predicate that looks equivalent and is
not. E-2 measured this as the only content type with a surviving effect.

Five content rules, each mapping to a check in D-7:

1. **Every rule carries its rationale**, as a trailing `— why: <reason>` clause.
   Not decoration: deletion hazard *falls* with instruction age because the reason decays
   faster than the rule, and 77.3% of instruction deaths are wholesale rewrites because
   "removing one instruction needs a reason, removing all needs none" (E-3). Recording
   the reason removed 99.3% of excess size. A rule without a `why` cannot be safely
   deleted later, so it never gets deleted, so the file ratchets.
2. **Every security-relevant rule names its enforcing control, or is marked advisory.**
   `— control: scope_freeze` / `bind_guard` / `literal_guard` / `ci:governance`, or
   `— advisory`. Only ~4.4% of security rules in public instruction files have a matching
   control and nothing marks which (E-6): *"a write-only security channel."* This repo
   has the controls; it can close the loop for the cost of one clause.
3. **No repeats, and no contradictions.** A repo-wide rule lives in the root alone. The
   greater risk in a 35-file tree is *contradiction*, not duplication (E-7: Conflicting
   Instructions, 28%) — rev.1's check targeted the benign case.
4. **Additive, never subtractive.** A scoped guide may add a constraint; it may never
   relax one the root sets. This is invariant I-1 and now has both a scenario and a check.
5. **Cite with a reason to read.** A bare path citation is the Blind Reference smell
   (E-7, 16%): *"If you just mention the path, Claude will often ignore it. You have to
   pitch the agent on why and when to read the file."* rev.1's "cite, don't inline" rule
   produced this smell; rev.2 requires every citation to say why and when.

**Rejected alternative** (rev.1 recorded none): a freeform contract with required keys
only, no fixed order. Rejected because check 2 becomes unimplementable and because
Skill Leakage (E-7, 35%) is a *placement* failure — a fixed slot for commands is what
makes "this belongs in a skill" visible during review. **Also rejected:** keeping
`## Verification` in every guide, as rev.1 had it. Testing and workflow procedure are the
two most-leaked categories (E-7); they belong in
`.agents/skills/pre-pr-validator/` and `.agents/skills/meshsa-test-conventions/`, which
already exist.

## D-4. Line budgets

rev.1 justified budgets by "the measured regression." That justification is void: E-1
Appendix B is an explicit null — *"The length of context files does not influence our
findings."* The budgets survive on a better mechanism.

E-3, over 247,694 instruction lifetimes: files grow **+226%** over their lifetime at
**+4.9 net instructions per commit**; the median already carries **39 instructions**,
"well past the threshold at which instruction-following degrades"; deletion hazard falls
with age (log-hazard −0.032/commit, CI excludes zero) and falls further with maintainer
count (β = −0.021, z = −11.7). A majority-agent-authored repository with many committers
is the maximally exposed case. A budget is a forcing function: a file that cannot grow
must be *edited*, which is the review that otherwise never happens.

Numbers come from this repo's own practice (existing guides 25/34/50/67, root 135), with
two corrections the red-team surfaced:

- **Root raised 150 → 170.** At 135 today, minus ~39 lines of folded roster/skills
  sections, plus a delegation table (~28) and one diagram (~20), the root lands ~144
  before `## Purpose` and the defensive directive. 150 was not reachable.
- **`packages/jetson_yolo_gcs/AGENTS.md` must shed content, not be squeezed.** Its
  existing substance (Layout 7 + Conventions 20 + failure policy 16 = 43 lines) plus Tier 1
  scaffolding exceeds 80. T-1.5 schedules moving the pipeline failure policy to
  `docs/specs/initiative-d-perception.md`, which already owns it, and citing it with a
  reason to read.

## D-5. Mermaid — decision diagrams, not structure diagrams **[inverted]**

rev.1 made a diagram **required** at Tier 0/1 and framed it as "the folder's boundary."
E-1 §4.3 measured overviews as ineffective and recommends content *"not already present
in the README"*; this repo already has `docs/C4.md` (six diagrams),
`docs/architecture/C4.md`, and `packages/jetson_yolo_gcs/docs/architecture/c4_diagrams.md`.
A boundary diagram in a guide is the redundant case.

rev.2 keeps Mermaid — the request asked for it and it has real value — but splits it:

- **Structure diagrams belong in `docs/`.** Where a folder wants one, it is authored
  under `docs/architecture/` and the guide links to it *with a reason to read*.
- **A guide may carry at most one diagram, and only when it encodes a constraint the code
  cannot show**: bring-up ordering (`flightctl` — mavp2p `udpc` consumers must bind
  first), codegen direction (`lib` — `openapi.yaml` → orval → two generated trees, and
  `clean: true` wipes them), a governance gate (`tools` — `governance.yaml` → hooks →
  CI). Decision diagrams stay; structure diagrams move.

Mechanics, all checked:

```
flowchart LR
    accTitle: meshsa transport registration path
    accDescr: A transport factory registers into transport_registry at import time; build_node resolves config entries through the registry and skips unknown types.
    cfg["node config"] --> build["build_node()"]
    reg[("transport_registry")] --> build
    build --> tr["Transport instances"]
```

- `accTitle:` and `accDescr:` are mandatory — Mermaid exposes no edge semantics to
  assistive technology without them. Verified against a renderer: they emit `<title>` and
  `<desc>` with `aria-labelledby`/`aria-describedby`. The block form `accDescr { … }` is
  accepted.
- A prose summary immediately after the closing fence, defined positively: the first
  non-blank line must not begin with `#`, a fence, `|`, `-`, `*`, or `N.`.
- **A fence-body cap of 22 lines replaces rev.1's "≤15 nodes."** Node count is not
  mechanically determinable without a Mermaid parser — chained edges (`a --> b --> c`),
  `subgraph`, labels containing `<br/>` and brackets, and `sequenceDiagram` participants
  all defeat a regex, and rev.1's own canonical example is 4 nodes across 3 lines under a
  rule that counts "node lines." "≤15 nodes, one concept per diagram" survives as prose
  guidance in the authoring skill, where judgement belongs.
- `flowchart LR|TB` and `sequenceDiagram` only; any other diagram type is refused rather
  than guessed at. No `C4Context` — that would fork `docs/C4.md`.

## D-6. Making Claude Code load the tree

Unchanged in substance from rev.1, and now better supported.

**Current state.** Claude Code's default `claude-md-or-agents-md` mode reads `AGENTS.md`
*only* when no `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` exists at or above
the working directory. This repo has a root `CLAUDE.md`, so **no `AGENTS.md` here is
loaded today** — the root pointer is a markdown link, not an `@` import.

**Fix.** The root `CLAUDE.md` imports `@AGENTS.md`; every directory carrying a guide gains
a three-line `CLAUDE.md` importing its sibling. Nested stubs load *on demand* when Claude
reads a file in that subtree, so session-start cost is zero — and E-2 found on-demand
retrieval significantly better than always-on injection on cache footprint at equal
correctness (p_Holm = 0.012), which is a positive argument for this shape rather than
merely a neutral one.

**The root is exempt from the stub contract**, stated here because rev.1 contradicted
itself: the spec required a stub to carry "only a title and the import", while the plan
kept the root's six Claude-specific notes (PowerShell on Windows, prefer `rg`, no
destructive git, check `.agents/skills` first, package-local mypy, delegate per roster).
Those are rules. rev.2 exempts the root explicitly in both the design and the delta.

**Rejected:** symlinking `CLAUDE.md` → `AGENTS.md` (Windows contributors are explicitly
supported; Git symlinks need Developer Mode and degrade under `core.symlinks=false`);
setting `instructionFiles: claude-md-and-agents-md` (Claude Code **ignores that key in
project and local settings**, so it cannot be committed for the team — worth one line in
`CONTRIBUTING.md` as a per-developer option); moving content into `.claude/rules/`
(splits it from the tree every other tool reads, recreating the drift these validators
exist to prevent). Note Claude Code never reads anything under `.agents/` as project
instructions, which is why `.agents/skills/` correctly gets no guide (D-2).

## D-7. `tools/validate_agents_docs.py`

Third sibling of `validate_workforce.py` and `validate_skills.py`: standalone,
stdlib-only, policy as module constants, one finding per line, exit 1 on any finding.
The red-team pass measured rev.1's check set against the real corpus and found three
checks that cannot work as specified; all three are corrected here.

| # | Check | Difficulty | Note |
| - | ----- | ---------- | ---- |
| 1 | Manifest ↔ tracked files agree both ways | trivial | Enumerate via `git ls-files '*AGENTS.md' '*CLAUDE.md'`, not `rglob` — exact, needs no exclusion list for `node_modules/`, and doubles as check 12 |
| 2 | Required H2s present in canonical order for the tier | trivial | Must skip `##` inside fences; the per-tier sets are in the delta, not prose |
| 3 | Line count within the tier budget | trivial | Blanks and fences count, or it is not a budget |
| 4 | Breadcrumb parent is the **nearest manifest ancestor** | trivial | rev.1 only checked that the link resolved, which passes for any existing guide and misses the orphan case it claimed to catch |
| 5 | Every cited path exists | **moderate — not a copy** | See below |
| 6 | Diagram: `accTitle`, `accDescr`, prose line after fence, ≤22 fence-body lines, allowed diagram type | trivial | Node counting removed (D-5) |
| 7 | Every `## Subagents` entry resolves | moderate | Fixed grammar: first backtick span of the bullet is the name. Index the 24 names from the three namespaces, leaning on the siblings' already-enforced name↔file invariants |
| 8 | Commands resolve | moderate | See below |
| 9 | Paired `CLAUDE.md` exists, imports `@AGENTS.md`, ≤2 non-blank lines | trivial | Root exempt (D-6) |
| 10 | No `## Rules` line **negates** a root rule (invariant I-1) | trivial | rev.3 **drops** duplicate detection entirely — see below |
| 11 | No imperative action directive in non-fenced prose outside `## Commands` | moderate | D-9; scoped in rev.3 after measuring an ~11% false-positive rate |
| 12 | Guide is tracked and survivable | trivial | Falls out of check 1; plus refuse a manifest entry inside a `clean: true` output directory (D-12) |
| 13 | ASCII-dominant; no bidi or zero-width characters | trivial | D-9; the hidden-Unicode rules-file variant |
| 14 | Reverse coverage: every roster agent, skill and mode is named by at least one guide | trivial | The drift `validate_skills.py`'s own docstring says this repo "spent a full audit pass fixing by hand" |

**Check 10's duplicate half was measured twice and is dropped.** rev.1 specified a
near-duplicate heuristic. Run against this repo's corpus (9 root rules × 17 scoped rules
plus synthetic true positives), `difflib.SequenceMatcher` gives true positives 0.28–0.80
and genuine non-duplicates 0.30–0.54 — overlapping, no separating threshold. The clearest
true positive, a scoped guide repeating `Never commit secrets.` verbatim, scores 0.28,
*below every one of the 17 genuine non-duplicates*. rev.2 therefore switched to normalised
exact match. Measured in turn (R-2): exact match **also failed to catch a deliberate
verbatim copy**, because root rules are multi-line bullets that normalise differently from
a re-wrapped copy, and copying only a rule's first sentence — the normal case — defeats
exact match by construction.

Both candidate mechanisms fail, for opposite reasons: one is too loose to be sound, the
other too tight to be useful. rev.3 therefore **deletes duplicate detection** rather than
tuning it a third time. The anti-accretion work is already done by the budget (check 3),
which §D-13 names as the mechanism — a file that cannot grow must be edited. What survives
as check 10 is only the **negation detector** serving invariant I-1: a `## Rules` line
naming a root rule's subject inside a negating construction ("does not apply here",
"except in this folder", "unlike the root"). That is the security-relevant half, it does
not depend on similarity, and it is the half no other check covers.

**Check 5 is not a copy of `validate_skills.py`.** Run unchanged over the five existing
guides it flags exactly one thing — `packages/meshsa[dev,meshtastic]` in the root's pip
command, because `_PLACEHOLDER_CHARS` does not include brackets — so **the root guide goes
red on day one**, while all four scoped guides return zero findings because their 17 real
citations are markdown links and the sibling only reads backtick spans. rev.2's check 5:
extract from backtick spans **and** markdown link targets; resolve **file-relative first,
then repo-root-relative** (a token passing either way is fine — this clears all 53
existing citations with no false positives); strip `[extras]`, `::symbol` and `#anchor`
before testing; reject any path escaping the repo root; keep the sibling's
`CHECKABLE_PATH_PREFIXES` allowlist for bare tokens.

Measured (R-3): the rev.2 specification run over the five existing guides emits **9
unresolved citations, all false** — the pip extras spec above, four bare file extensions
(`.pt`, `.onnx`, `.hef`, `.engine`), one route path (`/metrics`), and seven
package-relative shorthand citations on the jetson guide. Five corrections take that to
**1**, which is a genuine finding the retrofit fixes:

1. strip a trailing `[extras]` before testing;
2. reject bare-extension tokens matching `^\.[A-Za-z0-9]{1,6}$`;
3. reject absolute paths — a leading `/` means a route, not a repository path;
4. add **the nearest `src/<pkg>/` under the guide's directory as a third resolution
   base**, which resolves all seven package-relative citations rather than documenting
   them as an unchecked gap;
5. allow a declared exception for deliberate **counter-example** citations. This class is
   real: the Tier 2 probe legitimately cites `command/AGENTS.md` while explaining why that
   file cannot exist, and the spec delta cites `federation/` as a dead path on purpose.

**Check 8 treats an ambiguous target as a finding.** The root `Makefile` and
`tools/Makefile` share eight target names — `build clean dev format help install lint
test` — with different meanings: root `make test` runs the TypeScript suite,
`make -f tools/Makefile test` runs pytest. rev.2 specified this as "a guide that says
`make test` must fail", which is **not implementable by existence-checking** (R-4): `test`
is a valid root target, so the check passes and the agent still runs the wrong suite. The
implementable rule is about ambiguity rather than intent: **a bare `make <target>` whose
name exists in both Makefiles is a finding, and must be written with the `-f` form.**
That catches the real case without the checker having to know which suite a guide meant.
The parser must also consume
`-f <path>` as a pair (the root guide's `make -f tools/Makefile test lint type build` names
four targets and would otherwise yield `-f` as a target), skip `-C`/`-j` and `VAR=value`.
`pnpm --filter <name> run <script>` resolves against the eight workspace `package.json`
names; `pnpm -r`, `--if-present`, and path-glob filters are **explicitly skipped** with a
module comment, since a recursive invocation cannot be proven dead. `npm run` is a finding
in itself — the root `preinstall` script hard-fails any non-pnpm agent.

**Declared exceptions** live in `.claude/governance.yaml` under `agents_docs`, matching
`bind_guard` and `literal_guard` precedent (`{path, rule, rationale}`). rev.1 had no
escape hatch at all, which left "reword or suffer" as the only remedy.

**The manifest is a module constant, not `governance.yaml`.** The decisive reason is
security coupling, not style: `governance.yaml` is loaded by `scope_freeze.py`, the
PreToolUse hook that freezes the Initiative-C command path, and that loader is Pydantic
`extra="forbid"` and **fails open**. A 35-entry documentation manifest in that file means
a typo'd docs path can invalidate the config the command freeze depends on, and the freeze
then silently stops denying. A documentation list must never be able to disable
`c_gate_met`. The repo has already met this hazard once — `literal_guard` was made
`Optional` in `GovernanceConfig` precisely to avoid a mid-edit window — and an
`agents_docs` section would inherit the same shape, silently no-opping the checker on a
misspelling. Module constants match `CHECKABLE_PATH_PREFIXES`, `BUNDLE_GLOBS` and
`PRECOMMIT_REPOS`, which are the same kind of thing. If it outgrows a constant it becomes
`tools/agents_docs_manifest.json`, parsed with stdlib `json` — never `governance.yaml`.
The *tier* lives in the constant; the *qualifying trap* stays in `tasks.md`, where a human
reviews it.

**Deliberate non-goal:** the checker validates structure, references and injection
hygiene — not whether a rule is worth stating. That is what D-8's owner and D-10's review
stop points are for. Four of E-7's six smells needed an LLM to detect; only line count and
commit count are mechanically decidable, and rev.2 does not pretend otherwise.

## D-8. Subagents **[inverted]**

**(a) Delegation discoverable from the folder.** Every Tier 0–2 guide carries a
`## Subagents` section naming existing roster agents, skills and modes. Fixed grammar so
check 7 can parse it: each entry is a bullet whose first backtick span is the name.

```markdown
## Subagents
- `security-reviewer` — mandatory before any PR touching this folder. — control: ci:governance
- `bind-auditor` — any diff adding, moving, or removing a socket bind.
- `meshsa-add-transport` — the skill for adding a medium; read it before editing the registry.
```

It invents nothing; check 7 rejects a name that does not resolve.

**(b) `docs-cartographer` is a detector, not an author.** rev.1 gave an LLM agent the job
of authoring 35 guides. That is the one condition measured to make context files worse
(E-1, developer-written beat LLM-generated at p = 0.038 — the only significant
success-rate contrast in the study), and it is the Init Fossilization smell by
construction (E-7, 24% of sampled repos). rev.2 scopes it to what agents are good at and
evidence does not contradict:

```yaml
---
name: docs-cartographer
description: "Detects staleness in the AGENTS.md guide tree and proposes diffs for human ratification. Invoke when validate_agents_docs reports a finding, or on any diff that adds, removes, or relocates a module in a covered folder. Never lands guide prose unreviewed."
tools: Read, Grep, Glob, Bash(rg *), Bash(git diff*), Bash(python tools/validate_agents_docs.py*)
---
```

Note the tool list: **no `Write`, no `Edit`.** It reports and proposes; a human writes.
Body carries the `Relationship:` marker `validate_workforce.py` requires, citing
`.agents/skills/agents-md-authoring/SKILL.md`, within the 60-line cap. It also inherits
E-3's deletion protocol *and its safety caveat*: it may propose deleting a rule whose
rationale is recoverable, but *"keep a person in the deletion path and hold safety-relevant
instructions out of scope"* — so a rule carrying a `control:` tag is never proposed for
deletion by the agent.

Exactly one new roster entry, deliberately: every description costs tokens at each
session start.

## D-9. The guide tree is a security surface **[inverted]**

rev.1 rated this change "Low risk — documentation and one stdlib-only checker." That is
wrong in kind. E-5 measures instruction files as the **highest-ASR injection entry point**
of the three tested: the harness *"treats AGENTS.md (and CLAUDE.md) as trusted
system-level instructions and loads them into the session without checking what they
contain,"* with reachability `R ≡ 1` by construction. The published threat model is a
**pull-request contributor**, which is this repository's model. Pillar Security's
rules-file backdoor — including **hidden-Unicode variants** — is the disclosed exploit.

rev.2 adds 69 files to that surface and therefore declares it, with four controls:

1. **Check 11 — no action directives in prose outside `## Commands`.** E-5's recommended
   EP1 control is to *"scan the file before loading and flag or strip content that reads
   as an action directive ('run this', 'call bash with')."* E-5 puts that fix on the
   **harness**; the harness does not do it, so the repo approximates it in CI. Measured
   (R-6): against nine realistic trap lines and three injection payloads, the naive
   verb+noun pattern gives **0 misses and 1 false positive** (~11%). rev.3 therefore
   scopes it — scan only **non-fenced prose outside `## Commands`**, and match
   tool-invocation shapes rather than verb+noun pairs. It is a speed bump against naive
   and copy-paste payloads, not a control against an adaptive adversary.
2. **Check 13 — Unicode hygiene.** ASCII-dominant content; no bidirectional-override or
   zero-width characters. This is the disclosed hidden-Unicode variant, and it is four
   lines of code.
3. **A defensive directive in the root guide — for a different entry point.** rev.2
   claimed this as "~60% suppression of indirect-prompt-injection success", which
   **mis-scopes the source** (R-5). E-5 attributes the 25.7% → 10.2% reduction
   specifically to **EP2**: documentation-borne injection, with the payload planted in an
   unrelated `README.md`. The surface this bundle expands is **EP1**, the instruction
   files themselves. The directive stays — it is three lines, it is free, and this
   repository has plenty of EP2 and EP3 surface for it to help with — but it does **not**
   mitigate the surface this plan creates, and is not to be presented as if it does.
4. **`CODEOWNERS` coverage verified as a precondition**, not assumed. `.github/CODEOWNERS`
   is `* @ianshank` today, which covers it; T-0.3 verifies this still holds and fails the
   phase if it does not. For EP1 this is the load-bearing control, not checks 11/13: human
   review of the diff is what actually stops a hostile guide landing.

Three honest limits. First, per E-6, a prose rule is not a control: the repo's real
enforcement remains `scope_freeze.py`, `bind_guard`, `literal_guard` and CI — which is
precisely why D-3.2 requires each security rule to name the control that backs it or be
marked advisory. Second, the in-repo controls available for EP1 are approximations of a
fix E-5 assigns to the harness; the honest ordering is CODEOWNERS review first, checks
11/13 second. Third, E-5 found ASR falls with codebase **modularity** (High bucket 26.5%
vs Low 44.0%, with the config-driven sub-dimension the strongest single predictor), and
this repo is highly modular and config-driven — the lower-risk regime, but mitigation, not
immunity. rev.2 also cited E-5's nesting-depth result here; that comes from the EP3
source-file ablation and does not transfer to instruction files, so rev.3 drops it.

## D-10. Rollout order

Sequenced so the checker is written, wired, **and running under CI** before any new guide
is authored. rev.1 wired the gates in its final phase, leaving ~31 guide-adding commits
verified only by a human remembering to run a script by hand.

1. **Phase 1 — contract, checker, gates, and a green tree of five.** Skill, roster agent,
   checker, tests, **plus the `tools/Makefile` and CI `governance` wiring**, plus the root
   `@AGENTS.md` import and four three-line stubs. `TIER_MANIFEST` lists only the five
   guides that already exist, retrofitted to the D-3 contract. rev.1 ended this phase with
   CI **red** — check 9 would have fired five times, because the root import and the four
   stubs were scheduled for later phases. Landing them here costs ~13 lines. **Review stop
   point.**
2. **Phase 2 — root guide.** Delegation table, the defensive directive, one repo-map
   diagram, budget raised to 170 (D-4).
3. **Phase 3 — Tier 1**, one commit per domain, manifest and paired stub extended in the
   same commit as each guide. **Review stop point.**
4. **Phase 4 — Tier 2**, same discipline.
5. **Phase 5 — Tier 3 guard files** (see D-12 for where they actually go).
6. **Phase 6 — remaining wiring**: `scripts/validate-pre-pr.sh`, `.pre-commit-config.yaml`,
   `CONTRIBUTING.md`, `docs/specs/README.md` registration, `CHANGELOG.md`.

Every guide ships with its paired stub in the same commit, so the delta's "exit non-zero"
scenarios are unconditional from Phase 1 — rev.1 needed a warn-then-error mode that no
document defined, and a governance checker with a silent advisory mode is a checker nobody
notices is off.

## D-11. The frozen path cannot hold its own guide

`.claude/governance.yaml` freezes `packages/meshsa/src/meshsa/command/**`, and
`governance.py::match_globs` uses `fnmatch.fnmatchcase`, whose `*` crosses `/`. Verified
against the real matcher's semantics:

```
packages/meshsa/src/meshsa/command/AGENTS.md  -> packages/meshsa/src/meshsa/command/**
packages/meshsa/src/meshsa/command/CLAUDE.md  -> packages/meshsa/src/meshsa/command/**
packages/meshsa/src/meshsa/AGENTS.md          -> None
```

The scope-freeze hook denies a write to a *documentation* file in the frozen directory
exactly as it denies one to `lifecycle.py`. That is correct: the freeze is path-shaped by
design, and an `*.md` carve-out is a hole someone eventually drives a module through.

**Resolution.** The frozen path's guidance lives in its parent,
`packages/meshsa/src/meshsa/AGENTS.md`, under `### command/ (frozen)` — which is where an
agent about to touch `command/` is reading anyway. `MESHSA_GOVERNANCE_OVERRIDE` is not
spent on a Markdown file; every override is logged, and spending one here trains the wrong
reflex. `scope_widening_globs` (`federation/**`, `storeforward/**`) name directories that
do not exist, so they need no guide at all.

## D-12. Guard files go in the parent of a generated directory

Three of rev.1's six Tier 3 guard files would have been **deleted by the tooling they
warn about**. `lib/api-spec/orval.config.ts` sets `clean: true` on both outputs, so
`pnpm --filter @workspace/api-spec run codegen` wipes
`lib/api-zod/src/generated/` and `lib/api-client-react/src/generated/` entirely —
guide, stub and all. `artifacts/mockup-sandbox/src/.generated/` is rewritten by
`mockupPreviewPlugin.ts` on every dev and build. Check 1 would then go red for everyone
who regenerated, with no obvious cause.

This is the same shape as D-11 and takes the same resolution: **the guide lives in the
parent** — `lib/api-zod/src/`, `lib/api-client-react/src/`,
`artifacts/mockup-sandbox/src/` — and names the generated child in its `## Traps`. Check 12
refuses any manifest entry inside a known `clean: true` output directory, so the mistake
cannot be reintroduced. `packages/meshsa/tests/snapshots/` and `archive/` are not
regenerated in place and keep their in-directory guard files.

## D-13. Keeping it true

Four mechanisms, increasing in strength:

- **Rationale** (D-3.1) — the only thing that makes a rule *deletable*, and therefore the
  only thing that stops the ratchet at its root cause (E-3).
- **Budget** (D-4) — a file that cannot grow must be edited, forcing the review that
  otherwise never happens.
- **Checker** (D-7) — structural and reference rot, plus injection hygiene, on every PR.
- **Owner** (D-8b) — `docs-cartographer` detects staleness and proposes; a human ratifies.

`CONTRIBUTING.md` gains one checklist line: *if a PR adds, removes, or moves a module in a
folder with an `AGENTS.md`, refresh that file's `## Traps` in the same PR.*
