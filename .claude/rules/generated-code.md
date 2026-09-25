---
paths:
  - "lib/api-zod/src/generated/**"
  - "lib/api-client-react/src/generated/**"
  - "artifacts/mockup-sandbox/src/.generated/**"
  - "artifacts/mockup-sandbox/src/components/ui/**"
  - "packages/meshsa/tests/snapshots/**"
  - "archive/**"
---

# Generated and vendored trees — do not hand-edit

This is the case a directory guide cannot serve. These files look like ordinary source
when opened, and the thing you need to know about them is true *before* you type: an
edit here is discarded by the next generator run, silently and without a conflict.

## Rules

- Do not hand-edit `lib/api-zod/src/generated/**` or
  `lib/api-client-react/src/generated/**`. Edit `lib/api-spec/openapi.yaml` and rerun
  codegen — why: both orval targets set `clean: true`, so the generated directory is
  **deleted and rewritten** on every run; your edit does not conflict, it vanishes.
  Note that these trees are committed, which is exactly why an edit here looks
  permanent.
- Do not move `lib/api-client-react/src/custom-fetch.ts` into `generated/` — why: it is
  hand-written and load-bearing, and survives codegen only because it sits one level
  *above* the `clean:` scope. Moving it in deletes it on the next run.
- Do not hand-edit `artifacts/mockup-sandbox/src/.generated/**` — why: the mockup
  preview plugin rewrites it on every `vite dev` and `vite build`. It is also
  git-tracked, so a plain build can dirty the working tree and make an unrelated diff
  look like yours.
- Do not hand-edit the vendored shadcn components under
  `artifacts/mockup-sandbox/src/components/ui/**`; re-run the shadcn CLI instead — why:
  these 55 files are vendored upstream output, so a local edit is lost at the next
  component update and is invisible to review as a deliberate fork.
- Do not delete or hand-fix a file under `packages/meshsa/tests/snapshots/**` to clear a
  failing diff — why: a snapshot diff means the **wire format changed**, which is the
  signal the snapshot exists to raise. Regenerate deliberately with
  `MESHSA_UPDATE_SNAPSHOTS=1` and treat the result as a schema-version decision
  (see [.agents/skills/meshsa-schema-version-bump/SKILL.md](.agents/skills/meshsa-schema-version-bump/SKILL.md)).
- Treat `archive/**` as read-only history; do not update a snapshot during feature work
  — why: it records what shipped, so editing one destroys the record it exists to keep.
  Note the tooling asymmetry: `archive/` is five `.zip` files, so the `types: [text]`
  pre-commit hooks skip it entirely, while `gitleaks` and `check-added-large-files`
  still see it — control: `gitleaks`, in pre-commit and again in the non-bypassable CI
  `Secret scan` step.
