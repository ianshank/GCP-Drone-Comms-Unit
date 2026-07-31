# ADR-001: pnpm Workspace + TypeScript ESM + esbuild

**Status:** Accepted
**Date:** 2026-07-28
**Deciders:** Engineering team

---

## Context

We need a monorepo structure for a REST API server and a UI component preview
sandbox that share type-safe schemas and a database client.  Key constraints:

1. Both the API server (Node.js) and the sandbox (browser) are TypeScript.
2. Schema definitions must be written once and consumed by both.
3. The API server must produce a single deployable artefact (no `node_modules`
   in production image).
4. The development environment is Replit (Linux/NixOS, `pnpm` available).
5. All packages must use native ES Modules — no CommonJS transpilation.

---

## Decision

### Package manager: pnpm workspaces

**Chosen over:** npm workspaces, Yarn Berry, Turborepo.

**Rationale:**
- Strict dependency hoisting prevents phantom dependencies (packages
  accidentally available without being listed in `package.json`).
- `catalog:` feature in `pnpm-workspace.yaml` pins shared dep versions once.
- `minimumReleaseAge: 1440` (24 h) supply-chain policy is pnpm-native.
- Replit's scaffold uses pnpm; no toolchain divergence.

### Module format: ESM (`"type": "module"`)

**Chosen over:** CommonJS, dual CJS+ESM.

**Rationale:**
- Node.js ≥ 22 has full native ESM support including `--experimental-vm-modules`
  for Jest/Vitest.
- Vite (the sandbox bundler) is ESM-first; mixing CJS in a workspace creates
  interop friction.
- `import.meta.url`, top-level `await`, and named exports are first-class.
- Tree-shaking works correctly across workspace packages.

**Trade-off:** Dynamic `require()` calls in third-party CJS packages require
`createRequire()` shim in `build.mjs`. Acceptable one-time cost.

### Bundler: esbuild (API) + Vite (sandbox)

**Chosen over:** Webpack, Rollup, SWC.

**Rationale:**
- esbuild produces a single `dist/index.mjs` in < 1 s. This is the production
  artefact shipped in the Docker image. No `node_modules` required at runtime.
- Vite is the established choice for browser dev servers with HMR. Using it
  for the sandbox keeps the Radix UI + Tailwind stack well-supported.
- Using one bundler for both (e.g. Vite for Node) was evaluated and rejected:
  Vite's Node output requires additional plugins and produces larger bundles
  than esbuild.

### TypeScript: strict project references

**Chosen over:** single tsconfig, transpile-only (ts-node, esbuild).

**Rationale:**
- Project references (`tsconfig.json` references array) enable incremental builds
  and enforce that cross-package imports only use published types.
- `tsconfig.base.json` centralises `strict: true`, `noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes` — all packages inherit these.
- Build-time type checking catches API contract violations at PR time, not
  runtime.

### Test runner: Vitest

**Chosen over:** Jest, Mocha, node:test.

**Rationale:**
- ESM-native; no `transform` configuration needed for TypeScript or ESM imports.
- Compatible with pnpm workspaces and TypeScript project references out of the
  box.
- Vitest's coverage provider (`@vitest/coverage-v8`) uses Node.js's built-in
  V8 coverage — no instrumentation overhead.
- API matches Jest for easy migration of existing test patterns.

### Logging: pino

**Chosen over:** winston, bunyan, console.log.

**Rationale:**
- Structured JSON output compatible with log aggregators (Datadog, CloudWatch,
  Replit logs).
- Lowest latency of any Node.js logger (worker-thread transport).
- `pino-http` middleware integrates request IDs and serializers with Express.
- Header redaction (`req.headers.authorization`, `cookie`, `set-cookie`) is
  first-class in pino's `redact` option.

---

## Consequences

### Positive

- Single source of truth for types via shared `@workspace/api-zod` package.
- Sub-second incremental TypeScript builds.
- Production Docker image contains only the bundle — no `node_modules`.
- Native ESM in tests and source means no CJS/ESM boundary friction.

### Negative / trade-offs

- Developers must use `process.env["KEY"]` (bracket notation) everywhere —
  enforced by ESLint rule. Dot notation is disallowed.
- `create-require` shim in `build.mjs` is required for pino's worker transport
  (which uses `require` internally). Must be updated if build script changes.
- pnpm is required; `npm install` will fail (enforced by `preinstall` script).
- TypeScript project references require `tsc -b` (build mode) for incremental
  compilation; `tsc -p` alone will not build dependency packages.

---

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Yarn Berry (PnP) | Replit scaffold does not support PnP; peer dep issues with Radix UI |
| CJS throughout | Incompatible with Vite HMR and ESM-first dependencies |
| Turborepo | Additional build graph complexity; pnpm's built-in task cache is sufficient |
| Jest | Requires `@jest/globals` + transform config for ESM; Vitest is simpler |
| Single package (no monorepo) | Schema types would need manual duplication between server and client |
