# GCP-Drone-Comms-Unit — Development Workspace

[![CI](https://github.com/ianshank/GCP-Drone-Comms-Unit/actions/workflows/ci.yml/badge.svg)](https://github.com/ianshank/GCP-Drone-Comms-Unit/actions/workflows/ci.yml)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-blue)](https://www.typescriptlang.org/)
[![Node](https://img.shields.io/badge/Node.js-24.x-brightgreen)](https://nodejs.org/)
[![pnpm](https://img.shields.io/badge/pnpm-workspace-orange)](https://pnpm.io/)

pnpm monorepo: REST API server and its shared libraries, with
validation deliverables for the
[GCP-Drone-Comms-Unit](https://github.com/ianshank/GCP-Drone-Comms-Unit)
`meshsa.ui` operator console.

> **Looking for the drone-comms framework itself, not this validation workspace?**
> The Python side of this repository — `meshsa` (telemetry/mesh-SA/CoT bridge),
> `jetson_yolo_gcs` (on-board perception), `flightctl/` (ops layer), `hardware/`,
> and `ops/` — lives outside this pnpm tree. Start at
> [`docs/CHARTER.md`](docs/CHARTER.md) (scope + invariants),
> [`docs/ROADMAP.md`](docs/ROADMAP.md) (milestone trajectory), and
> [`packages/meshsa/README.md`](packages/meshsa/README.md) (framework-specific
> setup). This README and everything below it describes only the TypeScript
> validation/preview workspace for `meshsa.ui`.

---

## Workspace packages

| Package | Kind | Port | Description |
|---|---|---|---|
| `@workspace/api-server` | API | `$PORT` | Express 5 REST server, structured logging (pino), Drizzle ORM |
| `@workspace/db` | Library | — | Drizzle schema, migrations, client factory |
| `@workspace/api-zod` | Library | — | Zod schemas shared between server and clients |

---

## Quick start

```bash
# Install dependencies (frozen lockfile)
make install

# Run the API server locally (build + start)
make dev-api
```

The React/Vite mockup sandbox and the React Query client it consumed were archived in
plan P3-4 (`archive/mockup-sandbox/`, `archive/api-client-react/`; see
[`archive/README.md`](archive/README.md)). They are not workspace members.

---

## Architecture

See [`docs/architecture/TS_WORKSPACE_C4.md`](docs/architecture/TS_WORKSPACE_C4.md) for the full C4
context/container/component diagrams.

```
┌──────────────────────────────────────────────────┐
│                 pnpm Monorepo                    │
│                                                  │
│  ┌──────────────┐                                │
│  │  api-server  │  Express 5 · pino · Drizzle    │
│  └──────┬───────┘                                │
│         │ imports                                │
│  ┌──────▼───────────────────────────────┐        │
│  │  @workspace/db   @workspace/api-zod  │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│  lib/api-spec/openapi.yaml ──orval──▶ api-zod    │
└──────────────────────────────────────────────────┘
```

---

## Development

### Prerequisites

- Node.js ≥ 24
- pnpm, at the version pinned by `packageManager` in `package.json` (`corepack enable` selects it)
- PostgreSQL (or Replit managed DB)

### Environment variables

Copy and fill in secrets:

```bash
# Required for api-server
PORT=8080             # Set by Replit automatically
NODE_ENV=development
LOG_LEVEL=debug       # pino log level (trace|debug|info|warn|error)
DATABASE_URL=...      # PostgreSQL connection string

# Optional
SESSION_SECRET=...    # For future auth middleware
```

> **Never commit secrets.** All sensitive values must be in environment
> variables or Replit Secrets — never in source code or config files.
> `gitleaks` runs in pre-commit and again in the CI `Secret scan` step.

---

## Testing

```bash
# Run full test suite across all packages
make test

# Watch mode during development
pnpm --filter @workspace/api-server run test:watch

# Coverage report
make coverage
```

Test files live alongside source in `__tests__/` and package `tests/` directories.
See [`docs/LOCAL_TESTING_PLAN.md`](docs/LOCAL_TESTING_PLAN.md) for the complete test taxonomy, setup, and execution strategy.

---

## Validation (pre-PR)

Run the full validation gate before opening a PR:

```bash
make validate
```

This runs in order: **typecheck → lint → test → build**. All steps must pass.

For detailed output of each step individually:

```bash
make typecheck   # TypeScript strict type checking
make lint        # ESLint (no warnings permitted)
make test        # Vitest unit + integration tests
make build       # Production bundle (esbuild)
```

`make validate` is exactly steps 1–4 of `scripts/validate-pre-pr.sh`; `make validate-pre-pr`
runs the whole gate (TypeScript, Python and governance).
```

---

## Deliverables

`deliverables/meshsa-ui-validation/` contains execution-ready artifacts for
the [`GCP-Drone-Comms-Unit`](https://github.com/ianshank/GCP-Drone-Comms-Unit)
`meshsa.ui` field validation:

```
deliverables/meshsa-ui-validation/
├── docs/                        # PEER_REVIEW (primary review), port deconfliction, residual risk
├── tests/                       # Named scenario tests S1–S6 (Python/pytest)
├── patches/                     # Gate 0.1 / 0.3 source patches
├── systemd/                     # meshsa-ui.service + env template
└── README.md                    # Integration checklist
```

See [`deliverables/meshsa-ui-validation/README.md`](deliverables/meshsa-ui-validation/README.md)
for the step-by-step integration guide.

---

## Project structure

```
.
├── artifacts/
│   ├── api-server/          # Express REST API
│   │   ├── src/
│   │   │   ├── __tests__/   # Vitest tests
│   │   │   ├── lib/         # logger, shared utilities
│   │   │   └── routes/      # Express route handlers
│   │   └── build.mjs        # esbuild bundle script
├── deliverables/            # External repo validation artifacts
│   └── meshsa-ui-validation/
├── docs/                    # CHARTER, ROADMAP, C4, NEXTSTEPS and the plans (stable + working)
│   ├── architecture/        # TS_WORKSPACE_C4.md — the TypeScript workspace's C4
│   ├── adr/                 # Architecture Decision Records
│   ├── reviews/             # Historical records (point-in-time reviews and audits)
│   └── specs/               # One spec per roadmap/initiative feature
├── lib/
│   ├── api-zod/             # Shared Zod schemas
│   └── db/                  # Drizzle ORM schema + client
├── scripts/
│   ├── validate-pre-pr.sh   # Full pre-PR validation gate
│   └── hooks/               # Git hook scripts
├── archive/                 # Read-only history: ZIP snapshots + the archived TS trees
├── Makefile                 # Thin aliases for the TS steps of scripts/validate-pre-pr.sh
├── .gitleaks.toml           # Secret scanning configuration
├── .pre-commit-config.yaml  # Pre-commit hook configuration
└── pnpm-workspace.yaml      # pnpm workspace definition
```

---

## Deployment

This workspace deploys via Replit Autoscale. The `api-server` artifact is
the deployable unit — it builds to a single `dist/index.mjs` bundle via
esbuild and runs as a Node.js ESM process.

```bash
# Production build (used by Replit deploy)
pnpm --filter @workspace/api-server run build
```

See [Replit deployment docs](https://docs.replit.com/hosting/autoscale-deployments)
for publish instructions.

---

## Contributing

1. Branch from `main`
2. Write tests for any new behaviour
3. Run `make validate` — all checks must pass
4. Open a PR with a description referencing the relevant issue or deliverable
5. Let pre-commit run `gitleaks`; CI runs it again and is the non-bypassable copy

### Conventions

- **No hardcoded values** — all configuration via environment variables
  (read with `process.env["KEY"]`, never with `process.env.KEY`)
- **Structured logging** — use `logger` from `./lib/logger`, never `console.*`
- **Named exports** — prefer named exports over default for testability
- **Types first** — every function parameter and return type must be annotated
- **Fail loudly** — throw on unexpected state; never silently return `undefined`
