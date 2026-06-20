# Next Steps

With the NVIDIA Nemotron Ultra integration complete and the technical debt resolved, the following areas represent the next phases of project maturity:

## 1. Field Testing & Hardware Integration
- Deploy the `meshsa-base` node with the `inference` feature enabled to a physical Raspberry Pi 5 or Jetson Orin Nano.
- Conduct a live field test to verify that Nemotron's tactical summaries of Meshtastic `CHAT` traffic are relayed cleanly to ATAK/FreeTAKServer over the `tak_tcp` bridge.

## 2. Expanded AI Capabilities (Tool-Use)
- Extend the `NemotronClient` to parse structured JSON outputs instead of raw text.
- Allow the AI to issue system commands or query local node status (e.g., asking "Who was last seen at coordinates X, Y?").

## 3. Operational Dashboards
- Consider adding a local web UI or Prometheus metrics endpoint to expose inference latency, API rate limits, and deduplication cache hits.

## 4. Hardware Updates
- Ensure the 3D-printable cases in `hardware/vcase` have adequate thermal dissipation for the Jetson Orin Nano when running heavy local bridges.
