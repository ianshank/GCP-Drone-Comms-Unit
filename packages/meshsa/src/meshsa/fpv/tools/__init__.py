"""Command-line tools for the FPV subsystem.

* ``fpv-telemetry-monitor`` — live CRSF ingest + health + echo/CRC counters.
* ``fpv-log-replay`` — replay ``telemetry.jsonl`` through store + monitor.
* ``fpv-log-convert`` — JSONL session -> Parquet (schema_version-aware).

Each ``main()`` configures structlog like :mod:`meshsa.cli`; the live loops and
the Parquet/serial glue are imported lazily and marked ``# pragma: no cover``.
"""
