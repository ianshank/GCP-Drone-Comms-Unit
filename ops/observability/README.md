# MeshSA Observability

Phase 4 observability artifacts: a Prometheus-scrapeable metrics endpoint
(already exported by `meshsa`) plus a Grafana dashboard mapping the exported
counters to the four golden signals.

The metric names are defined in
[`packages/meshsa/src/meshsa/metrics.py`](../../packages/meshsa/src/meshsa/metrics.py)
and served by
[`packages/meshsa/src/meshsa/health.py`](../../packages/meshsa/src/meshsa/health.py).
This folder only adds the dashboard and docs; no code emits new metrics here.

## 1. Enable the exporter

The `/metrics` route is opt-in. In the node's `HealthConfig` (see
[`config.py`](../../packages/meshsa/src/meshsa/config.py)) set:

- `metrics_enabled = true`
- `metrics_format = "prometheus"` (the default; `"json"` is also supported but
  the dashboard expects Prometheus text exposition)

The `/healthz` listener must also be running for the server to start. Defaults
(all overridable in config):

| Setting              | Default       |
| -------------------- | ------------- |
| `host`               | `127.0.0.1`   |
| `port`               | `8088`        |
| `metrics_path`       | `/metrics`    |
| `metrics_format`     | `prometheus`  |

Example config fragment:

```json
{
  "health": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8088,
    "metrics_enabled": true,
    "metrics_path": "/metrics",
    "metrics_format": "prometheus"
  }
}
```

The endpoint binds to loopback by default. If Prometheus runs on another host,
bind to a reachable interface deliberately and protect it at the network layer;
the endpoint has no authentication.

## 2. Point Prometheus at it

Add a scrape job (adjust `targets` to the node's host:port):

```yaml
scrape_configs:
  - job_name: meshsa
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8088"]
```

## 3. Import the dashboard

In Grafana: **Dashboards -> New -> Import**, then upload
[`grafana-meshsa-dashboard.json`](grafana-meshsa-dashboard.json). When prompted,
select your Prometheus data source for the `DS_PROMETHEUS` input. The dashboard
uses a templated datasource variable, so it imports against any Prometheus
source without editing a hard-coded UID.

## Golden-signal -> metric mapping

| Golden signal  | Metric(s)                                                                                  | Type / labels                 | PromQL on the dashboard                                  |
| -------------- | ------------------------------------------------------------------------------------------ | ----------------------------- | ------------------------------------------------------- |
| **Traffic**    | `meshsa_rx_total`, `meshsa_tx_total`, `meshsa_forwarded_total`                              | router counters               | `rate(<metric>[$__rate_interval])`                      |
| **Traffic**    | `meshsa_transport_rx_frames`                                                                | counter, `{transport="..."}`  | `rate(meshsa_transport_rx_frames[$__rate_interval])`   |
| **Errors**     | `meshsa_dropped_undecodable_total`, `meshsa_schema_mismatch_total`                          | router counters               | `rate(<metric>[$__rate_interval])`                      |
| **Errors**     | `meshsa_transport_dropped_inbox_full`                                                       | counter, `{transport="..."}`  | `rate(meshsa_transport_dropped_inbox_full[$__rate_interval])` |
| **Saturation** | `meshsa_transport_dropped_inbox_full`, `meshsa_transport_reconnects`                        | counters, `{transport="..."}` | raw counter (rising line = saturating)                  |
| **Latency**    | _none exported today_                                                                       | --                            | text panel only (see below)                             |

## Latency gap (honest note)

MeshSA does **not** export an end-to-end latency metric today. There is no
histogram in `metrics.py`, so the dashboard's Latency row is a text panel rather
than a fabricated series. Until a latency histogram lands (planned M3 work),
**reconnect frequency** (`meshsa_transport_reconnects`) and **inbox-full drop
rate** (`meshsa_transport_dropped_inbox_full`) serve as availability/back-pressure
proxies. Do not add latency PromQL to the dashboard until the metric actually
exists in `metrics.py`.

## Multi-process caveat

The exporter renders counters from in-process state (hand-rolled text, no
`prometheus_client` registry). The gateway runs single-process today, so this is
a non-issue. **If** it is ever run multi-process (e.g. under a multi-worker
server), each worker would expose only its own counters. In that case use the
`prometheus_client` multiprocess pattern: set `PROMETHEUS_MULTIPROC_DIR` to a
writable directory **and wipe that directory between runs** so stale per-process
files from a previous run do not inflate the aggregated series. This is
operational guidance only; no code in this repo reads that variable yet.

## Drift guard

`packages/meshsa/tests/test_metrics.py` asserts that `render_prometheus(...)`
emits every metric name this dashboard references. Renaming a metric in
`metrics.py` without updating
[`grafana-meshsa-dashboard.json`](grafana-meshsa-dashboard.json) will fail that
test.
