---
name: meshsa-observability
description: "Use when: adding or changing metrics/health export — RouterMetrics, render_prometheus, per-transport counters, the /metrics or /healthz route, HealthConfig fields, or a Grafana golden-signal dashboard."
argument-hint: "The metric/health surface to add or change"
---

# MeshSA Observability (metrics & health)

Export is already shipped — extend it, don't reinvent it. No new runtime dependency: the
Prometheus exposition is hand-rolled in `metrics.py`.

## When to Use

- Adding a counter/gauge, a new `meshsa_*` series, a health-snapshot field, or a dashboard.
- Wiring metrics onto the health listener or building the Grafana artifact (plan Track A.1).

## Procedure

1. Counters live on `RouterMetrics` (and per-transport on the transport). Surface them via
   `RouterMetrics.as_dict()` and `meshsa.render_prometheus(metrics, transports)` — keep the
   series names stable (`meshsa_rx_total`, `meshsa_tx_total`, `meshsa_forwarded_total`,
   `meshsa_dropped_undecodable_total`, `meshsa_schema_mismatch_total`, and per-transport
   `meshsa_transport_{dropped_inbox_full,reconnects,rx_frames}{transport="..."}`). Renaming a
   series is a breaking change for dashboards/alerts — treat it like a wire change.
2. The `/metrics` route is opt-in on the health listener, gated by `HealthConfig`
   (`metrics_enabled`/`metrics_path`/`metrics_format`). Add new toggles as config fields with
   explicit defaults — no literals.
3. **Golden signals (SRE):** map latency / traffic / errors / saturation onto the existing
   `rx/tx/forwarded/dropped/reconnects` + per-transport counters. The Grafana dashboard
   (`ops/observability/grafana-meshsa-dashboard.json`) is a templated JSON artifact —
   datasource/job/interval are dashboard variables, not baked values.
4. **Guard exporter/dashboard drift:** add a pure test asserting every `meshsa_*` series a
   dashboard references is actually produced by `render_prometheus`.
5. If the gateway is ever run multi-process, set **and wipe** `PROMETHEUS_MULTIPROC_DIR`
   between runs.
6. **Optional inference series (only when `node.inference_service` is set):** the same pattern
   extends to `meshsa.inference` — `InferenceService.as_dict()` surfaces
   `offline_dropped`/`offline_queue_depth`/`intake_dropped`/`pending_tasks`, which
   `render_prometheus(metrics, transports, *, inference=...)` renders as
   `meshsa_inference_offline_dropped_total`, `meshsa_inference_intake_dropped_total` (counters)
   and `meshsa_inference_offline_queue_depth`, `meshsa_inference_pending_tasks` (gauges). When
   `inference` is omitted/`None` (inference disabled), no `meshsa_inference_*` lines are emitted
   at all — don't emit zero-valued placeholders. `health.render_metrics` wires this end to end:
   it reads `node.inference_service.as_dict()` and includes it as `body["inference"]` for the
   json format or folds it into the same Prometheus text via `render_prometheus(...,
   inference=...)`. The Grafana dashboard's "AI Inference" row (2 panels: drops-per-second from
   the counters, and a saturation panel from the two gauges) follows the same
   variables-not-baked-values convention as the rest of the dashboard.

## Procedure (gates)

Run from `packages/meshsa`: `python -m pytest`, `mypy src`, `ruff check .`,
`ruff format --check .`.

## References

- `packages/meshsa/src/meshsa/metrics.py` (`RouterMetrics`, `render_prometheus`)
- `packages/meshsa/src/meshsa/health.py`, `config.py` (`HealthConfig`)
- `packages/meshsa/src/meshsa/transports/polling_source.py` (`rx_frames`, link log)
- `packages/meshsa/src/meshsa/inference.py` (`InferenceService.as_dict`) — see also
  `.agents/skills/meshsa-inference/SKILL.md` for the config/behavior side of these counters
- `packages/meshsa/tests/test_metrics.py` — `test_render_prometheus_emits_all_dashboard_metric_names`
  is the drift-guard: it asserts all 12 dashboard-referenced names (5 router + 3 per-transport +
  4 inference) are actually produced by `render_prometheus`. Adding/renaming a series must update
  this test's expected set in the same change.
- `ops/observability/grafana-meshsa-dashboard.json` ("AI Inference" row) and
  `ops/observability/README.md`
- Google SRE golden signals: https://sre.google/sre-book/monitoring-distributed-systems/
