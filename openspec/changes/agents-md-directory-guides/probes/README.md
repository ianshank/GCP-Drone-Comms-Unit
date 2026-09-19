# Probes — round-3 feasibility evidence

Round 3 of the peer review (`docs/OPENSPEC_AGENTS_MD_PEER_REVIEW.md`, findings R-1 … R-7)
replaced argument with measurement. These are the artefacts. They are **not** guides and
**not** the deliverable: the filenames deliberately avoid the `AGENTS.md` suffix so no
current or future checker enumerates them as part of the tree.

| File | What it establishes |
| ---- | ------------------- |
| `probe-flightctl-guide.md` | A real Tier 1 guide authored to the D-3 contract. Passes every check with zero findings at **exactly 80 lines** — which is why the Tier 1 budget moved to 90 (R-1) |
| `probe-meshsa-core-guide.md` | A Tier 2 guide for the densest realistic case, carrying the `command/ (frozen)` subsection. **53 lines against a 60 budget** — Tier 2 verified adequate |
| `spike_validate_agents_docs.py` | A throwaway implementation of the rev.2 check set, run against the five existing guides. Produced R-2 (both duplicate detectors fail), R-3 (9 false positives → 1), R-4 (the colliding-target scenario is unimplementable as specified) and R-6 (~11% false positives on injection hygiene) |

Run it:

```bash
python3 openspec/changes/agents-md-directory-guides/probes/spike_validate_agents_docs.py
```

The spike is a measurement instrument, not a draft of `tools/validate_agents_docs.py`.
T-1.3 writes the real checker to the house conventions — stdlib-only, module-constant
policy, `git ls-files` enumeration, declared exceptions — and carries the five check-5
corrections the spike established. Starting from this file would import its shortcuts.
