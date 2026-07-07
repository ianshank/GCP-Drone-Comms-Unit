# Roadmap Reconciliation — an external "Architectural Roadmap" vs. this repository

> **Why this file exists.** An external "Architectural Roadmap and Development Strategy for
> the GCP-Drone-Comms-Unit" was circulated. Its own preamble states it was written **without
> access to the repository** and reconstructed from a developer's public footprint. Read
> against the actual code, most of its premises do not hold. This document records the
> reconciliation so future contributors (and AI agents) are not misled into building against a
> fictional architecture. The stable plan remains [CHARTER.md](CHARTER.md) →
> [ROADMAP.md](ROADMAP.md) → [NEXTSTEPS.md](NEXTSTEPS.md).

## The core mismatch

The document assumes a cloud-hosted, Java/Spring-Boot, Langfuse-instrumented, autonomous
LLM-**swarm** that *commands* drones. This repository is the opposite by design: a
self-hosted **edge** framework (`meshsa`) that is **read-only on the vehicle by default**, in
pure Python, with narrowly-scoped, human-supervised write carve-outs (see CHARTER §3).

| Document claim | Reality in this repo | Verdict |
| --- | --- | --- |
| "GCP" = **Google Cloud Platform**; cloud data routing, Drone CI, `konf`/`konfig` | [README](../README.md): *"'GCP' here is not Google Cloud Platform … no cloud backend"* — fully self-hosted edge. CI is **GitHub Actions only** (`.github/workflows/`). | **Inapplicable** |
| **Langfuse** observability + a `_url_encode` `%2F` routing bug to work around | **Zero** Langfuse references anywhere. Observability is hand-rolled Prometheus (`metrics.py`, `health.py`) + a Grafana dashboard. | **Inapplicable** |
| **Spring Boot** backend; migrate `junit-vintage` → JUnit 5 | **No Java/Maven/Gradle/JUnit** in the tree. Pure Python + shell; pytest/ruff/mypy. | **Inapplicable** |
| **Granite MoE** / VLA / ELASTIC edge models | No Granite. The LLM layer is Anthropic (`meshsa.llm`, **read-only**) + an optional **NVIDIA Nemotron NIM** bridge (`meshsa.inference`). | **Inapplicable** |
| Autonomous LLM **swarm that commands drones**, shared-workspace multi-agent, AIPL/`@agent` routing | Antithetical to **CHARTER §3**: read-only by default; only *bounded, human-supervised* commanding (Initiative C), gated on M2. No swarm, no autonomy. | **Out of scope (CHARTER §3)** |
| **uXRCE-DDS / ROS2** bridge | Not present; vehicle integration is MAVLink / MSP / CRSF / Meshtastic / TAK. | **Out of scope (for now)** |
| Dual-processor HAL, MAVLink Router, hardware matrix | Partially real: `flightctl` uses `mavp2p`; `jetson_yolo_gcs` is the Jetson perception package; `hardware/` holds enclosures. The framing is loosely correct even though the details are invented. | **Already covered** (differently) |

### On the document's "§5 technical debt"

The two upstream issues the document cites as blockers were independently verified (2026-07)
and belong to **other projects**, not this repo:

- **Spring Boot [#25094](https://github.com/spring-projects/spring-boot/issues/25094)** —
  *"Failed to parse version of junit:junit: 4.13.1"* is **closed** and labelled
  `for: external-project` + `status: invalid`; the Spring Boot maintainers ruled it a
  JUnit-Vintage (`JUnit4VersionCheck.parseVersion`) problem, not theirs. This repo has no
  JUnit at all.
- **Langfuse [#10184](https://github.com/langfuse/langfuse/issues/10184)** — a genuine bug,
  but specific to the Langfuse **Python SDK** double-URL-encoding folder-path (`%2F`) dataset
  names. This repo does not depend on Langfuse.

Neither has any surface here, so the document's §5 remediation work is not actionable.

## Per-section verdicts

| Doc §  | Topic | Verdict |
| --- | --- | --- |
| §1  | "Dual-domain GCP" (Google Cloud + Ground Control Points) | Google-Cloud half **inapplicable**; Ground-Control-Point half is a *future candidate* (see below). |
| §2  | Edge HAL / dual-processor / MAVLink Router / uXRCE-DDS | Partly **already covered** (`flightctl`/`jetson_yolo_gcs`); ROS2/DDS **out of scope**. |
| §3  | Multi-agent swarm framework / AIPL / `@agent` routing | **Out of scope (CHARTER §3)** — read-only, no swarm/autonomy. |
| §4  | Vision / Flight / Comms / Watchdog "subagents" | Framing rejected; the real analogues already exist (`cv`/`scout`, `command`, `transports`, `health`/`metrics`) as plain modules, not LLM agents. |
| §5  | Langfuse + JUnit "technical debt" | **Inapplicable** (verified upstream, other projects). |
| §5.3 | LLM/VLA model selection | The **in-scope** slice → advanced here as the `meshsa.inference` Track-B backlog. |
| §6  | Swarm sim / disaster response / neuro-symbolic | **Out of scope** (SITL appears only as a Scout HW follow-up). |
| §7  | Development sequence | Superseded by the real ROADMAP milestones. |

## What was genuinely actionable (and done)

The document's real, in-scope through-lines — **token/latency pressure**, **"disconnected
scenarios where cloud APIs are unreachable,"** and **multi-model selection** — map onto the
already-planned Track-B backlog for `meshsa.inference`
([specs/initiative-e-inference.md](specs/initiative-e-inference.md) §5). Those four items are
now implemented: **local rate limiting**, **structured (JSON) response parsing**,
**multi-model allow-list**, and **offline queue/replay**. See
[NEXTSTEPS.md](NEXTSTEPS.md) → "AI Inference (initiative E)".

## Future candidate (recorded, not started)

The one genuinely novel, CHARTER-compatible idea in the document is **surveyed Ground Control
Point markers** (the photogrammetry kind) to anchor `meshsa.scout` / `meshsa.cv.geo`
georeferencing for higher spatial accuracy. It is compatible with the read-only charter
(markers are survey inputs, not vehicle commands) but was **not** part of this change. If
pursued, it belongs under the Scout initiative with its own spec.
