# Peer Review — `agents-md-directory-guides` bundle (rev.1 → rev.2)

Date: 2026-09-19. Reviewer: agent-driven, every claim verified against the tree or
against a primary source. **Four verification passes**: external-research claims (seven
papers read in full, replacing four secondary blog summaries that rev.1 cited without
reading — registered in `docs/AGENTS_MD_EVIDENCE.md`); adversarial repo-state
verification (`security-reviewer`); house-format compliance against the two existing
bundles (`openspec-author`); and a red-team pass on the proposed checker, which ran the
proposed heuristics against the repository's own corpus. Method and format follow the
bundle's own `security-reviewer` rules — confidence tags, severity order, negative claims
verified by search, what-survives listed. Findings that a reviewer raised and that
verification **rejected** are recorded as such (F-22). The corrected bundle (rev.2) is
materialized under `openspec/changes/agents-md-directory-guides/` in the same PR that adds
this record.

**Verdict:** rev.1's mechanics were sound — the filename decision, the Claude Code
loading analysis, the frozen-path collision, and the checker-as-third-sibling shape all
survive verification. Its *evidence base* did not. rev.1 built its central argument on
four blog summaries, **all four of which were egress-blocked and therefore never read**,
and misreported the one number it leaned on hardest. Reading the primary literature
inverts three of rev.1's design decisions: the agent it appointed to author the guides is
the one condition measured to make them worse; the diagrams and overviews it made
mandatory are the content type measured to be useless in a documentation-rich repo; and
the line budgets it justified by "measured harm" rest on a mechanism the sources
explicitly rule out. rev.1 also declared the change security-neutral. It is not: the
guide tree is the highest-privilege prompt-injection surface in an agentic repository,
and rev.1 proposed multiplying it by 71 files in a repo whose distinguishing asset is a
security invariant.

The roster passes were worse for rev.1 than the literature pass. Its task checkboxes were
invisible to the repo's own `check_task_sync.py` (0 of 32 parsed). Three of its six guard
files would have been deleted by the codegen they warn about. Its headline checker rule,
measured against this repository's corpus, scores a verbatim duplicate *below* every
genuine non-duplicate. Its Phase 1 ended with CI red. And its manifest — the artefact the
whole plan compiles into — carried a wrong safety-path invariant that would have told an
agent to delete a tolerance window on the `LANDING_TARGET` publish path.

Twenty-two findings, sixteen rated [Certain]. Six change the deliverable. One (F-12) is
not about this bundle at all: verifying a manifest cell surfaced a pre-existing
all-interfaces unauthenticated HTTP listener that is absent from `docs/AUDIT_M2_AUTH.md`
and outside `bind_guard`'s Python-only scan globs. One (F-22) is a reviewer claim that
verification rejected.

## Findings (severity-ordered)

- **F-1 [Certain] — the change is not security-neutral, and rev.1 said it was.**
  rev.1's `proposal.md` Impact table rated the risk *"Low. Documentation and one
  stdlib-only checker,"* and its PR body checked off the governance boxes on the grounds
  that "no code changed." Both are wrong. Day et al. (Capital One, CAMLIS 2026,
  `arXiv:2608.14876`) measure instruction files as the **highest-privilege injection
  entry point** they test: *"EP1 is the highest-ASR entry point in our study because the
  harness treats AGENTS.md (and CLAUDE.md) as trusted system-level instructions and loads
  them into the session without checking what they contain,"* with reachability
  `R ≡ 1 by construction` because the harness auto-loads them. Their threat model names
  *"a contributor via pull request"* — this repository's exact model. They cite Pillar
  Security's rules-file backdoor disclosure, including **hidden-Unicode variants**.
  rev.1 proposed 36 `AGENTS.md` plus 35 `CLAUDE.md` stubs: a 71-file expansion of that
  surface, with no content validation, in the repo that ships `bind_guard`,
  `literal_guard`, and a scope-freeze hook precisely because it does not trust prose.
  rev.2 treats the guide tree as a declared surface: the checker rejects imperative
  action directives outside the declared `## Commands` block and rejects non-ASCII,
  bidi, and zero-width characters; `CODEOWNERS` coverage of `**/AGENTS.md` and
  `**/CLAUDE.md` is verified as a precondition, not assumed. The same paper also hands us
  a free mitigation rev.1 missed: a defensive directive in the root file cut attack
  success from **25.7% to 10.2%** (~60% suppression), so rev.2 requires one.

