# Evidence Register — agent context files (`AGENTS.md` / `CLAUDE.md`)

Checked in to satisfy the standing rule ratified in
[OPENSPEC_M2_BUNDLE_PEER_REVIEW.md](OPENSPEC_M2_BUNDLE_PEER_REVIEW.md) F-1:
*external research is adopted only with a verifiable citation checked into `docs/`
first.* Every paper below was read in full from the primary source. Secondary
summaries (blog posts, vendor guides) are **not** citable here and are deliberately
absent — the first draft of `openspec/changes/agents-md-directory-guides/` cited four
that were never retrievable, and got the load-bearing number wrong as a result
([OPENSPEC_AGENTS_MD_PEER_REVIEW.md](OPENSPEC_AGENTS_MD_PEER_REVIEW.md) F-3).

Each row states the claim **and its statistical significance**. A non-significant
difference is recorded as a null, never as a small effect.

## E-1 — Gloaguen, Mündler, Müller, Raychev, Vechev (ETH Zurich + LogicStar.ai)

*Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?*
`arXiv:2602.11988v2`. SWE-BENCH + a purpose-built CTXBENCH (138 instances, 12 repos with
developer-committed context files), 4 models, 3 conditions.

| Claim | Significance |
| ----- | ------------ |
| LLM-generated context files cause performance drops in **5 of 8 settings**; mean resolution rate −0.5% (SWE-BENCH), −2% (CTXBENCH) | **Null.** p = 0.87 and 0.37. "this indicates that they have no significant effect on performance" |
| Developer-written files beat LLM-generated ones | **Significant, p = 0.038** — the only significant success-rate contrast in the study |
| Developer-written vs none: +2.4% | **Null**, p = 0.21 |
| Steps increase in every setting: +2.45 (SWE), +3.92 (CTX) | **Significant**, p < 0.001% |
| Cost increase +20% / +23% | **Significant**, p < 0.001% |
| "Context files do not provide effective overviews" — no reduction in steps-to-first-relevant-file | Measured, all agents, both benchmarks |
| Context-file **length** has no effect on success rate or cost | Explicit null (Appendix B) |
| Removing any one content category (overview / tooling / testing) changes accuracy insignificantly | Null (Table 7) |
| **When all other documentation is stripped**, context files help (+2.7%) | The conditional that makes overviews useful — the inverse of this repository's situation |

**Authors' recommendation, verbatim:** *"we suggest omitting LLM-generated context files
for the time being, contrary to agent developers' recommendations"*; human-written files
*"should only include instructions required for coding agents that are not already
present in the README (e.g., specific conventions or non-functional requirements)."*

**Scope limit:** root-level context files only; Python only.

## E-2 — Khatri (independent)

*Do Context Files Help Coding Agents? A Two-Agent Ablation Study on Real Repositories*
`arXiv:2607.27250v1`. 288 evaluated runs, Claude Code + Codex, 17 tasks, 3 repos,
gold-test evaluation, TOST equivalence testing.

| Claim | Significance |
| ----- | ------------ |
| Context-injection strategy does not move correctness | Bounded to ≤10pp (Claude) / ≤15pp (Codex) by descriptive TOST |
| Agents fail on **implementation skill**, not missing repository knowledge; the real `AGENTS.md` never converts a near-miss to a pass on either agent | 36-cell manipulation-validity probe |
| On the one repo whose file carries explicit **cost warnings** ("the full test suite takes >20 minutes"), blind full-suite test runs fell 3.67 → 2.44 → 1.67 per cell; wall-clock −24% | Directional, n = 4–5, exploratory — but dose-ordered and mechanistic |
| On-demand retrieval (SELECTIVE) beat always-on injection on cache footprint at equal correctness | **Significant**, p_Holm = 0.012 |
| Borderline task difficulty is agent-specific (ρ = 0.75); ~40% of tasks sit in only one agent's informative band | Explains the E-1 / E-4 contradiction |

**Scope limit:** repositories filtered to *"exactly one root AGENTS.md with no competing
instruction stack."* 3 Python repos. Underpowered below 30pp.

## E-3 — Chakrabarti (South Park Commons)

*Why Does CLAUDE.md Keep Growing? Catastrophic Remembering in Agentic Coding*
`arXiv:2608.11095v1`. 1,867 repositories, 1,801 multi-version files, 247,694 instruction
lifetimes, 28,426 tracked deletions.

| Claim | Significance |
| ----- | ------------ |
| Context files grow **+226%** over their lifetime, **+4.9 net instructions per commit** | Observational, 19,267 commits |
| Median file carries **39 instructions** (90th pct 131) — "well past the threshold at which instruction-following degrades" | Measured |
| Deletion hazard **falls** with instruction age: log-hazard −0.032/commit | **95% CI [−0.047, −0.019]**, excludes zero |
| **77.3%** of instruction deaths arrive in a wholesale rewrite or migration — "removing one instruction needs a reason, removing all needs none" | Measured, competing-risks censored |
| A rewrite cuts size to 59.5%, then regrowth **accelerates** (4.9%/commit vs 4.1% before) | The ratchet |
| Root cause is **imperfect recall**, not staleness: hazard also falls with maintainer count | β = −0.021, z = −11.7 |
| Recording each instruction's **rationale** removes **99.3%** of excess size | Controlled, 184 worlds |
| Extraneous instructions cost **24.1pp** of correctness on the true instructions in the same file; rationale recovers 11.6pp (+23.1% relative) | 95% CI [5.1, 18.3]pp |

**Authors' safety caveat, verbatim:** *"An operator deploying the protocol should keep a
person in the deletion path and hold safety-relevant instructions out of scope."*

## E-4 — Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude

