"""Tests for meshsa.defaults — the shared operational-default constants and service-port
table (code-hygiene-modularity T-1.4, pins and adoption asserts T-2.8/T-3.5a)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from meshsa import defaults, netauth
from meshsa.cli import parse_args
from meshsa.config import HealthConfig, NemotronConfig, NodeConfig, RouterConfig, ScoutConfig
from meshsa.transports.detection_ingest import DetectionIngestTransport
from meshsa.transports.tak import TakMulticastTransport, TakTcpTransport
from meshsa.ui.config import UIConfig


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
    assert defaults.PORT_TAK_MULTICAST == 6969
    assert defaults.PORT_FTS_REST == 19023
    assert defaults.DEFAULT_TAK_MULTICAST_GROUP == "239.2.3.1"
    assert defaults.DEFAULT_MULTICAST_IFACE == "0.0.0.0"
    assert defaults.DEFAULT_COT_STALE_S == 120.0
    assert defaults.DEFAULT_PLI_INTERVAL_S == 30.0
    assert defaults.DEFAULT_INFERENCE_BACKOFF_MAX_S == 30.0
    assert defaults.DEFAULT_INFERENCE_BACKOFF_BASE == 2.0


def test_inference_and_transport_backoff_stay_independent_knobs():
    # defaults.py argues these are separate policies that merely agree today. Equal
    # values make that claim invisible to any value assertion, so pin it structurally:
    # aliasing one to the other would couple radio reconnect tuning to LLM retries.
    src = Path(inspect.getfile(defaults)).read_text(encoding="utf-8")
    assert "DEFAULT_INFERENCE_BACKOFF_MAX_S = DEFAULT_BACKOFF_MAX_S" not in src
    assert "DEFAULT_INFERENCE_BACKOFF_BASE = DEFAULT_BACKOFF_FACTOR" not in src


def test_host_constants_pinned_and_semantically_loopback():
    # Two constants by design (bind default vs outbound connect target): every listener
    # bind is guarded fail-closed by netauth.validate_bind, but outbound targets have no
    # guard — a shared constant would let one edit silently redirect egress. The
    # is_loopback pin is the semantic half: a non-loopback value here would flip every
    # listener to refuse-at-startup (loud) but silently redirect every egress default.
    assert defaults.DEFAULT_LOOPBACK_HOST == "127.0.0.1"
    assert netauth.is_loopback(defaults.DEFAULT_LOOPBACK_HOST)
    assert defaults.DEFAULT_LOCAL_TARGET_HOST == "127.0.0.1"
    assert netauth.is_loopback(defaults.DEFAULT_LOCAL_TARGET_HOST)


#: Modules that only ever *connect out* — they open no listener, so importing the
#: bind-side default would be a category error. Keeping them free of that import is
#: the only mechanical guard available: both host constants hold "127.0.0.1", so a
#: value assertion cannot tell a misuse from correct code (this test exists because
#: llm/sources.py did exactly that and no value test noticed).
_CLIENT_ONLY_MODULES = ("llm/sources.py",)


def _imported_names(module_rel_path: str) -> set[str]:
    src_root = Path(inspect.getfile(defaults)).parent
    tree = ast.parse((src_root / module_rel_path).read_text(encoding="utf-8"))
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def test_client_only_modules_never_import_the_bind_host_default():
    for rel_path in _CLIENT_ONLY_MODULES:
        imported = _imported_names(rel_path)
        assert "DEFAULT_LOOPBACK_HOST" not in imported, (
            f"{rel_path} opens no listener; an outbound target must use "
            f"DEFAULT_LOCAL_TARGET_HOST so a future edit to the bind default "
            f"(loud — every listener re-validates) cannot silently retarget egress"
        )
        assert "DEFAULT_LOCAL_TARGET_HOST" in imported, (
            f"{rel_path} should source its connect-target host from "
            f"defaults.DEFAULT_LOCAL_TARGET_HOST"
        )


def _default_of(cls: type, param: str) -> object:
    return inspect.signature(cls.__init__).parameters[param].default


def test_transport_constructor_defaults_adopt_the_table():
    # The class of bug this catches: a sweep (or later edit) re-typing a literal that
    # drifts from the table — config models are covered by their own defaults, but
    # constructor keyword defaults and argparse defaults are invisible to them.
    assert _default_of(DetectionIngestTransport, "host") == defaults.DEFAULT_LOOPBACK_HOST
    assert _default_of(DetectionIngestTransport, "port") == defaults.PORT_DETECTION_INGEST
    assert _default_of(DetectionIngestTransport, "queue_maxsize") == defaults.DEFAULT_QUEUE_MAXSIZE
    assert _default_of(TakTcpTransport, "host") == defaults.DEFAULT_LOCAL_TARGET_HOST
    assert _default_of(TakTcpTransport, "backoff_max_s") == defaults.DEFAULT_BACKOFF_MAX_S
    assert _default_of(TakMulticastTransport, "group") == defaults.DEFAULT_TAK_MULTICAST_GROUP
    assert _default_of(TakMulticastTransport, "port") == defaults.PORT_TAK_MULTICAST
    assert _default_of(TakMulticastTransport, "iface") == defaults.DEFAULT_MULTICAST_IFACE


def test_config_model_defaults_adopt_the_table():
    assert RouterConfig().queue_maxsize == defaults.DEFAULT_QUEUE_MAXSIZE
    assert HealthConfig().host == defaults.DEFAULT_LOOPBACK_HOST
    assert ScoutConfig().station_host == defaults.DEFAULT_LOOPBACK_HOST
    assert ScoutConfig().station_port == defaults.PORT_SCOUT_STATION
    assert UIConfig().host == defaults.DEFAULT_LOOPBACK_HOST
    assert UIConfig().port == defaults.PORT_UI
    cfg = NodeConfig(uid="u", callsign="c")
    assert cfg.pli_interval_s == defaults.DEFAULT_PLI_INTERVAL_S
    assert cfg.default_stale_s == defaults.DEFAULT_COT_STALE_S
    # NemotronConfig declares its defaults via Field(default=...), the shape that
    # silently evaded literal_guard's magics rule until T-2.8's Field() unwrap.
    assert NemotronConfig().backoff_max_s == defaults.DEFAULT_INFERENCE_BACKOFF_MAX_S
    assert NemotronConfig().backoff_base == defaults.DEFAULT_INFERENCE_BACKOFF_BASE


def test_cli_argparse_defaults_adopt_the_table(monkeypatch):
    # Guards the exact mis-mapping this sweep's review caught pre-execution: swapping
    # --fts-port's default (8087, PORT_FTS_TCP) for PORT_HEALTH (8098) would have been
    # an operator-visible egress change no other test observed.
    for key in ("FTS_HOST", "FTS_PORT", "HEALTHZ_HOST", "HEALTHZ_PORT"):
        monkeypatch.delenv(f"MESHSA_{key}", raising=False)
    args = parse_args([])
    assert args.fts_host == defaults.DEFAULT_LOCAL_TARGET_HOST
    assert args.fts_port == defaults.PORT_FTS_TCP
    assert args.healthz_host == defaults.DEFAULT_LOOPBACK_HOST
    assert args.healthz_port == defaults.PORT_HEALTH
