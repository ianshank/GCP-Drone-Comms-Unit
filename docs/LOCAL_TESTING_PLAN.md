# Local Test Execution Plan & Quality Verification Guide

> **Document Status:** ACTIVE & MAINTAINED
> **Target Branch:** `feat/test-plan-suite`
> **Repository:** `https://github.com/ianshank/GCP-Drone-Comms-Unit`

---

## 1. Executive Summary & Goals

This document outlines the comprehensive strategy for executing all test suites locally across Python services, perception pipelines, security tools, and TypeScript libraries in `GCP-Drone-Comms-Unit`.

### Coverage Requirements & Quality Gates
- **Global Minimum Coverage:** 80% (Project standard enforces **≥97%** in `meshsa` and **≥96%** in `jetson_yolo_gcs`).
- **Achieved Coverage:** 
  - `packages/meshsa`: **99.54%** (1090 passed)
  - `packages/jetson_yolo_gcs`: **99.34%** (205 passed)
  - `tools/claude_hooks`: **100%** (62 passed)
  - `@workspace/api-server`: **100%** (27 passed)

---

## 2. Test Taxonomy Matrix

| Test Category | Target Component(s) | Execution Command | Purpose & Scope |
| :--- | :--- | :--- | :--- |
| **Smoke / Sanity** | MeshSA, Jetson Perception | `python -m pytest packages/jetson_yolo_gcs/tests/unit/test_imports_clean.py packages/meshsa/tests/test_config.py` | Rapid validation of package imports, config defaults, and entry points (<2s execution). |
| **Unit Tests** | MeshSA, Jetson Perception, API Server | `python -m pytest packages/meshsa/tests` <br>`python -m pytest packages/jetson_yolo_gcs/tests/unit` <br>`pnpm --filter @workspace/api-server run test` | Validates isolated functions, pure codecs, protocol interfaces, data structures, and loggers using DI fakes (`FakeClock`, `SeqIdFactory`). |
| **Integration / Functional** | Router, Transports, Scout, UI App | `python -m pytest packages/meshsa/tests/test_tak.py packages/meshsa/tests/test_mavlink_source.py packages/meshsa/tests/test_scout_station.py packages/meshsa/tests/test_ui_app.py` | Validates component wiring, async event loops, aiohttp services, MAVLink message pumps, and Scout station pipelines. |
| **End-to-End (E2E)** | MeshSA Detection & FreeTAKServer | `python -m pytest packages/meshsa/tests/test_detection_e2e.py packages/meshsa/tests/test_inference_e2e.py` <br>(Live FTS opt-in: `$env:MESHSA_FTS_E2E=1; python -m pytest packages/meshsa/tests/e2e/test_fts_e2e.py`) | Multi-service lifecycle verification (detection ingest → codec → TAK client transport → FTS receiver). |
| **User Journey** | Scout Mission & UI Console | `python -m pytest packages/meshsa/tests/test_scout_pipeline.py packages/meshsa/tests/test_scout_replay.py packages/meshsa/tests/test_ui_snapshot.py` | Simulates operator workflows: terrain elevation sampling, mission export/replay, log ring buffer snapshots, and UI state render. |
| **Regression & Soak** | Radio Link Loss & Backoff | `python -m pytest packages/meshsa/tests/test_link_loss_soak.py packages/meshsa/tests/test_gap_fills.py packages/meshsa/tests/test_backoff.py` | Tests network loss recovery, backoff timers, pacing queues, and continuous radio disconnect/reconnect cycles. |
| **Security & Governance** | Transport Auth, Pre-flight Safety, AI Agent Hooks | `python -m pytest packages/meshsa/tests/test_netauth.py packages/meshsa/tests/test_arm_guard.py tools/claude_hooks/tests` | Verifies mutual auth, token validation, `ArmGuard` pre-flight RC safety interlocks, bind guard loopback enforcement, and tool governance rules. |

---

## 3. Dependency Management & Installation

### Python Workspaces
```powershell
# Install MeshSA with developer, meshtastic, and UI extras
python -m pip install -e "packages/meshsa[dev,meshtastic,ui]"

# Install Jetson YOLO GCS package in editable mode
python -m pip install -e "packages/jetson_yolo_gcs"
```

### Node / TypeScript Workspace
```powershell
# Install Node workspace dependencies
pnpm install
```

---

## 4. Full Verification Suite Command Suite

### 1. Python Framework Suite (`packages/meshsa`)
```powershell
cd packages/meshsa
python -m pytest
mypy src
ruff check .
ruff format --check .
python -m build
```

### 2. On-Board Perception Suite (`packages/jetson_yolo_gcs`)
```powershell
cd packages/jetson_yolo_gcs
python -m pytest
```

### 3. Developer Tools & AI Governance Hooks (`tools`)
```powershell
python -m pytest tools/claude_hooks/tests tools/tests
```

### 4. TypeScript Workspace (`artifacts/api-server` & `lib/*`)
```powershell
pnpm run typecheck
pnpm run lint
pnpm test
```

### 5. Full Repository Pre-PR Gate Script
```powershell
bash scripts/validate-pre-pr.sh
```

---

## 5. Objective Peer Review & Architectural Audit

### Adherence to Project Charter (`docs/CHARTER.md`)
1. **Scope & Non-Goals (§3):** 
   - `meshsa` core remains strictly a telemetry ingest, CoT codec, and mesh routing package.
   - Ground-side FPV interlock (`ArmGuard`) only gates arm low until health checks pass and does not intervene in flight.
   - `jetson_yolo_gcs` operates as an advisory landing target publisher with zero autonomous commanding authority.
2. **Invariants (§4):**
   - **Invariant 1 (Open/Closed):** Transports and codecs are registered via `transport_registry` / `codec_registry` without editing router or node code.
   - **Invariant 2 (Versioned Wire):** Envelopes maintain `schema_version` backward compatibility.
   - **Invariant 3 (Dependency Injection):** All I/O operations are abstracted behind `Protocol` types (`Transport`, `Codec`, `Clock`, `IdFactory`). Unit tests execute using fakes without needing hardware, radios, or live servers.
   - **Invariant 5 (Config Driven):** All operational parameters use pydantic models with explicit default values.
   - **Invariant 6 (Quality Gates):** Minimum required coverage gates (97% on meshsa, 96% on jetson_yolo_gcs) are strictly enforced in pytest configuration. Current execution achieves **>99%** on both.

### Adherence to Modern 2026 Best Practices
- **Backwards Compatibility:** Cross-platform Node script execution (`package.json`) ensures Windows, Linux, and macOS dev environments operate without shell dependency issues.
- **Modularity:** Isolated subpackages (`meshsa`, `jetson_yolo_gcs`, `api-server`, `claude_hooks`) allow decoupled development and targeted test execution.
- **Fail-Closed Security:** Loopback bind guards, pre-flight interlocks, and transport token authentication prevent unauthenticated network exposure.