- **F-2 [Certain] — rev.1 appointed an LLM agent to author the guides, which is the one
  condition the literature measures as worse.** rev.1 §D-8b created
  `docs-cartographer` to "author and refresh the guide tree and its diagrams." Gloaguen
  et al. (ETH Zurich + LogicStar.ai, `arXiv:2602.11988`) report that the **only
  statistically significant success-rate comparison in their study** is LLM-generated
  versus developer-written context files: *"developer-committed files outperform
  LLM-generated ones by a significant margin of 7% on average"* (abstract), *"significantly
  outperforming LLM-generated ones (p = 3.8%)"* (§4.2). Every other contrast — None vs
  LLM (p = 0.87, 0.37), None vs Dev (p = 0.21) — is null. Their recommendation is blunt:
  *"We therefore suggest omitting LLM-generated context files for the time being, contrary
  to agent developers' recommendations."* This is also the **Init Fossilization** smell of
  dos Santos et al. (`arXiv:2606.15828`): a file generated by an agent and never reviewed,
  present in 24% of the 100 repositories they sampled. rev.2 demotes `docs-cartographer`
  from author to **detector**: it finds staleness and proposes diffs; a human ratifies
  content. The agent never lands guide prose unreviewed.

- **F-3 [Certain] — rev.1 cited four sources it never read, and misreported the number it
  leaned on hardest.** rev.1's `design.md` §D-0 stated: *"Machine-generated `AGENTS.md`
  files **reduced** task success in 5 of 8 tested settings and added 2.45–3.92 steps per
  task,"* citing SitePoint and daily.dev. Both were egress-blocked; so were `agents.md`,
  `morphllm.com`, `aihero.dev`, and `developers.openai.com`. rev.1 cited them anyway.
  The primary source is Gloaguen et al. Verified verbatim: *"LLM-generated context files
  cause performance drops in 5 out of 8 settings"* — the count was right — but
  *"**With p-values of 87% and 37% ... this indicates that they have no significant
  effect on performance.**"* rev.1 omitted the null and presented a non-significant 0.5–2%
  drop as measured harm. What **is** significant (p < 0.001%) is cost: *"+20% and 23% on
  average."* The honest claim is a **cost** argument, not a harm argument. This repository
  already ratified a standing rule against exactly this, in
  `docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md` F-1: *"external research is adopted only with
  a verifiable citation checked into `docs/` first."* rev.1 violated a rule the repo had
  already written down. rev.2 cites six primary papers, all read in full, with the
  significance of each claim stated.

- **F-4 [Certain] — the evidence contradicts the plan's core content types: overviews,
  structure maps, and diagrams.** rev.1's template made `## Purpose`, `## Map` (Mermaid,
  **required** at Tier 0/1) and `## Key files` mandatory — three of seven sections are
  repository-overview content. Gloaguen et al. §4.3 is titled *"Context files do not
  provide effective overviews"*; they measured steps-to-first-relevant-file and found
  *"the context files do not meaningfully reduce this metric."* Their conclusion:
  context files *"should only contain specific additional instructions beyond what is
  already available in the codebase,"* and human-written ones *"should only include
  instructions required for coding agents that are **not already present in the
  README**."* The conditional matters and rev.2 states it: in their Appendix B ablation,
  *when all documentation is stripped from the repository*, context files do help
  (+2.7%). **That is the opposite of this repository's situation** — `docs/C4.md` (six
  Mermaid diagrams), `docs/ARCHITECTURE.md`, `docs/specs/`, and a `CONTRIBUTING.md` that
  already carries a repo-layout block. Here, overview content in an always-loaded file is
  the redundant case. rev.2 does not drop Mermaid — the request asked for it and it has
  real value — but relocates it: structure diagrams go to `docs/`, and a guide may carry
  **one** diagram only when it encodes a constraint that cannot be inferred from the code
  (bring-up ordering, codegen direction, a governance gate). Decision diagrams stay;
  structure diagrams move.

