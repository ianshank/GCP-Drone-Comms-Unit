# Multi-stage production build for @workspace/api-server
#
# Usage:
#   docker build -t gcp-drone-api .
#   docker run --rm -p 8080:8080 -e PORT=8080 -e NODE_ENV=production gcp-drone-api
#
# Stages:
#   deps     — install production + dev dependencies (pnpm workspace)
#   build    — typecheck + esbuild bundle → dist/index.mjs
#   runtime  — minimal Node 24 Alpine image; non-root user; no dev deps
#
# Environment variables (required at runtime):
#   PORT          TCP port to listen on
#   NODE_ENV      "production" (set in this file)
#   DATABASE_URL  PostgreSQL connection string
#   LOG_LEVEL     pino log level (default: info)

# ── Stage 1: deps ─────────────────────────────────────────────────────────────
FROM node:24-alpine AS deps

# Install pnpm via corepack (matches engines field)
RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Copy workspace manifests first for layer caching
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY artifacts/api-server/package.json      ./artifacts/api-server/
COPY lib/db/package.json                    ./lib/db/
COPY lib/api-zod/package.json              ./lib/api-zod/
COPY lib/api-client-react/package.json     ./lib/api-client-react/ 2>/dev/null || true

# Install ALL deps (dev included — needed for build step)
RUN pnpm install --frozen-lockfile

# ── Stage 2: build ────────────────────────────────────────────────────────────
FROM deps AS build

# Copy source
COPY tsconfig.base.json tsconfig.json ./
COPY artifacts/api-server/ ./artifacts/api-server/
COPY lib/db/              ./lib/db/
COPY lib/api-zod/         ./lib/api-zod/
COPY lib/api-client-react/ ./lib/api-client-react/ 2>/dev/null || true

# Build the API server bundle
RUN pnpm --filter @workspace/api-server run build

# ── Stage 3: runtime ──────────────────────────────────────────────────────────
FROM node:24-alpine AS runtime

# Security: run as non-root
RUN addgroup -g 1001 -S appgroup && \
    adduser  -u 1001 -S appuser -G appgroup

WORKDIR /app

# Copy only the production bundle
COPY --from=build --chown=appuser:appgroup /app/artifacts/api-server/dist ./dist

# The esbuild bundle inlines all deps; nothing else to copy.
# If you add native addons (e.g. better-sqlite3), copy node_modules here.

USER appuser

# Runtime defaults
ENV NODE_ENV=production \
    PORT=8080 \
    LOG_LEVEL=info

EXPOSE 8080

# Health check — mirrors the /api/healthz route
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://localhost:${PORT}/api/healthz" | grep -q '"status":"ok"' || exit 1

ENTRYPOINT ["node", "--enable-source-maps", "./dist/index.mjs"]
