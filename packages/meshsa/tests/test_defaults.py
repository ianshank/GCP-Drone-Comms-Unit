"""Tests for meshsa.defaults — the shared operational-default constants and service-port
table (code-hygiene-modularity T-1.4)."""

from __future__ import annotations

from meshsa import defaults
from meshsa.config import HealthConfig


def test_service_ports_are_unique():
    ports = [
        defaults.PORT_FTS_TCP,
        defaults.PORT_MAVLINK2REST,
        defaults.PORT_TAK_TLS,
        defaults.PORT_LLM,
        defaults.PORT_COMMANDER,
        defaults.PORT_DETECTION_INGEST,
        defaults.PORT_HEALTH,
        defaults.PORT_SCOUT_STATION,
        defaults.PORT_UI,
    ]
    assert len(ports) == len(set(ports)), f"duplicate port in the service-port table: {ports}"


def test_health_port_no_longer_collides_with_mavlink2rest():
    # Regression (code-hygiene-modularity T-1.4): HealthConfig.port used to default to
    # 8088, which is mavlink2rest's own upstream convention; meshsa.ui.cli wires a health
    # listener and a mavlink2rest-backed source into the same process.
    assert defaults.PORT_HEALTH != defaults.PORT_MAVLINK2REST


def test_health_config_sources_its_default_from_the_table():
    assert HealthConfig().port == defaults.PORT_HEALTH
