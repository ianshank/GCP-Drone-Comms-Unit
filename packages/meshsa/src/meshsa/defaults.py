"""Single source of truth for cross-module operational defaults (CHARTER §4 Invariant 5:
every operational value is a config field with an explicit default — this module is where
those defaults live, so they stop being copy-pasted literals at each call site).

A leaf module: no imports from the rest of ``meshsa``, so every config model and transport
can depend on it without risk of a cycle.

Adoption history (code-hygiene-modularity tasks.md): the service-port table was wired to
``HealthConfig``/``cli.py`` in T-1.4; the queue/backoff/endpoint/host constants were swept
into every transport constructor in T-3.5a; the log-cadence, source-timing, serial-device
and geodesy rows below landed with the Phase 3 sweep (plan P3-1). ``literal_guard``
(``tools/claude_hooks/literal_guard.py``) fails CI when a ``PORT_*`` value, a loopback/any
host string, a queue/backoff default or a MAVLink endpoint is re-typed outside this module.
"""

from __future__ import annotations

#: Default bounded-queue capacity for a transport's inbound/outbound buffer.
DEFAULT_QUEUE_MAXSIZE = 1000

#: Default exponential-backoff policy (initial delay, cap, multiplier) for a reconnecting
#: transport.
DEFAULT_BACKOFF_INITIAL_S = 1.0
DEFAULT_BACKOFF_MAX_S = 30.0
DEFAULT_BACKOFF_FACTOR = 2.0

#: Retry policy for the inference HTTP client. Numerically equal to the transport
#: reconnect schedule above, but deliberately a SEPARATE pair: a reconnecting radio
#: transport and an outbound model API are different policies that happen to agree
#: today, and sharing one constant would make a transport tuning change silently
#: retune inference retries. (Same reasoning as DEFAULT_LOOPBACK_HOST vs
#: DEFAULT_LOCAL_TARGET_HOST — equal values, independent knobs.)
DEFAULT_INFERENCE_BACKOFF_MAX_S = 30.0
DEFAULT_INFERENCE_BACKOFF_BASE = 2.0

#: Default MAVLink source endpoint (a local, listening UDP port — the common SITL/companion
#: computer convention).
DEFAULT_MAVLINK_ENDPOINT = "udpin:127.0.0.1:14550"

# ── Host defaults ───────────────────────────────────────────────────────────────────────
#: Default host for a service *listener* (bind). Deliberately a separate constant from
#: DEFAULT_LOCAL_TARGET_HOST: every listener bind is guarded fail-closed by
#: meshsa.netauth.validate_bind, while outbound connect targets have no such guard — a
#: single shared constant would let one future edit silently redirect egress. Both
#: values are pinned (literal + netauth.is_loopback) in tests/test_defaults.py.
DEFAULT_LOOPBACK_HOST = "127.0.0.1"

#: Default host for an outbound *connect target* (TAK TCP client, FTS CoT egress) that
#: happens to be local by convention. See DEFAULT_LOOPBACK_HOST for why the two exist.
DEFAULT_LOCAL_TARGET_HOST = "127.0.0.1"

#: All-interfaces address for the one intentional bind-all surface (TAK multicast,
#: AUDIT_M2_AUTH.md surface #2 — a declared bind_guard exception, not a waiver).
DEFAULT_MULTICAST_IFACE = "0.0.0.0"

#: ATAK SA multicast convention (group, and PORT_TAK_MULTICAST below).
DEFAULT_TAK_MULTICAST_GROUP = "239.2.3.1"

# ── Timing defaults shared by more than one call site ──────────────────────────────────
#: CoT event stale window (seconds): how long a consumer should treat a PLI as current.
DEFAULT_COT_STALE_S = 120.0

#: Position-report (PLI) send interval (seconds).
DEFAULT_PLI_INTERVAL_S = 30.0

#: Throttled-log cadence shared by the transport inbox-full warning (`transports/base.py`)
#: and the polling sources' link-health line: the 1st event, then every Nth. A stuck
#: consumer can drop thousands of frames a second, so one line per frame is not an option.
DEFAULT_LOG_EVERY_N = 100

#: Upper bound between two link-health log lines from a polling source (seconds). Equal
#: to DEFAULT_PLI_INTERVAL_S and DEFAULT_BACKOFF_MAX_S by coincidence — independent knobs,
#: never alias them.
DEFAULT_LINK_LOG_INTERVAL_S = 30.0

