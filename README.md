# jetson-flight-control

A distributed mesh situational-awareness (SA) system for field operations. Bridges
LoRa (Meshtastic), HaLow 802.11s, and IP mesh networks with TAK / ATAK servers for
real-time position and chat.

This monorepo contains the Python framework, deployment kits, and 3D-printable
hardware designs for the system.

## Layout

| Path                                | What lives here                                                          |
|-------------------------------------|--------------------------------------------------------------------------|
| [packages/meshsa](packages/meshsa)  | `meshsa` Python framework (registry-based codecs + transports, src layout) |
| [ops/pi5-node](ops/pi5-node)        | Raspberry Pi 5 user-node provisioning (`mesh-up.sh`, `setup_pi5_node.sh`) |
| [ops/base-service](ops/base-service)| Base-node systemd service unit + install guide                           |
| [hardware/gcs-stls](hardware/gcs-stls) | Pelican 1400 GCS 3D-printable parts                                  |
| [hardware/usernode-stls](hardware/usernode-stls) | User-node enclosures (Pi 5, T-Beam)                         |
| [hardware/vcase](hardware/vcase)    | Vertical Jetson Orin Nano case                                           |
| [docs](docs)                        | Architecture, audit report                                               |
| [tools](tools)                      | `Dockerfile`, `Makefile`                                                 |
| [.github/workflows](.github/workflows) | CI + release pipelines                                                |
| [archive](archive)                  | Historical ZIP snapshots (read-only)                                     |

## Quick start (development)

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -e "packages/meshsa[dev]"
cd packages/meshsa && pytest    # 98 tests, 100% coverage
```

For real-radio runs (Meshtastic + FreeTAKServer bridge):

```bash
pip install -e "packages/meshsa[meshtastic]"
meshsa-base --port /dev/ttyUSB0 --fts-host 127.0.0.1 \
  --lat 37.0 --lon -122.0 --callsign BASE1
```

See [packages/meshsa/README.md](packages/meshsa/README.md) for framework details,
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system design, and
[docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md) for known gaps and the backlog.

## Deployment

- Base node (Jetson or Pi running the Meshtastic <-> TAK bridge):
  [ops/base-service/INSTALL_base_node.md](ops/base-service/INSTALL_base_node.md)
- Pi 5 user node (HaLow mesh + ADS-B):
  [ops/pi5-node/README_pi5_node.md](ops/pi5-node/README_pi5_node.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security disclosures go through
[SECURITY.md](SECURITY.md).

## License

[Apache-2.0](LICENSE) (placeholder pending owner confirmation).
