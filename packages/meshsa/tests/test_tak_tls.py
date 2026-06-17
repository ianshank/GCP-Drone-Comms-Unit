"""TLS option on TakTcpTransport: endpoint resolution + injected SSL context.

The real ``ssl`` handshake and ``asyncio.open_connection(ssl=...)`` are
``# pragma: no cover`` glue (exercised on deploy, not in CI); these tests cover
the pure scheme/port resolution and the wiring that selects/stores the context.
"""

from __future__ import annotations

import ssl

from meshsa.transports.tak import TakTcpTransport, _resolve_tak_endpoint


def test_resolve_endpoint_plaintext_default():
    assert _resolve_tak_endpoint("127.0.0.1", None, False) == ("127.0.0.1", 8087, False)


def test_resolve_endpoint_tls_default_port():
    assert _resolve_tak_endpoint("takserver", None, True) == ("takserver", 8089, True)


def test_resolve_endpoint_explicit_port_overrides_default():
    assert _resolve_tak_endpoint("h", 9000, True) == ("h", 9000, True)


def test_resolve_endpoint_tls_scheme_sets_tls_and_port():
    assert _resolve_tak_endpoint("tls://fts.example", None, False) == ("fts.example", 8089, True)


def test_resolve_endpoint_tcp_scheme_forces_plaintext():
    assert _resolve_tak_endpoint("tcp://fts.example", None, True) == ("fts.example", 8087, False)


def test_resolve_endpoint_embedded_port_is_parsed():
    assert _resolve_tak_endpoint("tls://fts.example:9001", None, False) == (
        "fts.example",
        9001,
        True,
    )


def test_tls_uses_injected_context_and_default_port():
    # An injected factory keeps the real ssl.* / cert I/O out of the test path; the
    # transport must store that context and pick the TLS default port (8089).
    ctx = ssl.create_default_context()
    t = TakTcpTransport(host="takserver", tls=True, ssl_context_factory=lambda: ctx)
    assert t.tls is True
    assert t.port == 8089
    assert t._ssl_context is ctx


def test_plaintext_default_has_no_ssl_context():
    # The default (no connector, no TLS) path stays plaintext on 8087 with no context.
    t = TakTcpTransport(host="127.0.0.1")
    assert t.tls is False
    assert t.port == 8087
    assert t._ssl_context is None
