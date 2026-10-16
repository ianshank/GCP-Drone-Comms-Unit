---
name: ts-codegen
description: "Use when: changing the OpenAPI spec, regenerating the TypeScript API clients, editing anything under lib/*/src/generated, running orval, or fixing a workspace typecheck that fails on a missing lib .d.ts."
argument-hint: "The endpoint or schema that changed, and which client(s) consume it"
---

# Regenerate the TypeScript API Clients

## When to Use

- Add, remove, or change an endpoint or schema in `lib/api-spec/openapi.yaml`.
- A file under `lib/api-zod/src/generated/` or `lib/api-client-react/src/generated/`
  needs to change — the change belongs in the spec, never in the output.
- `pnpm -r run typecheck` fails with "cannot find module" for a `lib/*` package on a
  fresh clone.

## Procedure

1. Edit `lib/api-spec/openapi.yaml`. This is the only hand-edited input; both generated
   trees are derived from it.
2. Run the codegen from `lib/api-spec`:

   ```bash
   pnpm --filter @workspace/api-spec run codegen
   ```

   That script is `orval --config ./orval.config.ts && pnpm -w run typecheck:libs`, so
   it regenerates both targets and then builds the composite projects.
3. Review the regenerated diff in **both** trees before committing. They are committed
   to the repo, so a spec change that produces no diff means the codegen did not run.
4. If you changed a shared type, rebuild the composite projects and typecheck the
   whole workspace:

   ```bash
   pnpm --filter './lib/*' run build
   pnpm -r run typecheck
   ```

5. Run the workspace gate before opening a PR: `make validate-pre-pr`.

## Traps

- **`orval.config.ts` sets `clean: true` on both targets.** The generated directory is
  deleted and rewritten on every run, so a hand edit there does not conflict — it
  vanishes silently at the next codegen.
- **`lib/api-client-react/src/custom-fetch.ts` is hand-written and load-bearing.** It
  survives only because it sits one level *above* the `clean:` scope. Do not move it
  into `generated/`.
- **There are exactly two generated trees**, `lib/api-zod/src/generated/` and
  `lib/api-client-react/src/generated/`. `lib/db/src/schema/index.ts` is *not* one of
  them — drizzle-kit pushes SQL and does not emit that file, so "regenerating" it loses
  the schema.
- **Build the libs before type-checking on a fresh clone.** `lib/api-zod` and `lib/db`
  are TS composite projects (`composite: true`, `emitDeclarationOnly: true`) whose
  gitignored `dist/` `.d.ts` output must exist before dependents resolve their
  `references`. The root `Makefile` does this first; `.pre-commit-config.yaml` runs a
  bare `pnpm -r run typecheck` and does not, so that hook fails until something has
  built them.
- **`pnpm` is required.** The root `preinstall` script rejects npm and yarn outright.

## References

- Spec and config: `lib/api-spec/openapi.yaml`, `lib/api-spec/orval.config.ts`
- Path-scoped rules that fire in this area: [.claude/rules/ts-workspace.md](../../../.claude/rules/ts-workspace.md)
  and [.claude/rules/generated-code.md](../../../.claude/rules/generated-code.md)
- Workspace traps: the `lib` and `artifacts` sections of [AGENTS.md](../../../AGENTS.md)