*On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents*
`arXiv:2601.20404v2` (ICSE JAWs 2026). 10 repositories, 124 PRs, Codex/gpt-5.2-codex.

| Claim | Significance |
| ----- | ------------ |
| Median wall-clock runtime −28.64%, median output tokens −16.58% with `AGENTS.md` present | **Significant**, Wilcoxon signed-rank p < 0.05 |
| Task **quality** was not evaluated | *"beyond the scope of this paper"* — a sanity check on 50 samples only |

**Scope limit, verbatim:** *"repositories that contain one AGENTS.md file only at the
repository root. This configuration minimizes confounding effects from overlapping or
conflicting instruction files."* Confirms the >60,000-repository adoption figure.

**Note the tension with E-1** (which found cost *up* 20%). E-2 §5.3 reconciles both as
artifacts of injection mechanics rather than agent capability.

## E-5 — Day, Yadlapalli, Venkatapathy et al. (Capital One, CAMLIS 2026)

*Workspace Topology as an Attack Vector in Agentic Coding Assistants*
`arXiv:2608.14876v1`. 100 repositories, 10 languages, 6 domains, gpt-oss-120b/opencode.

| Claim | Significance |
| ----- | ------------ |
| `AGENTS.md`/`CLAUDE.md` (entry point EP1) is the **highest-ASR** injection surface: the harness *"treats [them] as trusted system-level instructions and loads them into the session without checking what they contain"* | Reachability `R ≡ 1` by construction |
| A **defensive directive** in `AGENTS.md` cuts attack success **25.7% → 10.2%** (~60% suppression) | n = 1000/cell, outside the neutral CI |
| Nesting depth modulates ASR: 18% (d=1) → 38% (d=2) → 24% (d=3) → 8.5% (d=4) | Reachability-driven |
| Higher codebase modularity **lowers** ASR (compliance 41% → 21%) | Config-driven codebases least susceptible |
| Recommended control: *"scan the file before loading and flag or strip content that reads as an action directive ('run this', 'call bash with')"* | Plus the Pillar Security rules-file backdoor, incl. hidden-Unicode variants |

**Threat model includes** *"a contributor via pull request"* — this repository's model.

## E-6 — Yan

*When "Do Not" Is Not `deny`: Security Rules in CLAUDE.md vs. Built-In Controls*
`arXiv:2608.23550v1`. 481 public `CLAUDE.md` files, 4,661 candidate segments, two blind
annotators plus adjudication.

| Claim | Significance |
| ----- | ------------ |
| Only **4.4%** of written security rules have a matching built-in control under the strict standard (4–16% across standards) | 95% CI [2.6, 6.7]; annotator κ = 0.89 on the match decision |
| *"CLAUDE.md is a write-only security channel. A developer writes a security rule but gets no feedback on whether a control will enforce it."* | The usable-security framing |
| Removing one declared-scope sentence raises out-of-scope action rate 0.0% → 17.1% | Cited from Rashidi 2026 |

**Design response the authors call for:** *"mark rules it cannot enforce as advisory
rather than accepting them silently."*

## E-7 — dos Santos, Costa, Montandon, Silva, Valente (UFMG / IFMG)

*Configuration Smells in AGENTS.md Files: Common Mistakes in Configuring Coding Agents*
`arXiv:2606.15828v5`. Grey-literature review (14 documents) + 100 popular repositories.

| Smell | Prevalence | Definition |
| ----- | ---------- | ---------- |
| **Lint Leakage** | 62% (93% precision) | Restating rules a linter/formatter already enforces |
| **Context Bloat** | 42% | ≥200 lines; root cause is usually another smell |
| **Skill Leakage** | 35% (82% prec.) | Task-specific instructions in the always-loaded file instead of an on-demand skill. Most leaked category: **Testing**, then Workflow |
| **Conflicting Instructions** | 28% (57% prec.) | Contradictory rules; "Claude may pick one arbitrarily" |
| **Init Fossilization** | 24% | Agent-generated (`/init`) and never reviewed |
| **Blind Reference** | 16% (87% prec.) | Citing a path without saying why or when to read it — *"If you just mention the path, Claude will often ignore it"* |

**91 of 100 files carried at least one smell.** Four of six smells needed an LLM to
detect; only Context Bloat (line count) and Init Fossilization (commit count) are
mechanically decidable — relevant to what a stdlib-only checker can honestly enforce.

## What this register licenses, and what it does not

**Licensed:**
- Cost-, ordering- and trap-warnings as the primary content type (E-2, the one surviving
  effect).
- Conventions and non-functional requirements not already in the README (E-1).
- Human-authored content; agent-detected staleness (E-1 p = 0.038, E-7 Init Fossilization).
- Recording each rule's rationale beside it (E-3, −99.3% excess).
- Lazy, on-demand loading over always-on injection (E-2, p_Holm = 0.012).
- Treating the guide tree as a security surface, and a defensive directive in the root
  (E-5, ~60% ASR suppression).
- Marking each security rule as control-backed or advisory (E-6).

**Not licensed — do not cite these as evidence:**
- That context files improve task success. Three studies say otherwise or null (E-1, E-2).
- That repository overviews or structure maps help (E-1 §4.3), **except** where the
  repository has no other documentation (E-1 Appendix B) — not this repository.
- That file length drives outcomes (E-1 Appendix B explicit null). Budgets are justified
  by the growth ratchet (E-3), not by measured length effects.
- **That nested per-directory files help at all.** E-1, E-2 and E-4 all restrict to
  single-root configurations by design; E-2 excludes any repo with a "competing
  instruction stack." No controlled evidence exists either way. Per-directory guides are
  a risk-managed bet, and must be described as one.
