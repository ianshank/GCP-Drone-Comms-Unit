"""Credential fields never appear in a model or dataclass ``repr`` (plan P3-5 review).

Every ``exc_info=True`` warning renders a traceback; with ``rich`` importable, structlog's
default renderer prints frame *locals*, and a ``ServerConfig`` or ``ServiceAuth`` is a local
of the frames that catch. ``configure_logging`` pins a plain formatter; this is the second
layer, so a ``repr`` reached by any route still cannot disclose the secret.
"""

from __future__ import annotations

import structlog

from meshsa._web import ServiceAuth
from meshsa.cli import configure_logging
from meshsa.config import MeshConfig, ScoutConfig
from meshsa.health import HealthConfig
from meshsa.inference.config import NemotronConfig
from meshsa.llm.server import ServerConfig
from meshsa.ui.config import UIConfig

SECRET = "s3cr3t-VALUE-9f8e7d"


def test_credential_fields_are_hidden_from_repr() -> None:
    holders = [
        ServerConfig(token=SECRET),
        UIConfig(token=SECRET),
        HealthConfig(token=SECRET),
        ScoutConfig(station_token=SECRET),
        MeshConfig(psk=SECRET),
        NemotronConfig(api_key=SECRET),
        ServiceAuth("meshsa-ui", SECRET),
    ]
    for holder in holders:
        assert SECRET not in repr(holder), type(holder).__name__
        assert SECRET not in str(holder), type(holder).__name__
    # The value itself is intact: repr hiding is not normalisation.
    assert ServerConfig(token=SECRET).token == SECRET
    assert ServiceAuth("meshsa-ui", SECRET).token == SECRET


def test_configure_logging_pins_a_plain_traceback_formatter() -> None:
    """Log content must not depend on whether ``rich`` happens to be installed."""
    before = structlog.get_config()
    try:
        configure_logging()
        renderer = structlog.get_config()["processors"][-1]
        assert isinstance(renderer, structlog.dev.ConsoleRenderer)
        assert renderer._exception_formatter is structlog.dev.plain_traceback
        configure_logging("WARNING")  # the level form still sets the filtering wrapper
        assert structlog.get_config()["processors"][-1]._exception_formatter is (
            structlog.dev.plain_traceback
        )
    finally:
        structlog.configure(**before)
