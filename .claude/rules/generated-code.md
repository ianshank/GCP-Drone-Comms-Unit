---
paths:
  - "lib/api-zod/src/generated/**"
  - "packages/meshsa/tests/snapshots/**"
  - "archive/**"
---

# Generated and vendored trees — do not hand-edit

This is the case a directory guide cannot serve. These files look like ordinary source
when opened, and the thing you need to know about them is true *before* you type: an
edit here is discarded by the next generator run, silently and without a conflict.

## Rules

- Do not hand-edit `lib/api-zod/src/generated/**`. Edit `lib/api-spec/openapi.yaml` and
  rerun codegen — why: the orval target sets `clean: true`, so the generated directory is
  **deleted and rewritten** on every run; your edit does not conflict, it vanishes.
  Note that the tree is committed, which is exactly why an edit here looks permanent.
  (The React client and the mockup sandbox's generated and vendored trees were archived
  under `archive/` by plan P3-4 and are covered by the archive rule below.)
- Do not delete or hand-fix a file under `packages/meshsa/tests/snapshots/**` to clear a
  failing diff — why: a snapshot diff means the **wire format changed**, which is the
  signal the snapshot exists to raise. Regenerate deliberately with
  `MESHSA_UPDATE_SNAPSHOTS=1` and treat the result as a schema-version decision
  (see [.agents/skills/meshsa-schema-version-bump/SKILL.md](../../.agents/skills/meshsa-schema-version-bump/SKILL.md)).
- Treat `archive/**` as read-only history; do not update a snapshot or an archived tree
  during feature work — why: it records what shipped, so editing one destroys the record
  it exists to keep. Note the tooling asymmetry: the five `.zip` files are skipped by the
  `types: [text]` pre-commit hooks, and the two archived source trees (`mockup-sandbox/`,
  `api-client-react/`, since plan P3-4) are excluded from the hygiene hooks and are not
  pnpm workspace members, so nothing type-checks or lints them; `gitleaks` and
  `check-added-large-files` still see all of it — control: `gitleaks`, in pre-commit and
  again in the non-bypassable CI `Secret scan` step.
