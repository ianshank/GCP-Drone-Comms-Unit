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


def test_port_table_reflection_covers_every_port_constant():
    # Future PORT_* rows auto-enroll in the uniqueness check; a new row that
    # duplicates an existing value fails here without any test edit.
    ports = [value for name, value in vars(defaults).items() if name.startswith("PORT_")]
    assert ports, "PORT_* table is empty"
    assert len(ports) == len(set(ports)), f"duplicate port in the service-port table: {ports}"


def test_pinned_literal_values_are_preserved():
    # The regression net under the T-3.5a literal sweep: post-sweep, call-site
    # defaults and table entries are the same symbol, so comparing them is a
    # tautology — only these literal pins can catch a defaults.py edit silently
    # changing deployed behavior. Changing any pinned value is an operator-visible
    # change: CHANGELOG + ops docs in the same commit (T-1.4 precedent).
    assert defaults.PORT_FTS_TCP == 8087
    assert defaults.PORT_MAVLINK2REST == 8088
    assert defaults.PORT_TAK_TLS == 8089
    assert defaults.PORT_LLM == 8090
    assert defaults.PORT_COMMANDER == 8095
    assert defaults.PORT_DETECTION_INGEST == 8097
    assert defaults.PORT_HEALTH == 8098
    assert defaults.PORT_SCOUT_STATION == 8099
    assert defaults.PORT_UI == 8100
    assert defaults.DEFAULT_QUEUE_MAXSIZE == 1000
    assert (
        defaults.DEFAULT_BACKOFF_INITIAL_S,
        defaults.DEFAULT_BACKOFF_MAX_S,
        defaults.DEFAULT_BACKOFF_FACTOR,
    ) == (1.0, 30.0, 2.0)
    assert defaults.DEFAULT_MAVLINK_ENDPOINT == "udpin:127.0.0.1:14550"
