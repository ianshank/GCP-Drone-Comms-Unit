---
paths:
  - "lib/**/*.ts"
  - "lib/**/*.json"
  - "artifacts/**/*.ts"
  - "artifacts/**/*.tsx"
  - "artifacts/**/*.json"
---

# TypeScript workspace

Fires in `lib/` and `artifacts/`. The root [AGENTS.md](AGENTS.md) carries the same
facts; this file exists so they arrive when you are in the workspace rather than only
at session start.

## Rules

- Build the libs before running a workspace typecheck — why: `lib/api-zod` and `lib/db`
  are TS composite projects (`composite: true`, `emitDeclarationOnly: true`) whose
  gitignored `dist/` `.d.ts` output must exist before dependents resolve their
  `references`; on a fresh clone a bare `pnpm -r run typecheck` fails for that reason
  alone. The root `Makefile` runs `pnpm --filter './lib/*' run build` first, but
  `.pre-commit-config.yaml` does **not**, so that hook has this failure mode.
- Change the OpenAPI spec, never the generated clients — why: `orval.config.ts` sets
  `clean: true` on both targets, so the generated directory is deleted and rewritten
  each run. There are exactly two generated trees, and both are committed, which is why
  editing one looks like it worked.
- Leave `lib/db/src/schema/index.ts` hand-written — why: drizzle-kit pushes SQL, it does
  not emit that file, so treating it as generated and "regenerating" it loses the
  schema.
- Do not add a network listener in `artifacts/` without recording it in
  [docs/AUDIT_M2_AUTH.md](docs/AUDIT_M2_AUTH.md) — why: `bind_guard`'s `SCAN_GLOBS` is
  Python-only, so no TypeScript listener has ever been in its scope; the existing
  `api-server` all-interfaces bind went unnoticed for exactly this reason
  — control: none mechanical for TypeScript — advisory, and that gap is the point:
  delegate to the **bind-auditor** subagent and add the row by hand.
- Keep `PORT` (both artifacts) and `BASE_PATH` (`mockup-sandbox/vite.config.ts` only)
  throwing when unset — why: a silent default would bind or mount somewhere nobody
  intended; failing at startup is the intended behaviour, not an oversight to fix
  — control: the throws themselves, in `artifacts/api-server/src/index.ts` and
  `artifacts/mockup-sandbox/vite.config.ts`; nothing external re-checks them, so
  deleting one removes the only guard.
- Treat the esbuild `banner` and `external` list in `api-server` as load-bearing — why:
  they are what keep the bundle runnable; trimming them produces a build that succeeds
  and fails at run time.
- Do not assume a workspace has a test script — why: among `artifacts/*` only
  `api-server` defines one; `mockup-sandbox` has none, so "tests pass" there means
  nothing ran.
