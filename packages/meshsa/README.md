# meshsa — modular mesh situational-awareness framework

A small, transport-agnostic Python framework for the distributable-node SA system.
It encodes the revised architecture: simple **user nodes** you hand out, **backbone**
nodes, and one **base** node — all speaking the same versioned message envelope over
whatever transports are configured.

## Design (maps to the peer-review fixes)
- **No hard-coded values.** Every operational parameter (intervals, stale times,
  dedupe cache size, queue sizes, channel/PSK/region/frequency) is a field on a
  Pydantic model in `meshsa.config` with an explicit, overridable default. Load from
  a mapping, a JSON file, or env vars (`NodeConfig.from_env`).
- **Modular / backward compatible.**
  - New transports/codecs self-register in `meshsa.registry` (open/closed) — adding a
    medium never edits the core.
  - Every `Envelope` carries `schema_version`; peers accept `[MIN_COMPATIBLE_SCHEMA,
    SCHEMA_VERSION]` (`meshsa.version.is_compatible`). The codec drops incompatible
    frames instead of crashing.
  - `build_node` **skips unknown transport types**, so a node tolerates configs
    written for newer or older builds.
- **Dependency injection via `typing.Protocol`.** `Transport`, `Codec`, `Clock`,
  `IdFactory` are structural interfaces; the router/node take real or fake
  implementations, so everything tests without a network.
- **Router = bridge with loop prevention.** Dedupes by `msg_id`, forwards between
  transports, delivers to subscribers — the same logic that lets a base node bridge
  LoRa ↔ HaLow ↔ IP cleanly.

## Layout
```
meshsa/
  version.py      schema version + compatibility window
  errors.py       exception hierarchy
  models.py       Position, NodeInfo, Envelope, payloads (Pydantic)
  config.py       NodeConfig/MeshConfig/RouterConfig/TransportConfig
  protocols.py    Transport/Codec/Clock/IdFactory + default impls
  registry.py     open/closed component registry
  codec.py        JsonCodec (CoT/XML codec can be added later)
  router.py       publish / pump / dedupe / bridge / subscribe
  node.py         build_node(config) -> Node
  transports/     loopback, null, meshtastic_radio (real API),
                  tak (TCP -> FreeTAKServer, UDP multicast -> ATAK), base;
                  mavlink_source / msp_source / crsf_source (receive-only
                  flight-source transports -> drone/FPV ATAK air tracks)
  cot.py          Cursor-on-Target codec (ATAK / WinTAK / iTAK / FreeTAKServer)
  compact.py      compact binary codec sized for LoRa (~40 B PLI vs ~220 B JSON)
```

## Quick start
```python
from meshsa import NodeConfig, Position, build_node

cfg = NodeConfig.from_file("example_user_node.json")
node = build_node(cfg)
node.on_message(lambda env: print("rx", env.kind, env.source_uid))
await node.start()
await node.publish_position(Position(lat=37.0, lon=-122.0))
```

## Adding a real radio (no core changes)
```python
from meshsa.registry import transport_registry
from meshsa.transports.base import AbstractTransport

@transport_registry.register("meshtastic")
def _make(name="meshtastic", port="/dev/ttyUSB0", **kw):
    return MeshtasticTransport(name=name, port=port, **kw)   # your impl
```
Then reference `{"name": "lora", "type": "meshtastic", "options": {"port": "..."}}`
in the node config. Same pattern for a HaLow/IP transport or a CoT codec.

## Tests & coverage
`pytest` → **101 passed, 100% statement + branch coverage** (`--cov-fail-under=90`
enforced in `pyproject.toml`). Tests inject a `FakeClock`, sequential id factory,
in-memory `LoopbackBus`, and a fake Meshtastic interface + pubsub, so they run with
no radio and no network. Hardware/library binding glue (building the real serial/TCP
interface and pypubsub hooks) is the only code marked `# pragma: no cover`.

## Talking to ATAK / FreeTAKServer
The `cot` codec maps Envelopes to/from Cursor-on-Target XML (PLI → position track,
CHAT → GeoChat). The router supports **per-transport codecs**, so one node can run
JSON on the mesh and CoT toward TAK and translate on the bridge:

