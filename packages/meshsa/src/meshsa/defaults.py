"""Single source of truth for cross-module operational defaults (CHARTER §4 Invariant 5:
every operational value is a config field with an explicit default — this module is where
those defaults live, so they stop being copy-pasted literals at each call site).

A leaf module: no imports from the rest of ``meshsa``, so every config model and transport
can depend on it without risk of a cycle.

Adoption is staged deliberately (code-hygiene-modularity tasks.md): the service-port table
below is wired to ``HealthConfig``/``cli.py`` as of T-1.4; the queue/backoff/endpoint
constants are sourced here now but only swept into their ~15 call sites in T-3.5, so this
module's full constant set exists before every consumer has adopted it.
"""

from __future__ import annotations

#: Default bounded-queue capacity for a transport's inbound/outbound buffer.
DEFAULT_QUEUE_MAXSIZE = 1000

#: Default exponential-backoff policy (initial delay, cap, multiplier) for a reconnecting
#: transport.
DEFAULT_BACKOFF_INITIAL_S = 1.0
DEFAULT_BACKOFF_MAX_S = 30.0
DEFAULT_BACKOFF_FACTOR = 2.0

#: Default MAVLink source endpoint (a local, listening UDP port — the common SITL/companion
#: computer convention).
DEFAULT_MAVLINK_ENDPOINT = "udpin:127.0.0.1:14550"

# ── Service port table ──────────────────────────────────────────────────────────────────
# One place recording every port a meshsa-adjacent service binds by default, including
# external tools this codebase talks to but does not own — so a future addition can check
# here first instead of colliding the way HealthConfig and mavlink2rest did (T-1.4).
PORT_FTS_TCP = 8087
#: mavlink2rest's own upstream default (an external tool; meshsa does not claim this port —
#: see the T-1.4 CHANGELOG entry for why HealthConfig moved off it instead).
PORT_MAVLINK2REST = 8088
PORT_TAK_TLS = 8089
PORT_LLM = 8090
PORT_COMMANDER = 8095
PORT_DETECTION_INGEST = 8097
#: meshsa.health's /healthz + /metrics listener. Moved here from 8088 in T-1.4: 8088 is
#: mavlink2rest's upstream convention, and meshsa.ui.cli provably wires a health listener
#: and a mavlink2rest-backed data source into the same process.
PORT_HEALTH = 8098
PORT_SCOUT_STATION = 8099
PORT_UI = 8100
