# SA Assistant — read-only LLM over drone telemetry + TAK tracks

A natural-language assistant for the dashboard MVP. It answers questions like
*"what's the drone's altitude and battery?"* or *"summarize the tracks on the
TAK network"* by **reading** the same services `start_all.sh` already runs
(mavlink2rest `:8088`, FreeTAKServer). It is **strictly read-only and
advisory** — every tool only reads state, so the assistant can never arm the
vehicle, change a flight mode, or alter a track. Anything that changes vehicle
or mission state stays in the flight-control UI.

The implementation lives in the framework as [`meshsa.llm`](../../packages/meshsa/src/meshsa/llm);
this folder is the ops/runbook layer.

## Install

```bash
pip install -e "packages/meshsa[llm]"     # anthropic + aiohttp
export ANTHROPIC_API_KEY=sk-ant-...        # required
```

## Run

```bash
cp flightctl/llm/llm.env.example flightctl/llm/llm.env   # then edit
set -a; . flightctl/llm/llm.env; set +a
meshsa-llm                                  # serves on :8090
```

Open `http://<unit>:8090/` for the chat widget, or `POST /chat`:

```bash
curl -s localhost:8090/chat -H 'content-type: application/json' \
  -d '{"prompt":"what is the drone altitude and battery?"}' | jq
# {"reply":"...", "tools":["get_drone_state"], "stop_reason":"end_turn"}
```

`GET /healthz` returns `{"status":"ok"}`.

## Embed in the dashboard (Cockpit)

The MVP single pane is [Blue Robotics Cockpit](https://github.com/bluerobotics/cockpit)
(see the dashboard design notes). Add the assistant as an **iframe widget**
pointed at `http://<unit>:8090/` — the widget is a self-contained page that POSTs
to its own `/chat`, so no extra wiring is needed.

## Configuration

| Env var | Default | Purpose |
| ------- | ------- | ------- |
| `ANTHROPIC_API_KEY` | — | **Required.** Anthropic API key. |
| `MESHSA_LLM_MODEL` | `claude-opus-4-8` | Claude model id. |
| `MESHSA_LLM_HOST` | `0.0.0.0` | Bind host. |
| `MESHSA_LLM_PORT` | `8090` | Bind port. |
| `MESHSA_MAVLINK2REST_URL` | `http://127.0.0.1:8088` | mavlink2rest base URL (from `start_all.sh`). |
| `MESHSA_DRONE_UID` | `uav-1` | UID used in telemetry replies. |
| `MESHSA_FTS_TRACKS_URL` | `http://127.0.0.1:19023/ManageGeoObject/getCoTGeoObject` | FreeTAKServer active-CoT endpoint. |

## Notes / hardening

- **Keep it read-only.** The tool surface (`get_drone_state`, `list_tracks`) only
  reads. If a future command tool is added, gate it behind explicit operator
  confirmation — do not let the model issue commands autonomously.
- The server returns upstream failures as a clean `502` with the message rather
  than a stack trace; telemetry/track sources fail soft (a downed link yields a
  "link DOWN" / empty-tracks answer rather than an error).
- Never commit `llm.env` — it holds your API key. Only `llm.env.example` is tracked.