- **F-5 [Certain] — the line budgets were justified by a mechanism the sources rule out,
  and the mechanism that does apply prescribes something rev.1 missed entirely.**
  rev.1 §D-4 justified its 12/60/80/150-line budgets as defending against the measured
  regression. Gloaguen et al. Appendix B: *"The length of context files does not
  influence our findings ... no clear dependency between the success rate or the
  per-instance cost and the context file length."* Their category ablation (Table 7) is
  null for every section type. The budgets survive, but on a different and better
  footing. Chakrabarti (`arXiv:2608.11095`), across **1,867 repositories and 247,694
  instruction lifetimes**, shows agentic context files grow **+226%** over their lifetime
  at **+4.9 net instructions per commit**, that the median file already carries **39
  instructions** — *"well past the threshold at which instruction-following degrades"* —
  and that deletion hazard **falls** with instruction age (log-hazard −0.032/commit,
  95% CI [−0.047, −0.019]). **77.3%** of instruction deaths arrive in a wholesale rewrite:
  *"removing one instruction needs a reason, removing all needs none."* The root cause is
  **imperfect recall** — an instruction's rationale decays faster than the instruction —
  and the hazard falls further with the number of maintainers (β = −0.021, z = −11.7),
  which is this repository's exact exposure as a majority-agent-authored tree. The
  prescribed fix is one rev.1 never considered: **record each rule's rationale beside it**.
  Encoding latent reasoning removed **99.3%** of excess instructions and improved
  real-prompt instruction-following by up to **23.1%**. rev.2 makes a one-line `why:` part
  of the rule format and checks for it, and adopts the paper's own safety caveat —
  *"keep a person in the deletion path and hold safety-relevant instructions out of
  scope."*