#: Poll cadence of the serial source transports (MSP and CRSF) between frames (seconds).
DEFAULT_SOURCE_POLL_INTERVAL_S = 1.0

#: How long a polling source waits for its reader thread to exit on stop (seconds).
DEFAULT_SOURCE_JOIN_TIMEOUT_S = 2.0

#: Total HTTP timeout for the assistant's upstream reads (mavlink2rest, FTS tracks). Short
#: on purpose: the sources are on the same host or LAN, and the chat request is waiting.
DEFAULT_HTTP_SOURCE_TIMEOUT_S = 3.0

#: Browser poll cadence of the scout station page (seconds); the operator console's
#: ``UIConfig.poll_interval_s`` is the same knob for the other page.
DEFAULT_STATION_POLL_INTERVAL_S = 3.0

#: Raster tile template the scout station map loads from the operator's browser. Third-party
#: egress: an offline deployment points ``ScoutConfig.station_tile_url`` at a local server.
DEFAULT_STATION_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# ── Serial devices ──────────────────────────────────────────────────────────────────────
# Every one is overridable (CLI flag, transport option or env); named here so the three
# conventions are visible side by side. The udev alias ``/dev/meshsa-radio`` in
# ops/base-service/base.env.example is the deployment override of the first.
#: Meshtastic T-Beam over USB serial (``meshsa-base --port``).
DEFAULT_MESHTASTIC_SERIAL_DEVICE = "/dev/ttyUSB0"
#: MSP flight controller over USB CDC (``msp_source`` ``device`` option).
DEFAULT_MSP_SERIAL_DEVICE = "/dev/ttyACM0"
#: CRSF handset line on the Pi's UART (``CrsfLinkSettings.crsf_device``).
DEFAULT_CRSF_SERIAL_DEVICE = "/dev/ttyAMA0"

# ── Protocol conventions ────────────────────────────────────────────────────────────────
#: Meshtastic PortNum for application payloads (``PRIVATE_APP``); shared by the radio
#: transport default and ``meshsa-base --portnum``.
DEFAULT_MESHTASTIC_PORTNUM = 256

#: Mean Earth radius (m) for the equirectangular/haversine helpers in ``cv/geo.py`` and
#: ``scout/survey.py`` — one value so the two projections cannot drift apart.
EARTH_RADIUS_M = 6_371_000.0

# ── Service port table ──────────────────────────────────────────────────────────────────
# One place recording every port a meshsa-adjacent service binds by default, including
# external tools this codebase talks to but does not own — so a future addition can check
# here first instead of colliding the way HealthConfig and mavlink2rest did (T-1.4).
#: TAK multicast SA (bidirectional UDP; pairs with DEFAULT_TAK_MULTICAST_GROUP).
PORT_TAK_MULTICAST = 6969
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
#: FreeTAKServer's REST API upstream default (external tool; meshsa does not claim this
#: port — llm/sources.py composes its tracks URL from it).
PORT_FTS_REST = 19023
#: FreeTAKServer's web UI (external; ``start_all.sh`` FTS_UI_PORT, the Pi provisioning
#: script's "FreeTAKServer UI" hint).
PORT_FTS_UI = 5000
#: FreeTAKHub WebMap, a Node-RED flow (external; ``start_all.sh`` WEBMAP_PORT).
PORT_WEBMAP = 1880
#: mavp2p ``udpc`` fan-out to the meshsa gateway (``start_all.sh`` GW_PORT; the two
#: ``flightctl/configs/jetson_gateway.*.json`` endpoints).
PORT_MAVP2P_GATEWAY = 14551
#: mavp2p ``udpc`` fan-out to mavlink2rest (``start_all.sh`` M2R_UDP_PORT).
PORT_MAVP2P_MAVLINK2REST = 14552
#: dump1090 Beast output consumed by adsbcot (``setup_pi5_node.sh`` FEED_URL).
PORT_DUMP1090_BEAST = 30005
#: ArduPilot SITL's MAVLink TCP (``flightctl/configs/jetson_command.json``).
PORT_SITL_TCP = 5762

# External conventions this codebase talks to but does not own, recorded so a future
# addition checks here first (the T-1.4 lesson): MAVLink UDP telemetry rendezvous is
# 14550 (meshsa listens via DEFAULT_MAVLINK_ENDPOINT; the jetson package's udpout
# sender — packages/jetson_yolo_gcs core/config.py — is the other end of the same
# rendezvous and deliberately does not import this module); RTP video is 5600.
