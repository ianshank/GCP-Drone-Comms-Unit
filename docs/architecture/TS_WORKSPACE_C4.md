# C4 Architecture — GCP-Drone-Comms-Unit Workspace

Diagrams follow the [C4 model](https://c4model.com/).  All diagrams are rendered
with [Mermaid](https://mermaid.js.org/) (GitHub, VS Code, and most CI platforms
render these natively).

> The React/Vite mockup sandbox and the `@workspace/api-client-react` hooks library were
> archived in plan P3-4 (2026-11-09) and no longer appear below; the trees are kept
> read-only under `../../archive/` (see its README). The drone-comms C4 is
> [`../C4.md`](../C4.md).

---

## Level 1 — System Context

Who uses the system and what other systems does it interact with.

```mermaid
graph TB
    dev["👤 Developer\n─────────────────\nBuilds, tests, and\nvalidates operator\nconsole components"]

    subgraph workspace["Replit Development Workspace"]
        api["🖥 API Server\n─────────────────\nExpress 5 REST API\nNode.js / TypeScript"]
    end

    subgraph external["External Systems"]
        drone["📡 GCP-Drone-Comms-Unit\n─────────────────\nproduction meshsa.ui\noperator console\n(GitHub repo)"]
        db[("🗄 PostgreSQL\n─────────────────\nReplit managed DB")]
        replit["☁ Replit Platform\n─────────────────\nHosting, secrets,\nautoscale deploy"]
    end

    dev -->|"develops / tests"| api
    dev -->|"applies validated\ndeliverables to"| drone
    api -->|"reads / writes"| db
    workspace -->|"hosted on"| replit

    classDef person fill:#08427b,color:#fff,stroke:#073b6f
    classDef system fill:#1168bd,color:#fff,stroke:#0e5fa8
    classDef external fill:#999,color:#fff,stroke:#888

    class dev person
    class api system
    class drone,db,replit external
```

---

## Level 2 — Container

The containers (deployable/runnable units) inside the workspace.

```mermaid
graph TB
    dev["👤 Developer"]

    subgraph workspace["Replit Workspace — pnpm monorepo"]
        direction TB

        subgraph apiArtifact["artifacts/api-server  [:PORT]"]
            apiApp["Express 5 Application\n─────────────\nPino HTTP logging\nCORS middleware\nJSON body parsing\nDrizzle ORM"]
        end

        subgraph libs["Shared Libraries - lib workspace"]
            dbLib["@workspace/db\n─────────────\nDrizzle schema\nClient factory\nMigrations"]
            zodLib["@workspace/api-zod\n─────────────\nZod schemas\nRequest/response\ntypes (shared)"]
        end

        subgraph deliverables["deliverables/meshsa-ui-validation/"]
            pyTests["Python test suite\n─────────────\npytest S1–S6\nconftest fixtures\nGate 0 patches"]
            sysd["Systemd unit files\n─────────────\nmeshsa-ui.service\nmeshsa-ui.env.example"]
            docs2["Documentation\n─────────────\nPeer review\nRisk acceptance\nC4 / ADR"]
        end
    end

    db[("PostgreSQL")]

    dev -->|"HTTP"| apiArtifact
    apiApp -->|"Drizzle ORM"| db
    apiApp -.->|"imports"| dbLib
    apiApp -.->|"imports"| zodLib

    classDef container fill:#1168bd,color:#fff,stroke:#0e5fa8
    classDef db fill:#2d6a2d,color:#fff,stroke:#1e4d1e
    classDef lib fill:#555,color:#fff,stroke:#444
    classDef deliverable fill:#6b3a8e,color:#fff,stroke:#5a2f78

    class apiApp container
    class db db
    class dbLib,zodLib lib
    class pyTests,sysd,docs2 deliverable
```

---

## Level 3 — Component (API Server)

The components inside the `api-server` container.

```mermaid
graph TB
    client["HTTP Client\n(curl / browser / test runner)"]

    subgraph apiServer["@workspace/api-server"]
        index["index.ts\n─────────────\nPORT validation\napp.listen()\nProcess lifecycle"]

        subgraph appModule["app.ts — Express application"]
            pinoHttp["pino-http\nmiddleware\n(structured logging)"]
            corsM["CORS\nmiddleware"]
            bodyP["Body parsers\n(JSON + URLencoded)"]
            router["Router\n/api/*"]
        end

        subgraph routes["routes/"]
            healthR["health.ts\nGET /api/healthz\n→ { status: 'ok' }"]
            indexR["index.ts\nRoute registry"]
        end

        subgraph libDir["lib/"]
            loggerM["logger.ts\nPino instance\nLOG_LEVEL from env\nHeader redaction"]
        end

        subgraph tests["src/__tests__/"]
            healthT["health.test.ts\nUnit + integration"]
            appT["app.test.ts\nMiddleware tests"]
            loggerT["logger.test.ts\nConfiguration tests"]
        end
    end

    db[("@workspace/db\nPostgreSQL")]
    zodLib["@workspace/api-zod\nZod schemas"]

    client -->|"HTTP request"| index
    index --> appModule
    pinoHttp --> loggerM
    appModule --> router
    router --> indexR
    indexR --> healthR
    healthR -->|"HealthCheckResponse.parse()"| zodLib

    classDef entry fill:#08427b,color:#fff,stroke:#073b6f
    classDef middleware fill:#1168bd,color:#fff,stroke:#0e5fa8
    classDef route fill:#444,color:#fff,stroke:#333
    classDef lib2 fill:#2d6a2d,color:#fff,stroke:#1e4d1e
    classDef test fill:#6b3a8e,color:#fff,stroke:#5a2f78

    class index entry
    class pinoHttp,corsM,bodyP,router middleware
    class healthR,indexR route
    class loggerM lib2
    class healthT,appT,loggerT test
```

---

## Deployment

```mermaid
graph LR
    src["Source\n(Replit Workspace)"]
    build["esbuild bundle\ndist/index.mjs"]
    deploy["Replit Autoscale\nDeployment"]
    proxy["Replit Proxy\n(mTLS + path routing)"]
    user["End User\nBrowser"]

    src -->|"pnpm build"| build
    build -->|"publish"| deploy
    deploy --> proxy
    user -->|"HTTPS"| proxy
    proxy -->|"/api/*"| deploy
```

---

## Key architectural decisions

See [`docs/adr/`](../adr/) for full Architecture Decision Records.

| Decision | Choice | Rationale |
|---|---|---|
| Package manager | pnpm workspaces | Strict hoisting, catalog pinning, `minimumReleaseAge` security policy |
| Module format | ESM (`"type": "module"`) | Native Node.js ESM; compatible with Vite and Vitest without transforms |
| Bundler | esbuild (api-server) | Sub-second single-file Node.js bundle (Vite left with the archived sandbox) |
| Logging | pino + pino-http | Structured JSON; lowest-overhead Node.js logger; header redaction built-in |
| Schema validation | Zod (shared via @workspace/api-zod) | Single source of truth for request/response shapes; TypeScript inference |
| ORM | Drizzle | Type-safe SQL; minimal runtime; schema-first migrations |
| Testing | Vitest | ESM-native; works without transforms; compatible with pnpm workspaces |
| Container runtime | Node.js 24 Alpine | Smallest footprint; LTS; ESM built-in support |