- **F-6 [Certain] — no study evaluated nested per-directory files; all three controlled
  studies deliberately excluded them.** rev.1 §D-0 cited blog posts ("nearest-first
  precedence", "OpenAI's Codex repo ships 88 of them") in the evidence column, as if
  adoption were efficacy. Lulla et al. (`arXiv:2601.20404`) §3.1.2: *"we focus on the
  simplest configuration: repositories that contain **one AGENTS.md file only at the
  repository root**. This configuration minimizes confounding effects from overlapping or
  conflicting instruction files."* Khatri (`arXiv:2607.27250`) §3.2 filters on
  *"exactly one root AGENTS.md with no competing instruction stack."* Gloaguen et al.
  likewise test root files. **The multi-file configuration rev.1 proposed is the one every
  controlled study removed as a confounder.** rev.2 states this plainly: the tiering is
  risk management under acknowledged uncertainty, not an evidence-backed design, and the
  file count drops accordingly.

- **F-7 [Likely] — rev.1 proposed restating security rules as prose across 20+ guides,
  which is a write-only channel.** rev.1 §D-8a required every governed folder's
  `## Subagents` section to restate the binding `security-reviewer` rule. Yan
  (`arXiv:2608.23550`) analysed 481 public `CLAUDE.md` files and found that under a strict
  standard only **4.4%** [2.6–6.7] of written security rules have a matching built-in
  control: *"CLAUDE.md is a write-only security channel. A developer writes a security
  rule but gets no feedback on whether a control will enforce it."* This repository is
  unusually well placed to fix that rather than suffer it — it *has* the controls
  (`scope_freeze.py` as a real PreToolUse deny, `bind_guard`, `literal_guard`, the CI
  `governance` job). rev.2 therefore requires every security-relevant rule in a guide to
  be **tagged with the control that enforces it, or explicitly marked advisory**. That
  closes the loop the paper says is missing, at the cost of one token per rule.

- **F-8 [Likely] — rev.1's own authoring contract reproduces three catalogued
  configuration smells.** dos Santos et al. (`arXiv:2606.15828`) catalogue six smells
  across 100 repositories; 91 carried at least one. (a) **Skill Leakage** (35%; the most
  commonly leaked category is *Testing*, then *Workflow*): rev.1 put `## Commands` and
  `## Verification` in *every* guide, which is precisely testing-and-workflow content in
  an always-loaded file — and this repo already has the right home for it in
  `.agents/skills/pre-pr-validator/` and `.agents/skills/meshsa-test-conventions/`.
  (b) **Blind Reference** (16%): rev.1's §D-3 rule 4, *"Cite, don't inline,"* actively
  produces this smell — *"If you just mention the path, Claude will often ignore it. You
  have to pitch the agent on why and when to read the file."* (c) **Conflicting
  Instructions** (28%): a 36-file tree multiplies contradiction risk, and rev.1's check 10
  targeted *duplication*, which is the benign case. rev.2 moves commands to the skills
  that own them, requires every citation to state why and when to read it, and reorients
  check 10 from duplication to contradiction.

- **F-9 [Certain] — a wrong number under an implied-certain claim.** rev.1 stated
  *"114 directories carry tracked files."* Verified: `git ls-files | xargs -n1 dirname |
  sort -u` yields **118** including the repository root, **117** excluding it. rev.1's 114
  came from a command that silently also excluded `archive/`. The argument (114 or 117,
  one file per directory is not the answer) survives; the false precision does not. This
  is the same failure as F-4 in `docs/OPENSPEC_M2_BUNDLE_PEER_REVIEW.md`, repeated.

- **F-10 — the one content type the evidence actively supports is the one rev.1 treated
  as incidental.** Khatri's two-agent ablation (288 evaluated runs, Claude Code + Codex,
  TOST equivalence) bounds the correctness effect to ≤10–15pp and explains the null:
  *"agents fail on implementation skill — feature design, pattern selection, exact
  wiring — not missing repository knowledge that a context file could supply,"* and
  *"the real AGENTS.md never converts a near-miss to a pass on either agent."* But one
  effect did survive, and it is specific: on `opshin`, *"the one repository whose
  AGENTS.md carries explicit runtime/compile-time warnings ('the full test suite takes
  >20 minutes')"*, blind full-suite test runs fell **3.67 → 2.44 → 1.67** per cell and
  wall-clock time fell ~24%. **Cost, ordering and trap warnings are the evidence-backed
  content type.** This repository is full of them and rev.1 scattered them through
  prose: a single-file pytest run still fails `--cov-fail-under=97`; `dist/` must be built
  before `pnpm -r run typecheck`; `mypy flightctl/ tools/` must stay one invocation;
  mavp2p `udpc` consumers must bind first; `.gitignore` must use `.agents/*`, never
  `.agents/`. rev.2 promotes these to a first-class, required `## Traps` section and
  demotes the overview sections that the same literature finds inert.

## Findings — roster review passes

- **F-11 [Certain] — rev.1's manifest stated a safety-path failure policy that the code
  contradicts.** The `packages/jetson_yolo_gcs/src/jetson_yolo_gcs` cell read
  *"`LANDING_TARGET` fails loud."* `Pipeline._publish_target` implements
  **tolerate-then-escalate**: consecutive publish failures are counted and rate-limit
  logged until they reach `publish_failure_tolerance`, then the exception re-raises.
  Fail-loud-on-first is only the `tolerance == 0` case. Three of that cell's four policies
  were right; the wrong one was the only one on the safety path, and an agent told to
  preserve it would delete the tolerance window. This is the guide-tree failure mode the
  bundle exists to prevent, present in the manifest before a single guide was written —
  and it is a failure no checker in D-7 would ever catch, which is why the review stop
  points are not optional.

- **F-12 [Certain] — a real, unaudited, unauthenticated network surface, found while
  verifying a manifest cell.** `artifacts/api-server/src/index.ts` calls
  `app.listen(port, cb)` with **no host argument**, so Express binds all interfaces, not
  loopback. `src/middlewares/` contains only `.gitkeep`; `app.use(cors())` is
  unrestricted-origin; the sole occurrence of "authorization" in the package is a pino
  redaction key. Verified: `docs/AUDIT_M2_AUTH.md` has **zero** `artifacts/` rows across
  its 17 numbered surfaces, and `bind_guard.py::SCAN_GLOBS` is
  `packages/**/src/**/*.py`, `flightctl/**/*.py`, `tools/**/*.py` — **Python only**, so no
  TypeScript listener has ever been in scope. This is pre-existing and not created by this
  bundle, but it sits squarely against the ROADMAP M2 invariant. rev.2 makes recording it
  a **precondition** (T-0.4) and blocks `artifacts/AGENTS.md` until the audit row exists:
  a Tier 1 guide whose trap list omits an unauthenticated listener is worse than no guide.
  Remediating the listener and widening `bind_guard` to TypeScript are both deferred as
  their own changes.

- **F-13 [Certain] — rev.1's checkbox format made every task invisible to the repo's own
  checker.** rev.1 wrote `- [ ] **T-0.1** …`. `check_task_sync.py` parses
  `^[-*] \[([ xX])\] (T-\d+\.\d+[a-z]?)\b` — the id must follow the bracket immediately.
  Measured: **0 of 32** checkbox lines parsed, against 71/71 in `code-hygiene-modularity`
  and 20/20 in `gcp-drone-m2-agent-hardening`. Since `check_task_sync.py` runs inside
  `make checkers` and the pre-PR gate, every future commit naming a task id would have
  emitted a false "not found in any bundle" warning — 32 of them, which is how a checker
  becomes noise everyone ignores. Fixed by dropping the bold.

- **F-14 [Certain] — rev.1 would have written a second repository-root-scope memory
  file.** `.claude` is Tier 1, and rev.1 required a paired stub in every guide directory —
  so `.claude/CLAUDE.md`. But rev.1's own §D-6 states that Claude Code treats
  `.claude/CLAUDE.md` as a **root-scope** instruction file. rev.1 therefore mandated
  creating a second root-scope memory file with undefined precedence against the first,
  which also falsifies its own "+0 tokens at session start" claim. rev.2 exempts
  `.claude/` explicitly (T-0.5).

- **F-15 [Certain] — three of rev.1's six guard files would have been deleted by the
  tooling they warn about.** `lib/api-spec/orval.config.ts` sets `clean: true` on both
  outputs, so `pnpm --filter @workspace/api-spec run codegen` wipes
  `lib/api-zod/src/generated/` and `lib/api-client-react/src/generated/` entirely — guide,
  stub and all. `artifacts/mockup-sandbox/src/.generated/` is rewritten on every dev and
  build. Check 1 would then go red for everyone who regenerated, with no visible cause.
  rev.2 moves those three guides to the **parent** directory — the same resolution the
  design already uses for the frozen command path — and adds check 12 so the mistake
  cannot be reintroduced.

- **F-16 [Certain] — the checker's headline check was measured and found unsound.** rev.1
  specified a near-duplicate heuristic against root rules. Run over this repository's own
  corpus (9 root rules × 17 scoped rules, plus synthetic true positives),
  `difflib.SequenceMatcher` gives true positives 0.28–0.80 and genuine non-duplicates
  0.30–0.54 — overlapping, with no separating threshold. The clearest true positive, a
  scoped guide repeating `Never commit secrets.` verbatim, scores **0.28 — below every one
  of the 17 genuine non-duplicates**, because the measure is length-sensitive. Token
  containment separates here but degenerates on short lines: `Do not edit generated
  files.` scores 0.80, and that is verbatim the line every guard file will carry — against
  which rev.1's own Implementation note 6 declared guard-file redundancy *intentional*.
  rev.2 replaces it with normalised exact-match plus a negation detector for invariant
  I-1, and exempts Tier 3.

- **F-17 [Certain] — rev.1's second-highest-value check does nothing on four of the five
  files it protects, and breaks the fifth on day one.** Run unchanged,
  `validate_skills.py`'s path logic flags exactly one thing across the existing guides:
  `packages/meshsa[dev,meshtastic]` in the root's pip command, because
  `_PLACEHOLDER_CHARS` omits brackets — so **the root guide goes red immediately**. All
  four scoped guides return zero findings, because their 17 real citations are Markdown
  links and the sibling reads only backtick spans. Separately,
  `CHECKABLE_PATH_PREFIXES` contains no `lib/`, `artifacts/`, or `scripts/` — the exact
  guides whose entire content is "this path is generated, edit that one instead". rev.2
  gives check 5 its own logic and adds T-1.3b to extend the shared constant.

- **F-18 [Certain] — rev.1's command check was specified as a union over two Makefiles
  that share eight colliding target names.** Root `make test` runs the TypeScript suite;
  `make -f tools/Makefile test` runs pytest. Under a union rule a
  `packages/meshsa/AGENTS.md` saying `make test` passes and sends an agent to the wrong
  suite — precisely the wasted turn the check exists to prevent. The parser must also
  consume `-f <path>` as a pair, or the root guide's own
  `make -f tools/Makefile test lint type build` yields `-f` as a target name. rev.2
  disambiguates by `-f` and explicitly skips what cannot be resolved (`pnpm -r`,
  `--if-present`, path-glob filters).

- **F-19 [Certain] — rev.1's Phase 1 ended with CI red, and wired its own gate last.**
  Check 9 would have fired five times at the Phase 1 stop point (four missing stubs plus a
  root `CLAUDE.md` whose import was not scheduled until Phase 2), and rev.1's T-5.3 implied
  a warn-then-error mode that no document defined. Separately, the `tools/Makefile` and CI
  wiring sat in Phase 6, so roughly 30 guide-adding commits would have been verified only
  by a human remembering to run a script. rev.2 moves the gate wiring, the root import and
  the four stubs into Phase 1, which is also the cheapest place to discover F-17.

- **F-20 [Certain] — rev.1's delta was structurally incomplete for a checker author.** No
  `## MODIFIED Requirements` section, although the change amends
  `gcp-drone-m2-agent-hardening`'s ratified "Agents Collaborate by Default" and replaces
  the root `CLAUDE.md` pointer that bundle landed. The per-tier required-section sets were
  never stated, making the section check unimplementable. Two requirements contradicted
  each other (repo-wide rules "live in the root and nowhere else" versus a mandate to
  restate the `security-reviewer` rule per folder). One requirement bundled four concerns.
  The only security-relevant clause — additive-never-subtractive — had neither a scenario
  nor a mechanism. And no requirement bound the checker to CI, so a repository could
  satisfy every requirement and never run it.

- **F-21 — accumulated precision errors in the manifest.** Each would have been copied
  verbatim into a guide: `tools` claimed "PyYAML pins must match CI exactly" when
  `check_tool_pins.py::TOOLS` covers only `ruff` and `mypy` and nothing pins PyYAML
  outside `ci.yml` (false the day it was written); `lib` claimed three generated trees
  (two — the third is under `artifacts/`); `artifacts` claimed per-package `dev`/`build`/
  `test` (`mockup-sandbox` has no `test`); the shadcn guard file said ~70 vendored files
  (55); `archive` claimed exclusion from "every gate" (only `ruff`, `ruff-format`, `mypy`
  — `gitleaks`, `detect-private-key` and three others still see it); the deliverables
  retirement task `T-10.2b` was attributed to `NEXTSTEPS.md` when it lives in the
  `code-hygiene-modularity` bundle; `.github` said three mypy passes (four across CI);
  `scripts` cited `make validate-pre-pr`, which is the *parent's* target and so fails the
  tier test it was listed under. rev.1 also proposed a guide for `.agents/skills/` that
  appeared in no tier — self-violating its own first requirement — and a
  `step_validate_skills` function that does not exist (`step_skills_lint` does). The
  "deliberately uncovered" table, whose stated purpose is distinguishing absent from
  forgotten, omitted seven directories.

- **F-22 — a reviewer finding that verification rejected.** The adversarial pass reported
  that the three polling-based receive-only transports do not override `send`, so the
  manifest's "receive-only sources keep `send()` a no-op" encoded a weaker control than
  `AbstractTransport.send`'s `raise NotImplementedError`. Checked directly:
  `polling_source.py::PollingSourceTransport.send` **does** override it and returns
  `None`, and `mavlink_source`, `msp_source` and `crsf_source` all derive from it. The
  original cell was correct and is retained, with the base-class raise noted so a future
  source that skips both bases inherits the stricter behaviour. Recorded because the
  standing rule cuts both ways: a reviewer's claim is not evidence either.

## What survived review unchanged

The filename decision (`AGENTS.md`, not `Agent.md`) — confirmed by every paper read, and
by the four guides already in the tree. The §D-6 loading analysis: Claude Code reads
`AGENTS.md` only when no `CLAUDE.md` sits at or above the working directory, so this
repo's root `CLAUDE.md` currently suppresses every guide in the tree; verified against
the official memory documentation, and the `@AGENTS.md` import remains the only
repo-portable fix, since `instructionFiles` is ignored in project settings. The
lazy-loading property of nested `CLAUDE.md` stubs is now *better* supported than rev.1
knew: Khatri's SELECTIVE arm (on-demand retrieval rather than always-on injection) was
the only strategy to significantly reduce cache footprint (p_Holm = 0.012) at equal
correctness, which is an argument for on-demand guides and against always-on ones. The
§D-10 frozen-path collision — `command_emission_globs` is `.../command/**` and
`match_globs` uses `fnmatch`, so a write to `command/AGENTS.md` is denied exactly as a
write to `command/lifecycle.py` is — verified empirically against the real matcher's
semantics, and the resolution (document the frozen path from its parent, never spend a
`MESHSA_GOVERNANCE_OVERRIDE` on a Markdown file) stands. The checker's shape as a third
stdlib-only sibling of `validate_workforce.py` and `validate_skills.py`, wired into
`make -f tools/Makefile checkers`, `scripts/validate-pre-pr.sh`, and CI's `governance`
job. Checks 5 (cited-path existence) and 8 (command existence) survive and gain support:
they are the mechanical defence against Blind Reference and stale-path rot. The
Phase-1-first rollout order, and the decision to retrofit the five existing guides before
writing any new one.

## Standing rules added by this review

1. External research is adopted only from a **primary source read in full**. A secondary
   summary of a study is not a citation of that study. If the source cannot be retrieved,
   the claim is dropped, not softened.
2. Every statistic carries its **significance**. A non-significant difference is reported
   as a null result, not as an effect with a smaller number.
3. Any change that adds files the agent harness **auto-loads as trusted context** is a
   security change and is reviewed as one, whatever else it touches.