```json
"transports": [
  { "name": "mesh", "type": "meshtastic", "options": { "port": "/dev/ttyUSB0" } },
  { "name": "tak",  "type": "tak_tcp", "codec": "cot",
    "options": { "host": "127.0.0.1", "port": 8087 },
    "codec_options": { "stale_s": 60 } }
]
```
A CoT frame arriving on `tak` is decoded once, delivered to subscribers, and
re-encoded as JSON for the `mesh` side (and vice-versa). Backward compatible: omit
`codec` and every transport uses the node default.

## TAK transports (end-to-end bridge)
- `tak_tcp` streams CoT to/from a TAK server (FreeTAKServer, default `:8087`); a
  `CotFramer` reassembles `<event>...</event>` documents from the byte stream and
  resyncs past partial/garbage data. It **auto-reconnects with exponential backoff**
  (`reconnect`, `backoff_initial_s`, `backoff_max_s`, `backoff_factor` — all config
  options; the backoff `sleep` is injectable for tests). `start()` establishes the
  first connection before returning so early sends aren't dropped; while transiently
  disconnected, sends are best-effort dropped rather than raising.
  - **TLS** (FreeTAKServer `:8089`): set `tls: true` plus any of `tls_cafile`,
    `tls_certfile`, `tls_keyfile`, `tls_verify` (default `true`), `tls_check_hostname`
    (default `true`), `tls_server_hostname`. The SSL context is built and validated at
    construction (fail-fast); an injected `connector` overrides it. `tls: false`
    (default) keeps the plain `:8087` path byte-for-byte.
  - **Pacing**: `pace_min_interval_s` (default `0` = off) enforces a minimum hold
    between outbound CoT frames (PyTAK `FTS_COMPAT` style) so a fast source doesn't
    overrun a rate-limited FTS; `clock` is injectable for tests.
- `tak_multicast` exchanges CoT datagrams on ATAK's SA group (default
  `239.2.3.1:6969`). Not paced (fan-out group, no FTS rate limit).

Both put network I/O behind injected collaborators (`connector` for TCP,
`io_factory` for multicast), so the framing/bridge logic is fully tested with
fakes; only the real socket builders are `# pragma: no cover`. The suite includes
a config-driven bridge e2e test: a node with a loopback mesh side (JSON) and a
loopback TAK side (CoT) publishes a position, then bridges an inbound CoT event
back onto the mesh as JSON.

## Runnable field example (real hardware)
`src/meshsa/examples/base_node.py` wires a **real** T-Beam (Meshtastic over USB) to a **real**
FreeTAKServer (no fakes) and runs the JSON-mesh <-> CoT-TAK bridge, broadcasting its
own position on an interval. Install with the meshtastic extra, then run the
installed console script:

    pip install -e ".[meshtastic]"
    meshsa-base --port /dev/ttyUSB0 --fts-host 127.0.0.1 \
        --lat 37.0 --lon -122.0 --callsign BASE1

All flags also read from the environment (`MESHSA_PORT`, `MESHSA_FTS_HOST`, ...);
CLI wins. Ctrl-C shuts down cleanly. The TAK link reconnects on its own if FTS
restarts.

## Meshtastic transport
`MeshtasticTransport` wraps a real device interface (serial/TCP/BLE) and the pypubsub
receive bus, both injectable for testing. Sends via `sendData` on a configurable
portnum/destination/channel; receive callbacks (radio reader thread) hand bytes to the
asyncio inbox via `call_soon_threadsafe`. It **auto-reconnects with backoff**: a
supervisor rebuilds the interface when Meshtastic publishes `connection.lost`, and
`start()` brings up the first connection before returning. While disconnected, sends
are best-effort dropped rather than raising.

**Use the `compact` codec on the mesh, not JSON.** A JSON PLI envelope is ~220 bytes
— at/over Meshtastic's ~237 B single-packet limit. The `compact` binary codec encodes
the same PLI in ~40 bytes (lat/lon as scaled int32 ≈1.1 cm, altitude in metres, ce/le
clamped to uint16; other kinds fall back to compact-JSON). Pair it per-transport:
`{ "name": "lora", "type": "meshtastic", "codec": "compact",
"options": { "connection": "serial", "port": "/dev/ttyUSB0", "portnum": 256 } }`.
